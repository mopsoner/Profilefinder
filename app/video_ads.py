"""Persistent lead audio and editable slideshow video jobs."""
import json
import logging
from pathlib import Path
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .db import SessionLocal, get_db
from .models import Lead, LeadWebsite, AudioAd, VideoAd
from .video_render import MEDIA, ROOT, FORMATS, audio_duration, site_pages, split_script, validate_slides, capture_pages, compose_slides, encode_video
from ads.server import decode_audio
import httpx
from .ad_copy import TONES, lead_facts, generate_copy, CopyUnavailable
from .video_direction import LAYOUT_NAMES, scene_layout

router = APIRouter()
logger = logging.getLogger('profilefinder.video_ads')
tpl = Jinja2Templates(directory=str(ROOT / 'app/templates'))
pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='video-ads')
slot = threading.BoundedSemaphore(1)


def video_dependencies():
    tools = {'FFmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe')),
             'Playwright': False, 'Chromium': bool(shutil.which('chromium') or shutil.which('chromium-browser'))}
    try:
        from playwright.sync_api import sync_playwright
        tools['Playwright'] = True
        if not tools['Chromium']:
            with sync_playwright() as playwright:
                tools['Chromium'] = Path(playwright.chromium.executable_path).is_file()
    except Exception:
        pass
    return {'missing': [name for name, present in tools.items() if not present]}


def video_tools_ready():
    return not video_dependencies()['missing']


async def read_json(request, maximum=29 * 1024 * 1024):
    origin = request.headers.get('origin')
    if origin and origin != f'{request.url.scheme}://{request.headers.get("host", "")}':
        raise HTTPException(403, 'Origine non autorisée.')
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'Une requête JSON est requise.')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise HTTPException(413, 'Requête trop volumineuse.')
    try:
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, 'Objet JSON invalide.')


def audio_payload(row):
    return {'id': row.id, 'lead_id': row.lead_id, 'script': row.script, 'duration': row.duration,
            'created_at': row.created_at.isoformat(), 'url': f'/api/ads/audio/{row.id}'}


@router.get('/api/ads/leads')
def lead_options(db: Session = Depends(get_db)):
    return [{'id': lead.id, 'name': lead.name, 'activity': lead.business_type or '', 'city': lead.city or '', 'address': lead.address or ''} for lead in db.scalars(select(Lead).order_by(Lead.name)).all()]


@router.post('/api/ads/message')
async def prepare_message(request: Request, db: Session = Depends(get_db)):
    data = await read_json(request, 15000)
    tone, duration, details = data.get('tone','warm'), data.get('duration',30), data.get('details','')
    if not isinstance(tone,str) or tone not in TONES or type(duration) is not int or duration not in (15,30,45):
        raise HTTPException(400, 'Ambiance ou durée invalide.')
    if not isinstance(details,str) or len(details)>2000:
        raise HTTPException(400, 'Complément limité à 2 000 caractères.')
    lead_id = data.get('lead_id')
    if lead_id is not None:
        if type(lead_id) is not int:
            raise HTTPException(400, 'Identifiant de prospect invalide.')
        lead = db.get(Lead, lead_id)
        if not lead:
            raise HTTPException(404, 'Prospect introuvable.')
        website = db.scalar(select(LeadWebsite).where(LeadWebsite.lead_id==lead_id))
        facts = lead_facts(lead, website)
    else:
        profile = data.get('profile')
        if not isinstance(profile,dict) or not all(isinstance(profile.get(key),str) and 1<=len(profile[key].strip())<=180 for key in ('name','activity')):
            raise HTTPException(400, 'Sélectionnez un prospect ou renseignez son nom et son activité.')
        city = profile.get('city','')
        if not isinstance(city,str) or len(city)>100:
            raise HTTPException(400, 'Ville invalide.')
        facts = {'profil':{'nom':profile['name'],'activite':profile['activity'],'ville':city}}
    try:
        result = await run_in_threadpool(generate_copy, facts, tone, duration, details)
        return {**result, 'lead_id':lead_id}
    except CopyUnavailable as error:
        raise HTTPException(503, str(error))
    except ValueError as error:
        raise HTTPException(400, str(error))
    except httpx.HTTPStatusError as error:
        raise HTTPException(502, f'OpenAI a refusé la génération (HTTP {error.response.status_code}). Vérifiez la clé, le modèle et vos crédits.')
    except httpx.RequestError:
        raise HTTPException(502, 'OpenAI est injoignable. Réessayez dans quelques instants.')


@router.post('/api/ads/audio')
async def save_audio(request: Request, db: Session = Depends(get_db)):
    data = await read_json(request)
    lead_id = data.get('lead_id')
    if type(lead_id) is not int or not db.get(Lead, lead_id):
        raise HTTPException(404, 'Prospect introuvable.')
    script = data.get('script')
    if not isinstance(script, str) or not 1 <= len(script.strip()) <= 4096:
        raise HTTPException(400, 'Associez le texte de la voix off à cet audio (4 096 caractères max.).')
    try:
        raw = decode_audio(data.get('audio'))
    except ValueError as error:
        raise HTTPException(400, str(error))
    identifier = uuid4().hex
    folder = MEDIA / 'audio'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{identifier}.mp3'
    path.write_bytes(raw)
    try:
        duration = await run_in_threadpool(audio_duration, path)
        row = AudioAd(id=identifier, lead_id=lead_id, script=script.strip(), duration=duration)
        db.add(row)
        db.commit()
    except (ValueError, subprocess.SubprocessError, KeyError, FileNotFoundError):
        path.unlink(missing_ok=True)
        raise HTTPException(400, 'Audio illisible ou durée hors limites (1 à 300 secondes). FFmpeg est requis.')
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return audio_payload(row)


@router.get('/api/ads/audio/{identifier}')
def saved_audio(identifier: str, db: Session = Depends(get_db)):
    row = db.get(AudioAd, identifier)
    if not row:
        raise HTTPException(404, 'Audio introuvable.')
    path = MEDIA / 'audio' / f'{row.id}.mp3'
    if not path.is_file():
        raise HTTPException(404, 'Le fichier audio n’est plus disponible.')
    # ffprobe checks the actual media; imported WAV/OGG can also be stored here.
    return FileResponse(path, media_type='application/octet-stream')


@router.get('/video-ads')
@router.get('/leads/{lead_id}/video-ads')
def studio(request: Request, lead_id: int | None = None, db: Session = Depends(get_db)):
    selected_lead = db.get(Lead, lead_id) if lead_id is not None else None
    if lead_id is not None and not selected_lead:
        raise HTTPException(404, 'Prospect introuvable.')
    leads = [selected_lead] if 'lead_id' in request.path_params else db.scalars(select(Lead).order_by(Lead.name)).all()
    return tpl.TemplateResponse(request, 'video_ads.html', {'leads': leads, 'selected_lead': selected_lead})


@router.get('/api/video-ads/leads/{lead_id}')
def lead_context(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Prospect introuvable.')
    site = db.scalar(select(LeadWebsite).where(LeadWebsite.lead_id == lead_id))
    try:
        site_data = json.loads(site.content_json) if site else None
        if site_data is not None and not isinstance(site_data, dict):
            site_data = None
    except (TypeError, ValueError):
        site_data = None
    audios = db.scalars(select(AudioAd).where(AudioAd.lead_id == lead_id).order_by(AudioAd.created_at.desc())).all()
    projects = db.scalars(select(VideoAd).where(VideoAd.lead_id == lead_id).order_by(VideoAd.created_at.desc()).limit(12)).all()
    return {'lead': {'id': lead.id, 'name': lead.name}, 'has_site': site_data is not None,
            'pages': [{'title': p.get('nav_label') or p.get('title') or 'Page'} for p in site_pages(site_data, lead.name)] if site_data else [],
            'audios': [audio_payload(row) for row in audios], 'projects': [project_payload(row) for row in projects],
            'ready': video_tools_ready(), 'missing_tools': video_dependencies()['missing']}


def project_payload(row):
    slides=json.loads(row.slides_json)
    for index,slide in enumerate(slides):
        if slide.get('layout') not in LAYOUT_NAMES:
            slide['layout']=scene_layout(index,len(slides))
        preview=MEDIA/'video'/row.id/f'slide-{index}.png'
        slide['preview_url']=f'/api/video-ads/{row.id}/scenes/{index}?v={preview.stat().st_mtime_ns}' if preview.is_file() else None
    return {'id': row.id, 'lead_id': row.lead_id, 'audio_id': row.audio_id, 'format': row.format, 'status': row.status,
            'progress': row.progress, 'error': row.error, 'slides': slides, 'layouts':LAYOUT_NAMES,
            'created_at': row.created_at.isoformat(), 'video_url': f'/api/video-ads/{row.id}/video' if row.status == 'completed' else None,
            'pages': [{'title': p.get('nav_label') or p.get('title') or 'Page', 'url': f'/api/video-ads/{row.id}/pages/{i}'} for i, p in enumerate(site_pages(json.loads(row.site_json), 'Site'))]}


def update(identifier, **fields):
    with SessionLocal() as db:
        row = db.get(VideoAd, identifier)
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


def run_job(identifier, mode):
    try:
        with SessionLocal() as db:
            row = db.get(VideoAd, identifier)
            lead = db.get(Lead, row.lead_id)
            audio = db.get(AudioAd, row.audio_id)
            if not lead or not audio:
                raise ValueError('Le prospect ou l’audio a été supprimé.')
            lead_data = {'id': lead.id, 'name': lead.name, 'city': lead.city or '', 'phone': lead.phone or ''}
            directory = MEDIA / 'video' / row.id
            site, slides, format_name = json.loads(row.site_json), json.loads(row.slides_json), row.format
            audio_path, duration = MEDIA / 'audio' / f'{audio.id}.mp3', audio.duration
        # Release the database connection before expensive browser and encoder work.
        directory.mkdir(parents=True, exist_ok=True)
        if mode == 'prepare':
            capture_pages(directory, site, lead_data, lambda n: update(identifier, progress=round(n*.45)), format_name)
            compose_slides(directory, slides, lead_data, format_name, site, lambda n: update(identifier,progress=45+round(n*.55)))
            update(identifier, status='ready', progress=100)
        elif mode=='preview':
            compose_slides(directory, slides, lead_data, format_name, site, lambda n: update(identifier,progress=n))
            update(identifier,status='ready',progress=100)
        else:
            compose_slides(directory, slides, lead_data, format_name, site, lambda n: update(identifier, progress=round(n*.2)))
            encode_video(directory, audio_path, slides, duration, lambda n: update(identifier, progress=20+round(n*.8)))
            update(identifier, status='completed', progress=100)
    except Exception as error:
        logger.exception('Video Ads job failed: %s', identifier)
        message = str(error) if isinstance(error, ValueError) else 'Le rendu a échoué. Vérifiez Chromium/Playwright, FFmpeg et les médias locaux, puis réessayez.'
        update(identifier, status='failed', error=message)
    finally:
        slot.release()


@router.post('/api/video-ads/prepare')
async def prepare(request: Request, db: Session = Depends(get_db)):
    data = await read_json(request, 100000)
    if not await run_in_threadpool(video_tools_ready):
        missing = (await run_in_threadpool(video_dependencies))['missing']
        raise HTTPException(503, 'Outils vidéo manquants sur le serveur : '+', '.join(missing)+'. Exécutez scripts/install.sh puis redémarrez ProfileFinder.')
    lead_id, audio_id, format_name = data.get('lead_id'), data.get('audio_id'), data.get('format', 'portrait')
    if type(lead_id) is not int or not isinstance(audio_id, str) or not isinstance(format_name, str) or format_name not in FORMATS:
        raise HTTPException(400, 'Prospect, audio ou format invalide.')
    lead = db.get(Lead, lead_id)
    audio = db.get(AudioAd, audio_id)
    website = db.scalar(select(LeadWebsite).where(LeadWebsite.lead_id == lead_id))
    if not lead or not audio or audio.lead_id != lead_id:
        raise HTTPException(400, 'Sélectionnez un audio appartenant à ce prospect.')
    if not website:
        raise HTTPException(400, 'Générez d’abord le site du prospect dans Sites IA.')
    if not (MEDIA / 'audio' / f'{audio.id}.mp3').is_file():
        raise HTTPException(400, 'Fichier audio indisponible. Importez-le à nouveau.')
    try:
        site = json.loads(website.content_json)
        if not isinstance(site, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, 'Le contenu du site est invalide. Régénérez-le dans Sites IA.')
    pages = site_pages(site, lead.name)
    slides = split_script(audio.script, pages, audio.duration)
    if not slot.acquire(blocking=False):
        raise HTTPException(409, 'Un rendu est déjà en cours. Réessayez après sa fin.')
    try:
        row = VideoAd(id=uuid4().hex, lead_id=lead_id, audio_id=audio_id, format=format_name, site_json=json.dumps(site), slides_json=json.dumps(slides), status='preparing')
        db.add(row)
        db.commit()
        pool.submit(run_job, row.id, 'prepare')
    except Exception:
        slot.release()
        raise
    return project_payload(row)


@router.get('/api/video-ads/{identifier}')
def project(identifier: str, db: Session = Depends(get_db)):
    row = db.get(VideoAd, identifier)
    if not row:
        raise HTTPException(404, 'Projet introuvable.')
    return project_payload(row)


@router.post('/api/video-ads/{identifier}/render')
async def render(identifier: str, request: Request, db: Session = Depends(get_db)):
    data = await read_json(request, 100000)
    row = db.get(VideoAd, identifier)
    if not row:
        raise HTTPException(404, 'Projet introuvable.')
    if row.status not in ('ready', 'completed', 'failed'):
        raise HTTPException(409, 'Attendez la fin du traitement en cours.')
    audio = db.get(AudioAd, row.audio_id)
    if not audio:
        raise HTTPException(400, 'Audio supprimé.')
    try:
        slides = validate_slides(data.get('slides'), len(site_pages(json.loads(row.site_json), 'Site')), audio.duration)
    except ValueError as error:
        raise HTTPException(400, str(error))
    if not all((MEDIA / 'video' / row.id / f'page-{slide["page_index"]}.png').is_file() for slide in slides):
        raise HTTPException(400, 'Captures indisponibles. Préparez un nouveau projet.')
    if not slot.acquire(blocking=False):
        raise HTTPException(409, 'Un rendu est déjà en cours. Réessayez après sa fin.')
    try:
        row.slides_json = json.dumps(slides)
        preview_only=data.get('preview_only') is True
        row.status, row.progress, row.error = 'preparing' if preview_only else 'rendering', 0, None
        db.commit()
        pool.submit(run_job, row.id, 'preview' if preview_only else 'render')
    except Exception:
        slot.release()
        raise
    return project_payload(row)


@router.get('/api/video-ads/{identifier}/pages/{index}')
def page_capture(identifier: str, index: int, db: Session = Depends(get_db)):
    row = db.get(VideoAd, identifier)
    if not row or not 0 <= index < len(site_pages(json.loads(row.site_json), 'Site')):
        raise HTTPException(404, 'Capture introuvable.')
    path = MEDIA / 'video' / row.id / f'page-{index}.png'
    if not path.is_file():
        raise HTTPException(404, 'Capture en préparation ou indisponible.')
    return FileResponse(path, media_type='image/png')


@router.get('/api/video-ads/{identifier}/scenes/{index}')
def scene_preview(identifier: str, index: int, db: Session = Depends(get_db)):
    row=db.get(VideoAd,identifier)
    if not row or not 0<=index<len(json.loads(row.slides_json)):
        raise HTTPException(404,'Scène introuvable.')
    path=MEDIA/'video'/row.id/f'slide-{index}.png'
    if not path.is_file():
        raise HTTPException(404,'Scène en préparation ou indisponible.')
    return FileResponse(path,media_type='image/png',headers={'Cache-Control':'no-store'})


@router.get('/api/video-ads/{identifier}/video')
def download(identifier: str, db: Session = Depends(get_db)):
    row = db.get(VideoAd, identifier)
    if not row or row.status != 'completed':
        raise HTTPException(404, 'Vidéo pas encore disponible.')
    path = MEDIA / 'video' / row.id / 'spot.mp4'
    if not path.is_file():
        raise HTTPException(404, 'Fichier vidéo indisponible.')
    return FileResponse(path, media_type='video/mp4', filename=f'video-ads-{row.lead_id}-{row.id[:8]}.mp4', content_disposition_type='inline')


def recover_interrupted_jobs():
    with SessionLocal() as db:
        for row in db.scalars(select(VideoAd).where(VideoAd.status.in_(['preparing', 'rendering']))).all():
            row.status = 'failed'
            row.error = 'Le serveur a redémarré pendant le traitement. Préparez à nouveau les captures ou relancez le rendu.'
        db.commit()
