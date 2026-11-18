"""Image Ads studio, persistent compositions and recoverable job attempts."""
import base64
import hashlib
import io
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ad_copy import CopyUnavailable, generate_copy, lead_facts, stored_json
from .config import settings
from .db import SessionLocal, get_db
from .job_tracking import ACTIVE, finish_task, job_payload, start_task
from .media import image_from_bytes, require_lead, selected_media
from .models import ImageAd, ImageAdVersion, Job, Lead, LeadWebsite
from .site_style import website_art
from .website_identity import homepage_identity

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
logger = logging.getLogger(__name__)
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='image-ads')
queue_lock = Lock()
FORMATS = {'square': (1080, 1080), 'portrait': (1080, 1350),
           'story': (1080, 1920), 'landscape': (1920, 1080)}

IMAGE_STYLES = {
    'flyer': ('Flyer', 'Composition graphique dynamique avec des zones distinctes pour le titre, les informations et l’appel à l’action.'),
    'photo': ('Photo', 'Photographie publicitaire réaliste, lumière naturelle ou de studio, sujet principal net et arrière-plan discret.'),
    'poster': ('Affiche', 'Composition lisible à distance, silhouette dominante, contraste marqué et grand espace pour le titre.'),
    'ad': ('Annonce publicitaire', 'Création publicitaire centrée sur le produit ou le service, avec un point focal clair et une zone pour l’appel à l’action.'),
    'social': ('Visuel pour réseaux sociaux', 'Visuel lisible sur mobile, composition simple, sujet fort et éléments essentiels éloignés des bords.'),
}

VISUAL_STYLES = {
    'minimalist': ('Minimaliste', 'Palette réduite, lignes épurées et espaces négatifs généreux.'),
    'editorial': ('Éditorial premium', 'Composition éditoriale soignée, lumière douce et matières raffinées.'),
    'bold': ('Dynamique et coloré', 'Couleurs franches, contrastes expressifs et composition énergique.'),
    'natural': ('Naturel et chaleureux', 'Lumière diffuse, couleurs organiques et textures authentiques.'),
    'retro': ('Rétro', 'Palette vintage, grain subtil et formes graphiques inspirées de l’impression.'),
    'cinematic': ('Cinématographique', 'Éclairage directionnel, profondeur et étalonnage cinéma.'),
}

# Panel, text, accent and headline font. These palettes also affect the exported typography.
FLYER_PALETTES = {
    '': ('#101b2d', '#ffffff', '#93e2de', 'DejaVuSans-Bold.ttf'),
    'minimalist': ('#f8f8f5', '#161a20', '#355c66', 'DejaVuSans.ttf'),
    'editorial': ('#f1e9da', '#282118', '#7d4a27', 'DejaVuSerif.ttf'),
    'bold': ('#332072', '#ffffff', '#ffe660', 'DejaVuSans-Bold.ttf'),
    'natural': ('#f5eee1', '#23332a', '#366047', 'DejaVuSerif.ttf'),
    'retro': ('#f8e6bd', '#39251f', '#9d382a', 'DejaVuSerif-Bold.ttf'),
    'cinematic': ('#111217', '#fff6e8', '#f0c47a', 'DejaVuSans-Bold.ttf'),
}


class Composition(BaseModel):
    mode: str
    action: Literal['auto', 'local', 'ai', 'variant', 'full', 'full_variant'] = 'auto'
    use_previous_flyer: bool = False
    contact_icons: bool | None = None
    layout: Literal['commercial', 'editorial', 'promotion'] = 'commercial'
    format: str
    message: str = Field('', max_length=220)
    display_name: str | None = Field(None, max_length=255)
    activity: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=80)
    address: str | None = Field(None, max_length=300)
    website: str | None = Field(None, max_length=300)
    image_style: str = ''
    visual_style: str = ''
    objective: str = Field('', max_length=300)
    mood: str = Field('', max_length=300)
    colors: str = Field('', max_length=180)
    emphasize: str = Field('', max_length=300)
    avoid: str = Field('', max_length=300)
    operator_instruction: str = Field('', max_length=1500)
    media_ids: list[str] = Field(default_factory=list, max_length=4)
    logo_id: str | None = None
    position: str = 'auto'
    fit: str = 'contain'
    alignment: str = 'left'
    text_color: str = Field('#ffffff', pattern=r'^#[0-9a-fA-F]{6}$')


    @field_validator('image_style')
    @classmethod
    def validate_image_style(cls, value):
        if value and value not in IMAGE_STYLES:
            raise ValueError('Type d’image inconnu.')
        return value


    @field_validator('visual_style')
    @classmethod
    def validate_visual_style(cls, value):
        if value and value not in VISUAL_STYLES:
            raise ValueError('Style visuel inconnu.')
        return value


def identity_for(db, lead):
    row = db.scalar(select(LeadWebsite).where(LeadWebsite.lead_id == lead.id))
    if row:
        return {**website_art(stored_json(row.content_json, {})), 'source': 'site_ai'}
    return homepage_identity(lead.website)


def generate_background(prompt, format_name, refs, *, previous_background=None, previous_flyer=None,
                        complete_flyer=False, flyer_logo=None):
    cfg = settings()
    if not cfg.openai_api_key:
        raise ValueError('Configurez la clé OpenAI pour la création IA.')
    size = {'square': '1024x1024', 'portrait': '1024x1536', 'story': '1024x1536',
            'landscape': '1536x1024'}[format_name]
    headers = {'Authorization': 'Bearer ' + cfg.openai_api_key}
    options = {'model': cfg.openai_image_model, 'prompt': prompt, 'size': size,
               'quality': 'medium', 'output_format': 'png'}
    url = 'https://api.openai.com/v1/images/'
    files = [('image[]', ('reference.png', data, 'image/png')) for data in refs]
    if previous_background:
        files.insert(0, ('image[]', ('fond-precedent.png', previous_background, 'image/png')))
        options['prompt'] += (
            '\nLa première image est le fond de la version précédente. Utilise-le comme référence principale '
            'pour la retouche, conserve les éléments compatibles et applique les nouvelles consignes en priorité.'
        )
    if flyer_logo:
        files.append(('image[]', ('logo-fourni.png', flyer_logo, 'image/png')))
        options['prompt'] += '\nUtilise le logo fourni avec fidélité, sans le redessiner ni en inventer un autre.'
    if previous_flyer:
        files.append(('image[]', ('flyer-precedent.png', previous_flyer, 'image/png')))
        options['prompt'] += (
            '\nLa dernière image jointe est une ancienne version du flyer. '
            'Utilise-la comme référence de direction artistique. Les nouvelles consignes et les textes '
            'exacts du formulaire priment sur son contenu. Omet toute ancienne information absente du formulaire.'
            if complete_flyer else
            '\nLa dernière image jointe est la version précédente du flyer. '
            'Utilise son visuel comme point de départ, conserve les éléments graphiques compatibles '
            'et applique les nouvelles consignes en priorité. Ne reproduis aucun texte, numéro, '
            'adresse ni logo du flyer précédent. Le studio les compose séparément.'
        )
    if files:
        response = httpx.post(url + 'edits', data=options, headers=headers, timeout=180, files=files)
    else:
        response = httpx.post(url + 'generations', json=options, headers=headers, timeout=180)
    response.raise_for_status()
    raw = base64.b64decode(response.json()['data'][0]['b64_json'], validate=True)
    if len(raw) > 24 * 1024 * 1024:
        raise ValueError('Visuel OpenAI trop volumineux.')
    image_from_bytes(raw)
    return raw


def wrap_overlay_text(draw, text, font, max_width):
    lines = []
    for paragraph in text.splitlines():
        line = ''
        for word in paragraph.split():
            test = f'{line} {word}'.lstrip()
            if line and draw.textlength(test, font=font) > max_width:
                lines.append(line)
                line = ''
            for char in word:
                if draw.textlength(line + char, font=font) > max_width:
                    lines.append(line)
                    line = ''
                line += char
            line += ' '
        lines.append(line.strip())
    return '\n'.join(lines)


def fit_flyer_text(draw, text, font_file, size, width, height, spacing=6):
    while True:
        font = ImageFont.truetype(font_file, max(size, 12))
        wrapped = wrap_overlay_text(draw, text, font, width)
        bounds = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing)
        if bounds[3] - bounds[1] <= height or size <= 12:
            return wrapped, font, bounds
        size -= 2


def headline_position(options):
    position = options.get('position', 'auto')
    if position != 'auto':
        return position
    # Only interpret placement phrases explicitly attached to the headline.
    instruction = options.get('operator_instruction', '').lower()
    placements = {'en haut': 'top', 'en bas': 'bottom', 'au centre': 'center',
                  'à gauche': 'left', 'à droite': 'right'}
    match = re.search(r"(?:accroche|slogan|message publicitaire)\s*(?:[:=]|placé[e]?|doit être)*\s*"
                      r"(en haut|en bas|au centre|à gauche|à droite)\b", instruction)
    return placements[match[1]] if match else 'bottom'


def draw_contact_icon(draw, field, x, y, size, accent, panel):
    stroke = max(2, size // 10)
    if field == 'phone':
        draw.rounded_rectangle((x + size // 5, y, x + 4 * size // 5, y + size),
                               radius=size // 7, outline=accent, width=stroke)
        draw.line((x + 2 * size // 5, y + 4 * size // 5, x + 3 * size // 5, y + 4 * size // 5),
                  fill=accent, width=stroke)
    else:
        left, middle, right = x + size // 8, x + size // 2, x + 7 * size // 8
        draw.polygon(((left + stroke, y + size // 2), (right - stroke, y + size // 2), (middle, y + size)),
                     fill=accent)
        draw.ellipse((left, y, right, y + 3 * size // 4), fill=accent)
        hole = size // 8
        center_y = y + 3 * size // 8
        draw.ellipse((middle - hole, center_y - hole, middle + hole, center_y + hole), fill=panel)


def compose(background, logo, options):
    width, height = FORMATS[options['format']]
    unit = min(width, height)
    margin = round(unit * .067)
    panel, ink, accent, headline_font = FLYER_PALETTES[options.get('visual_style', '')]
    body_font = 'DejaVuSans.ttf'
    canvas = Image.new('RGBA', (width, height), panel)
    draw = ImageDraw.Draw(canvas)

    brand = image_from_bytes(logo) if logo else None
    if brand:
        brand.thumbnail((width // 6, unit // 11), Image.Resampling.LANCZOS)
    name_x = margin + (brand.width + margin // 3 if brand else 0)
    activity = options.get('business', {}).get('activity', '')
    name, font, bounds = fit_flyer_text(draw, options.get('display_name', ''), headline_font,
                                        round(unit * .061), width - margin - name_x, unit // 9)
    name_height = bounds[3] - bounds[1]
    activity_text, activity_font, activity_bounds = fit_flyer_text(
        draw, activity, body_font, round(unit * .027), width - margin - name_x, unit // 18)
    activity_height = activity_bounds[3] - activity_bounds[1]
    gap = margin // 6 if activity and name else 0
    header_content = max(brand.height if brand else 0, name_height + gap + activity_height)
    header_bottom = margin + header_content + margin // 2
    if brand:
        canvas.alpha_composite(brand, (margin, margin + (header_content - brand.height) // 2))
    if name:
        draw.multiline_text((name_x, margin - bounds[1]), name, font=font, fill=ink, spacing=6)
    if activity:
        draw.multiline_text((name_x, margin + name_height + gap - activity_bounds[1]),
                            activity_text, font=activity_font, fill=accent, spacing=6)

    business = options.get('business', {})
    contacts = [(field, business[field]) for field in ('phone', 'address', 'website') if business.get(field)]
    footer_top = height - margin // 2
    if contacts:
        icon_fields = ('phone', 'address') if options.get('contact_icons') else ()
        icon_size = round(unit * .025)
        icon_indent = icon_size + margin // 6
        line_gap = unit // 140
        rows = []
        for field, value in contacts:
            indent = icon_indent if field in icon_fields else 0
            text, font, bounds = fit_flyer_text(
                draw, value, body_font, round(unit * .027), width - 2 * margin - indent,
                max(20, (height // 5) // len(contacts)))
            rows.append((field, indent, text, font, bounds, max(icon_size, bounds[3] - bounds[1])))
        footer_height = sum(row[-1] for row in rows) + line_gap * (len(rows) - 1)
        footer_top = height - margin - footer_height - margin // 2
        y = footer_top + margin // 2
        for field, indent, text, font, bounds, row_height in rows:
            if indent:
                draw_contact_icon(draw, field, margin, y + (row_height - icon_size) // 2, icon_size, accent, panel)
            draw.multiline_text((margin + indent, y - bounds[1]), text, font=font, fill=ink, spacing=6)
            y += row_height + line_gap

    photo = image_from_bytes(background)
    layout = options.get('layout', 'commercial')
    image_margin = margin if layout == 'editorial' else 0
    promo_height = unit // 7 if layout == 'promotion' and options['message'].strip() else 0
    frame = (width - 2 * image_margin, footer_top - header_bottom - promo_height)
    artwork = (ImageOps.fit(photo, frame, Image.Resampling.LANCZOS) if options['fit'] == 'cover'
               else ImageOps.contain(photo, frame, Image.Resampling.LANCZOS))
    canvas.alpha_composite(artwork, ((width - artwork.width) // 2,
                                    header_bottom + (frame[1] - artwork.height) // 2))
    if promo_height:
        draw.rectangle((0, footer_top - promo_height, width, footer_top), fill=accent)
    draw.rectangle((margin, header_bottom - 4, margin + unit // 14, header_bottom - 1), fill=accent)

    if headline := options['message'].strip():
        position = 'bottom' if promo_height else headline_position(options)
        inset = margin // 3
        max_width = width // 2 - margin if position in ('left', 'right') else width - 2 * margin
        headline, font, bounds = fit_flyer_text(draw, headline, headline_font, round(unit * .041),
                                                 max_width - 2 * inset, max(18, promo_height // 2 if promo_height else frame[1] // 3))
        box_width = bounds[2] - bounds[0] + 2 * inset
        box_height = bounds[3] - bounds[1] + 2 * inset
        center = position == 'center' or options['alignment'] == 'center'
        x = width - margin - box_width if position == 'right' else margin
        if promo_height:
            x = (width - box_width) // 2
        if center and position not in ('left', 'right'):
            x = (width - box_width) // 2
        y = {'top': header_bottom + inset, 'bottom': footer_top - inset - box_height}.get(
            position, header_bottom + (frame[1] - box_height) // 2)
        if promo_height:
            y = footer_top - (promo_height + box_height) // 2
        draw.rounded_rectangle((x, y, x + box_width, y + box_height), radius=inset // 2, fill=panel)
        draw.multiline_text((x + inset - bounds[0], y + inset - bounds[1]), headline,
                            font=font, fill=ink, spacing=6, align='center' if center else 'left')

    output = io.BytesIO()
    canvas.convert('RGB').save(output, 'PNG')
    return output.getvalue()


def image_art_direction(options):
    direction = {}
    for field, choices in (('image_style', IMAGE_STYLES), ('visual_style', VISUAL_STYLES)):
        if style := options.get(field):
            label, description = choices[style]
            direction[field] = {'type': label, 'direction': description}
    return direction


def compose_full_flyer(options, refs, logo, previous_flyer):
    width, height = FORMATS[options['format']]
    brief = {
        'format final': f'{width} × {height}',
        'mise en page': options['layout'],
        'position demandée par le formulaire': options['position'],
        'identité visuelle du prospect': options['identity'],
        'direction artistique': image_art_direction(options),
        'brief client': {field: options[field] for field in ('objective', 'mood', 'colors', 'emphasize', 'avoid')},
        'instruction opérateur': options.get('operator_instruction', ''),
        'textes exacts à imprimer': {
            'nom': options['display_name'], 'accroche': options['message'].strip(),
            **options['business'],
        },
    }
    if options.get('contact_icons'):
        brief['pictogrammes de contact'] = {
            'à placer juste à côté du champ correspondant': [
                label for field, label in (('phone', 'téléphone'), ('address', 'localisation'))
                if options['business'].get(field)
            ],
            'aucun pictogramme pour un champ vide': True,
        }
    prompt = (
        'Tu es un designer graphique senior. Crée le flyer publicitaire COMPLET et final, '
        'prêt à être diffusé. Compose le visuel, le logo fourni et les textes ensemble. '
        'Applique l’instruction opérateur à toute la composition, y compris la position, '
        'la typographie et les relations entre éléments. Les exemples de mise en page du formulaire '
        'sont des indications de départ. Lorsqu’une consigne vise une donnée précise, '
        'place l’élément demandé au contact de cette donnée dans le même groupe visuel. '
        'Recopie exactement les textes fournis. Omet les champs vides et n’invente aucune '
        'coordonnée ni affirmation commerciale. Utilise des marges généreuses pour garder tous '
        'les éléments à l’intérieur de l’image. Ne produis ni mockup ni texte explicatif.\n'
        + json.dumps(brief, ensure_ascii=False)
    )
    result = generate_background(prompt, options['format'], refs, previous_flyer=previous_flyer,
                                 complete_flyer=True, flyer_logo=logo)
    image = image_from_bytes(result).convert('RGB')
    edge_color = image.getpixel((0, 0))
    export = ImageOps.pad(image, (width, height), method=Image.Resampling.LANCZOS, color=edge_color)
    output = io.BytesIO()
    export.save(output, 'PNG')
    return output.getvalue()


def run_image_job(identifier, task_id):
    try:
        with SessionLocal() as db:
            row, task = db.get(ImageAd, identifier), db.get(Job, task_id)
            if not row or not task or task.resource_id != identifier:
                return
            lead = require_lead(db, row.lead_id)
            options = json.loads(row.options_json)
            operation = json.loads(task.types)
            if not isinstance(operation, dict):
                operation = {}
            action = operation.get('action', 'auto')
            refs = [media.content for media in selected_media(db, lead.id, options['media_ids'], ('image',))]
            logo = selected_media(db, lead.id, [options['logo_id']], ('image',))[0].content if options['logo_id'] else None
            source = row
            if operation.get('source_version'):
                source = owned_version(db, owned_image(db, lead.id, operation['source']),
                                       operation['source_version'])
            previous_flyer = source.png if operation.get('use_previous_flyer') else None
            if action in ('full', 'full_variant'):
                task.stage, task.total_found = 'Création IA du flyer complet', 25
                db.commit()
                row.png = compose_full_flyer(options, refs, logo, previous_flyer)
                row.background = None
                row.background_key = None
            else:
                if options['mode'] == 'ai':
                    brief = {'entreprise': lead.name, 'activité': lead.business_type,
                             'site': lead.website, 'identité': options['identity'],
                             **{key: options[key] for key in ('objective', 'mood', 'colors', 'emphasize', 'avoid')}}
                    if style := options.get('image_style'):
                        label, direction = IMAGE_STYLES[style]
                        brief['type d’image'] = label
                        brief['direction visuelle du type'] = direction
                    if style := options.get('visual_style'):
                        label, direction = VISUAL_STYLES[style]
                        brief['style visuel'] = label
                        brief['direction artistique du style'] = direction
                    if instruction := options.get('operator_instruction'):
                        brief['instruction opérateur pour le fond'] = instruction
                    prompt = json.dumps(brief, ensure_ascii=False, sort_keys=True)
                    prompt = ('Agis comme un directeur artistique et designer graphique senior. Crée le visuel '
                              'principal d’un support publicitaire professionnel en suivant le brief. '
                              'Compose une image équilibrée avec un sujet identifiable, des marges de sécurité '
                              'et des zones calmes qui permettent d’ajouter une accroche. Respecte les références '
                              'et évite les détails parasites. Le studio ajoute séparément le nom, le métier, '
                              'les coordonnées et le logo. Aucun texte, logo, cadre, filigrane ni pictogramme de coordonnées dans le visuel.\n' + prompt)
                    key = hashlib.sha256(json.dumps([prompt, options['format'], options['media_ids'],
                                                    settings().openai_image_model]).encode()).hexdigest()
                    if action != 'local' and (action in ('ai', 'variant') or row.background_key != key or not row.background):
                        task.stage, task.total_found = 'Génération du fond OpenAI', 25
                        db.commit()
                        row.background = generate_background(
                            prompt, options['format'], refs,
                            previous_background=source.background, previous_flyer=previous_flyer)
                        row.background_key = key
                    background = row.background
                else:
                    background = refs[0]
                task.stage, task.total_found = 'Composition du flyer et des coordonnées', 75
                db.commit()
                row.png = compose(background, logo, options)
                if options['mode'] == 'photo':
                    row.background = None
                    row.background_key = None
            snapshot_version(db, row)
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


def snapshot_version(db, row):
    version = ImageAdVersion(project_id=row.id, options_json=row.options_json,
                             background_key=row.background_key, background=row.background, png=row.png)
    db.add(version)
    return version


def owned_version(db, row, version_id):
    version = db.get(ImageAdVersion, version_id)
    if not version or version.project_id != row.id:
        raise HTTPException(404, 'Version introuvable.')
    return version


def active_render(db, row):
    return db.scalar(select(Job.id).where(
        Job.resource_id == row.id, Job.kind == 'image_render', Job.status.in_(ACTIVE)).limit(1))


def image_payload(db, row):
    jobs = db.scalars(select(Job).where(Job.kind == 'image_render', Job.resource_id == row.id)
                      .order_by(Job.id.desc())).all()
    has_png = db.scalar(select(ImageAd.png.is_not(None)).where(ImageAd.id == row.id))
    versions = db.execute(select(ImageAdVersion.id, ImageAdVersion.created_at).where(
        ImageAdVersion.project_id == row.id).order_by(ImageAdVersion.id.desc())).all()
    return {'id': row.id, 'options': json.loads(row.options_json),
            'png': f'/api/leads/{row.lead_id}/image-ads/{row.id}/png' if has_png else None,
            'has_background': db.scalar(select(ImageAd.background.is_not(None)).where(ImageAd.id == row.id)),
            'versions': [{'id': version.id, 'created_at': version.created_at,
                          'png': f'/api/leads/{row.lead_id}/image-ads/{row.id}/versions/{version.id}/png'}
                         for version in versions],
            'jobs': [job_payload(job) for job in jobs]}


def flyer_business(lead):
    # Use the same business labels as the prospect pages without importing the application.
    label = templates.env.globals.get('type_label')
    activity = label(lead.business_type) if label else (lead.business_type or '').replace('_', ' ').capitalize()
    return {'activity': activity, 'phone': lead.phone or '', 'address': lead.address or lead.city or '',
            'website': re.sub(r'^https?://', '', lead.website or '', flags=re.IGNORECASE).rstrip('/')}


@router.get('/image-ads')
def studio(request: Request, lead_id: int | None = None, project_id: str = '', db: Session = Depends(get_db)):
    if lead_id is not None:
        require_lead(db, lead_id)
    return templates.TemplateResponse(request, 'image_ads.html', {
        'leads': db.execute(select(Lead.id, Lead.name).order_by(Lead.name)).all(),
        'lead_id': lead_id, 'project_id': project_id, 'formats': FORMATS, 'image_styles': IMAGE_STYLES, 'visual_styles': VISUAL_STYLES})


@router.get('/api/leads/{lead_id}/image-ads')
def list_images(lead_id: int, db: Session = Depends(get_db)):
    lead = require_lead(db, lead_id)
    rows = db.execute(select(ImageAd.id, ImageAd.created_at, ImageAd.png.is_not(None).label('has_png')).where(ImageAd.lead_id == lead_id)
                      .order_by(ImageAd.created_at.desc())).all()
    return {'name': lead.name, 'website': lead.website, 'business': flyer_business(lead), 'identity': identity_for(db, lead),
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
        result = generate_copy(facts, 'bold', 8, json.dumps(brief, ensure_ascii=False), headline=True)
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


@router.get('/api/leads/{lead_id}/image-ads/{identifier}/versions/{version_id}/png')
def version_png(lead_id: int, identifier: str, version_id: int, download: bool = False,
                db: Session = Depends(get_db)):
    version = owned_version(db, owned_image(db, lead_id, identifier), version_id)
    headers = {'Cache-Control': 'no-store'}
    if download:
        headers['Content-Disposition'] = f'attachment; filename="image-ad-{identifier}-v{version.id}.png"'
    return Response(version.png, media_type='image/png', headers=headers)


@router.post('/api/leads/{lead_id}/image-ads/{identifier}/versions/{version_id}/restore')
def restore_version(lead_id: int, identifier: str, version_id: int, db: Session = Depends(get_db)):
    with queue_lock:
        row = owned_image(db, lead_id, identifier)
        version = owned_version(db, row, version_id)
        if active_render(db, row):
            raise HTTPException(409, 'Un traitement est déjà en cours.')
        row.options_json = version.options_json
        row.background = version.background
        row.background_key = version.background_key
        row.png = version.png
        snapshot_version(db, row)
        task = start_task(db, 'image_render', lead_id, row.id, 'Restauration d’une version')
        finish_task(task)
        db.commit()
        return {'id': row.id}


def prepare_composition(db, lead_id, composition, identifier):
    lead = require_lead(db, lead_id)
    if composition.mode not in ('photo', 'ai') or composition.format not in FORMATS or (
        composition.position not in ('auto', 'top', 'center', 'bottom', 'left', 'right') or composition.fit not in ('contain', 'cover')
        or composition.alignment not in ('left', 'center')
        or len(composition.message.splitlines()) > 5
    ):
        raise HTTPException(400, 'Mode, format ou composition invalide. Utilisez cinq lignes de texte au maximum.')
    selected_media(db, lead_id, composition.media_ids, ('image',), limit=4)
    if composition.action in ('full', 'full_variant') and composition.mode != 'ai':
        raise HTTPException(400, 'Le flyer complet nécessite le mode Création IA.')
    if composition.mode == 'photo' and len(composition.media_ids) != 1:
        raise HTTPException(400, 'Sélectionnez une photo pour le mode Photo réelle.')
    if composition.logo_id and composition.logo_id in composition.media_ids:
        raise HTTPException(400, 'Sélectionnez le logo uniquement dans le champ de surimpression.')
    previous = owned_image(db, lead_id, identifier) if identifier else None
    if composition.logo_id:
        logo, = selected_media(db, lead_id, [composition.logo_id], ('image',))
        if logo.category != 'logo' and not (previous and json.loads(previous.options_json).get('logo_id') == logo.id):
            raise HTTPException(400, 'Choisissez un média de la catégorie Logo.')
    saved_options = json.loads(previous.options_json) if previous else {}
    business = {**flyer_business(lead), **saved_options.get('business', {})}
    options = composition.model_dump(exclude={'operator_instruction', 'image_style', 'visual_style', 'action', 'use_previous_flyer', 'contact_icons', *business})
    name = composition.display_name
    options['display_name'] = saved_options.get('display_name', lead.name) if name is None else ' '.join(name.split())
    for field in business:
        value = getattr(composition, field)
        if value is not None:
            business[field] = ' '.join(value.split())
    options['business'] = business
    if composition.mode == 'ai':
        options['image_style'] = composition.image_style or 'flyer'
    if composition.action in ('full', 'full_variant'):
        options['render_kind'] = 'full'
    icons = composition.contact_icons
    if icons is None:
        icons = saved_options.get('contact_icons', False) if previous else True
    if icons:
        options['contact_icons'] = True
    if composition.visual_style:
        options['visual_style'] = composition.visual_style
    if instruction := composition.operator_instruction.strip():
        options['operator_instruction'] = instruction
    options['identity'] = saved_options.get('identity', {})
    if not previous and composition.action != 'local':
        options['identity'] = identity_for(db, lead)
    for field in ('position', 'alignment', 'fit', 'text_color'):
        if field not in composition.model_fields_set and field in saved_options:
            options[field] = saved_options[field]
    return options


@router.post('/api/leads/{lead_id}/image-ads/preview')
@router.post('/api/leads/{lead_id}/image-ads/{identifier}/preview')
def preview(lead_id: int, composition: Composition, identifier: str | None = None, db: Session = Depends(get_db)):
    options = prepare_composition(db, lead_id, composition.model_copy(update={'action': 'local'}), identifier)
    if composition.mode == 'photo':
        background = selected_media(db, lead_id, options['media_ids'], ('image',))[0].content
    else:
        background = owned_image(db, lead_id, identifier).background if identifier else None
        if not background:
            raise HTTPException(409, 'Générez un visuel pour afficher son aperçu.')
    logo = selected_media(db, lead_id, [options['logo_id']], ('image',))[0].content if options['logo_id'] else None
    return Response(compose(background, logo, options), media_type='image/png', headers={'Cache-Control': 'no-store'})


@router.post('/api/leads/{lead_id}/image-ads', status_code=202)
@router.post('/api/leads/{lead_id}/image-ads/{identifier}', status_code=202)
def enqueue(lead_id: int, composition: Composition, identifier: str | None = None, db: Session = Depends(get_db)):
    with queue_lock:
        options = prepare_composition(db, lead_id, composition, identifier)
        source = owned_image(db, lead_id, identifier) if identifier else None
        if source and active_render(db, source):
            raise HTTPException(409, 'Un traitement est déjà en cours.')
        if composition.action == 'local' and composition.mode == 'ai' and not (source and source.background):
            raise HTTPException(409, 'Générez un visuel avant de retoucher le flyer.')
        row = source if source and composition.action not in ('variant', 'full_variant') else ImageAd(id=uuid4().hex, lead_id=lead_id)
        if row is source:
            latest = db.scalar(select(Job).where(Job.resource_id == identifier, Job.kind == 'image_render')
                               .order_by(Job.id.desc()).limit(1))
            if latest and latest.status == 'completed' and json.loads(row.options_json) == options and composition.action in ('auto', 'local'):
                return {'id': row.id, 'job_id': latest.id}
        source_version = None
        if source:
            source_version = db.scalar(select(ImageAdVersion.id).where(
                ImageAdVersion.project_id == source.id).order_by(ImageAdVersion.id.desc()).limit(1))
            if source.png and source_version is None:
                version = snapshot_version(db, source)
                db.flush()
                source_version = version.id
        row.options_json = json.dumps(options, ensure_ascii=False)
        db.add(row)
        task = start_task(db, 'image_render', lead_id, row.id, 'En attente de composition')
        task.types = json.dumps({'action': composition.action,
                                 'source': source.id if source and row is not source else None,
                                 'source_version': source_version if row is not source else None,
                                 'use_previous_flyer': composition.use_previous_flyer})
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
