"""Persistent lead audio and editable slideshow video jobs."""
import json
import logging
from pathlib import Path
import shutil
import subprocess
import threading
from functools import lru_cache
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

router = APIRouter()
logger = logging.getLogger('profilefinder.video_ads')
tpl = Jinja2Templates(directory=str(ROOT / 'app/templates'))
pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='video-ads')
slot = threading.BoundedSemaphore(1)


@lru_cache
def video_tools_ready():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        return False
    try:
        from playwright.sync_api import sync_playwright
        if shutil.which('chromium') or shutil.which('chromium-browser'):
            return True
        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()
    except Exception:
        return False


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
def studio(request: Request, db: Session = Depends(get_db)):
    leads = db.scalars(select(Lead).order_by(Lead.name)).all()
    return tpl.TemplateResponse(request, 'video_ads.html', {'leads': leads})


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
            'ready': video_tools_ready()}


def project_payload(row):
    return {'id': row.id, 'lead_id': row.lead_id, 'audio_id': row.audio_id, 'format': row.format, 'status': row.status,
            'progress': row.progress, 'error': row.error, 'slides': json.loads(row.slides_json),
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
            capture_pages(directory, site, lead_data, lambda n: update(identifier, progress=n), format_name)
            update(identifier, status='ready', progress=100)
        else:
            compose_slides(directory, slides, lead_data, format_name)
            encode_video(directory, audio_path, slides, duration, lambda n: update(identifier, progress=n))
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
    if not video_tools_ready():
        raise HTTPException(503, 'Installez Playwright, Chromium, FFmpeg et ffprobe pour préparer une vidéo.')
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
        row.status, row.progress, row.error = 'rendering', 0, None
        db.commit()
        pool.submit(run_job, row.id, 'render')
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
