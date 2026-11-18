"""Image Ads studio, persistent compositions and recoverable job attempts."""
import base64
import hashlib
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ad_copy import CopyUnavailable, generate_copy, lead_facts, stored_json
from .config import settings
from .db import SessionLocal, get_db
from .job_tracking import ACTIVE, finish_task, job_payload, start_task
from .media import image_from_bytes, require_lead, selected_media
from .models import ImageAd, Job, Lead, LeadWebsite
from .site_style import website_art
from .website_identity import homepage_identity

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
logger = logging.getLogger(__name__)
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='image-ads')
queue_lock = Lock()
FORMATS = {'square': (1080, 1080), 'portrait': (1080, 1350),
           'story': (1080, 1920), 'landscape': (1920, 1080)}


class Composition(BaseModel):
    mode: str
    format: str
    message: str = Field(min_length=1, max_length=220)
    objective: str = Field('', max_length=300)
    mood: str = Field('', max_length=300)
    colors: str = Field('', max_length=180)
    emphasize: str = Field('', max_length=300)
    avoid: str = Field('', max_length=300)
    media_ids: list[str] = Field(default_factory=list, max_length=4)
    logo_id: str | None = None
    position: str = 'bottom'
    fit: str = 'contain'
    alignment: str = 'left'
    text_color: str = Field('#ffffff', pattern=r'^#[0-9a-fA-F]{6}$')


def identity_for(db, lead):
    row = db.scalar(select(LeadWebsite).where(LeadWebsite.lead_id == lead.id))
    if row:
        return {**website_art(stored_json(row.content_json, {})), 'source': 'site_ai'}
    return homepage_identity(lead.website)


def generate_background(prompt, format_name, refs):
    cfg = settings()
    if not cfg.openai_api_key:
        raise ValueError('Configurez la clé OpenAI pour la création IA.')
    size = {'square': '1024x1024', 'portrait': '1024x1536', 'story': '1024x1536',
            'landscape': '1536x1024'}[format_name]
    headers = {'Authorization': 'Bearer ' + cfg.openai_api_key}
    options = {'model': cfg.openai_image_model, 'prompt': prompt, 'size': size,
               'quality': 'medium', 'output_format': 'png'}
    url = 'https://api.openai.com/v1/images/'
    if refs:
        response = httpx.post(url + 'edits', data=options, headers=headers, timeout=180,
                              files=[('image[]', ('reference.png', data, 'image/png')) for data in refs])
    else:
        response = httpx.post(url + 'generations', json=options, headers=headers, timeout=180)
    response.raise_for_status()
    raw = base64.b64decode(response.json()['data'][0]['b64_json'], validate=True)
    if len(raw) > 24 * 1024 * 1024:
        raise ValueError('Visuel OpenAI trop volumineux.')
    image_from_bytes(raw)
    return raw


def compose(background, logo, options):
    width, height = FORMATS[options['format']]
    source = image_from_bytes(background)
    canvas = Image.new('RGBA', (width, height), '#171c2e')
    image = (ImageOps.fit(source, (width, height)) if options['fit'] == 'cover'
             else ImageOps.contain(source, (width, height)))
    canvas.alpha_composite(image, ((width - image.width) // 2, (height - image.height) // 2))
    padding = round(min(width, height) * .065)
    if logo:
        brand = image_from_bytes(logo)
        brand.thumbnail((width // 4, height // 9), Image.Resampling.LANCZOS)
        canvas.alpha_composite(brand, (padding, padding))
    overlay = Image.new('RGBA', canvas.size)
    draw = ImageDraw.Draw(overlay)
    # Pixel-based wrapping keeps even long unbroken words inside the output frame.
    fontsize = round(min(width, height) * .062)
    font = ImageFont.truetype('DejaVuSans-Bold.ttf', fontsize)
    lines = []
    for paragraph in options['message'].splitlines():
        line = ''
        for word in paragraph.split():
            test = f'{line} {word}'.lstrip()
            if line and draw.textlength(test, font=font) > width - 4 * padding:
                lines.append(line)
                line = ''
            for char in word:
                if draw.textlength(line + char, font=font) > width - 4 * padding:
                    lines.append(line)
                    line = ''
                line += char
            line += ' '
        lines.append(line.strip())
    text = '\n'.join(lines)
    box = draw.multiline_textbbox((0, 0), text, font=font, spacing=12)
    while box[3] - box[1] > height * .49 and fontsize > 10:
        fontsize -= 3
        font = ImageFont.truetype('DejaVuSans-Bold.ttf', fontsize)
        box = draw.multiline_textbbox((0, 0), text, font=font, spacing=12)
    text_height = box[3] - box[1]
    y = {'top': max(2 * padding, height // 5), 'center': (height - text_height) // 2,
         'bottom': height - 2 * padding - text_height}[options['position']]
    draw.rounded_rectangle((padding, y - padding // 2, width - padding,
                            y + text_height + padding // 2), radius=24, fill=(14, 19, 33, 205))
    centered = options['alignment'] == 'center'
    x = (width - (box[2] - box[0])) // 2 if centered else 2 * padding
    draw.multiline_text((x, y - box[1]), text, font=font, spacing=12,
                        fill=options['text_color'], align='center' if centered else 'left')
    canvas.alpha_composite(overlay)
    output = io.BytesIO()
    canvas.convert('RGB').save(output, 'PNG')
    return output.getvalue()


def run_image_job(identifier, task_id):
    try:
        with SessionLocal() as db:
            row, task = db.get(ImageAd, identifier), db.get(Job, task_id)
            if not row or not task or task.resource_id != identifier:
                return
            lead = require_lead(db, row.lead_id)
            options = json.loads(row.options_json)
            refs = [media.content for media in selected_media(db, lead.id, options['media_ids'], ('image',))]
            logo = selected_media(db, lead.id, [options['logo_id']], ('image',))[0].content if options['logo_id'] else None
            if options['mode'] == 'ai':
                prompt = json.dumps({'entreprise': lead.name, 'activité': lead.business_type,
                                     'site': lead.website, 'identité': options['identity'],
                                     **{k: options[k] for k in ('objective', 'mood', 'colors', 'emphasize', 'avoid')}},
                                    ensure_ascii=False, sort_keys=True)
                prompt = ('Crée un fond publicitaire plein cadre en suivant ce brief. Laisse de l’espace pour '
                          'une surimpression. Aucun texte, logo, bordure ou filigrane.\n' + prompt)
                key = hashlib.sha256(json.dumps([prompt, options['format'], options['media_ids'],
                                                settings().openai_image_model]).encode()).hexdigest()
                if row.background_key != key or not row.background:
                    task.stage, task.total_found = 'Génération du fond OpenAI', 25
                    db.commit()
                    row.background = generate_background(prompt, options['format'], refs)
                    row.background_key = key
                background = row.background
            else:
                background = refs[0]
            task.stage, task.total_found = 'Composition du texte et du logo', 75
            db.commit()
            row.png = compose(background, logo, options)
            finish_task(task)
            db.commit()
    except Exception as error:
        logger.exception('Image Ads job failed: %s', identifier)
        with SessionLocal() as db:
            task = db.get(Job, task_id)
            if task and task.resource_id == identifier:
                message = error.detail if isinstance(error, HTTPException) else str(error) if isinstance(error, ValueError) else (
                    'La génération du visuel a échoué. Vérifiez la configuration OpenAI ou les fichiers et relancez.')
                finish_task(task, message)
                db.commit()


def recover_image_jobs():
    with SessionLocal() as db:
        for task in db.scalars(select(Job).where(Job.kind.in_(('image_render', 'image_copy')), Job.status.in_(ACTIVE))):
            finish_task(task, 'Traitement interrompu par le redémarrage. Relancez depuis Image Ads.')
        db.commit()


def owned_image(db, lead_id, identifier):
    require_lead(db, lead_id)
    row = db.get(ImageAd, identifier)
    if not row or row.lead_id != lead_id:
        raise HTTPException(404, 'Création introuvable.')
    return row


def image_payload(db, row):
    jobs = db.scalars(select(Job).where(Job.kind == 'image_render', Job.resource_id == row.id)
                      .order_by(Job.id.desc())).all()
    has_png = db.scalar(select(ImageAd.png.is_not(None)).where(ImageAd.id == row.id))
    return {'id': row.id, 'options': json.loads(row.options_json),
            'png': f'/api/leads/{row.lead_id}/image-ads/{row.id}/png' if has_png else None,
            'jobs': [job_payload(job) for job in jobs]}


@router.get('/image-ads')
def studio(request: Request, lead_id: int | None = None, project_id: str = '', db: Session = Depends(get_db)):
    if lead_id is not None:
        require_lead(db, lead_id)
    return templates.TemplateResponse(request, 'image_ads.html', {
        'leads': db.execute(select(Lead.id, Lead.name).order_by(Lead.name)).all(),
        'lead_id': lead_id, 'project_id': project_id, 'formats': FORMATS})


@router.get('/api/leads/{lead_id}/image-ads')
def list_images(lead_id: int, db: Session = Depends(get_db)):
    lead = require_lead(db, lead_id)
    rows = db.execute(select(ImageAd.id, ImageAd.created_at, ImageAd.png.is_not(None).label('has_png')).where(ImageAd.lead_id == lead_id)
                      .order_by(ImageAd.created_at.desc())).all()
    return {'name': lead.name, 'website': lead.website, 'identity': identity_for(db, lead),
            'projects': [{'id': row.id, 'created_at': row.created_at,
                          'png': f'/api/leads/{lead_id}/image-ads/{row.id}/png' if row.has_png else None}
                         for row in rows]}


@router.post('/api/leads/{lead_id}/image-ads/message')
def message(lead_id: int, composition: Composition, db: Session = Depends(get_db)):
    lead = require_lead(db, lead_id)
    selected_media(db, lead_id, composition.media_ids, ('image',), limit=4)
    if composition.logo_id:
        selected_media(db, lead_id, [composition.logo_id], ('image',))
    site = db.scalar(select(LeadWebsite).where(LeadWebsite.lead_id == lead_id))
    brief = composition.model_dump(include={'objective', 'mood', 'colors', 'emphasize', 'avoid'})
    facts = lead_facts(lead, site)
    task = start_task(db, 'image_copy', lead_id, stage='Rédaction du message OpenAI')
    db.commit()
    try:
        result = generate_copy(facts, 'bold', 8, json.dumps(brief, ensure_ascii=False))
    except (CopyUnavailable, httpx.HTTPError, ValueError) as error:
        detail = 'La génération du message a échoué. Vérifiez la configuration OpenAI.'
        finish_task(task, detail)
        db.commit()
        raise HTTPException(502, detail) from error
    except Exception:
        finish_task(task, 'La génération du message a échoué.')
        db.commit()
        raise
    finish_task(task)
    db.commit()
    return result


@router.get('/api/leads/{lead_id}/image-ads/{identifier}')
def get_image(lead_id: int, identifier: str, db: Session = Depends(get_db)):
    return image_payload(db, owned_image(db, lead_id, identifier))


@router.get('/api/leads/{lead_id}/image-ads/{identifier}/png')
def download(lead_id: int, identifier: str, download: bool = False, db: Session = Depends(get_db)):
    row = owned_image(db, lead_id, identifier)
    if not row.png:
        raise HTTPException(404, 'PNG indisponible.')
    headers = {'Cache-Control': 'no-store'}
    if download:
        headers['Content-Disposition'] = f'attachment; filename="image-ad-{identifier}.png"'
    return Response(row.png, media_type='image/png', headers=headers)


@router.post('/api/leads/{lead_id}/image-ads', status_code=202)
@router.post('/api/leads/{lead_id}/image-ads/{identifier}', status_code=202)
def enqueue(lead_id: int, composition: Composition, identifier: str | None = None, db: Session = Depends(get_db)):
    lead = require_lead(db, lead_id)
    if composition.mode not in ('photo', 'ai') or composition.format not in FORMATS or (
        composition.position not in ('top', 'center', 'bottom') or composition.fit not in ('contain', 'cover')
        or composition.alignment not in ('left', 'center') or not composition.message.strip()
        or len(composition.message.splitlines()) > 5
    ):
        raise HTTPException(400, 'Mode, format ou composition invalide. Utilisez cinq lignes de texte au maximum.')
    selected_media(db, lead_id, composition.media_ids, ('image',), limit=4)
    if composition.mode == 'photo' and len(composition.media_ids) != 1:
        raise HTTPException(400, 'Sélectionnez une photo pour le mode Photo réelle.')
    if composition.logo_id and composition.logo_id in composition.media_ids:
        raise HTTPException(400, 'Sélectionnez le logo uniquement dans le champ de surimpression.')
    previous = owned_image(db, lead_id, identifier) if identifier else None
    if composition.logo_id:
        logo, = selected_media(db, lead_id, [composition.logo_id], ('image',))
        if logo.category != 'logo' and not (previous and json.loads(previous.options_json).get('logo_id') == logo.id):
            raise HTTPException(400, 'Choisissez un média de la catégorie Logo.')
    options = composition.model_dump()
    options['identity'] = json.loads(previous.options_json)['identity'] if previous else identity_for(db, lead)
    with queue_lock:
        row = owned_image(db, lead_id, identifier) if identifier else ImageAd(
            id=uuid4().hex, lead_id=lead_id)
        if identifier:
            latest = db.scalar(select(Job).where(Job.resource_id == identifier, Job.kind == 'image_render')
                               .order_by(Job.id.desc()).limit(1))
            if latest and latest.status in ACTIVE:
                raise HTTPException(409, 'Un traitement est déjà en cours.')
            if latest and latest.status == 'completed' and json.loads(row.options_json) == options:
                return {'id': row.id, 'job_id': latest.id}
        row.options_json = json.dumps(options, ensure_ascii=False)
        db.add(row)
        task = start_task(db, 'image_render', lead_id, row.id, 'En attente de composition')
        task.status = 'queued'
        task.started_at = None
        db.commit()
        pool.submit(start_image_job, row.id, task.id)
        return {'id': row.id, 'job_id': task.id}


def start_image_job(identifier, task_id):
    with SessionLocal() as db:
        task = db.get(Job, task_id)
        if not task or task.resource_id != identifier or task.status != 'queued':
            return
        task.status, task.started_at = 'running', datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
    run_image_job(identifier, task_id)
