"""Validated, prospect-scoped assets shared by the studios."""
import io
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from ads.server import MAX_AUDIO
from .ad_copy import stored_json
from .db import get_db
from .models import Lead, ProspectMedia

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
CATEGORIES = {'logo': 'Logo', 'products': 'Produits', 'premises': 'Locaux',
              'work': 'Réalisations', 'other': 'Autre'}
MAX_BYTES = 24 * 1024 * 1024


def require_lead(db, lead_id):
    lead = db.get(Lead, lead_id) if lead_id is not None else None
    if lead_id is None or not lead:
        raise HTTPException(404, 'Prospect introuvable.')
    return lead


def selected_media(db, lead_id, ids, types=('image', 'audio', 'video'), limit=12):
    if not isinstance(ids, list) or len(ids) > limit or any(
        not isinstance(identifier, str) or len(identifier) != 32 for identifier in ids
    ) or len(set(ids)) != len(ids):
        raise HTTPException(400, 'Sélection de médias invalide.')
    if not ids:
        return []
    require_lead(db, lead_id)
    rows = {row.id: row for row in db.scalars(select(ProspectMedia).where(
        ProspectMedia.lead_id == lead_id, ProspectMedia.id.in_(ids)))}
    if any(identifier not in rows or rows[identifier].mime.split('/')[0] not in types for identifier in ids):
        raise HTTPException(404, 'Média indisponible pour ce prospect.')
    return [rows[identifier] for identifier in ids]


def media_payload(row):
    return {'id': row.id, 'lead_id': row.lead_id, 'name': row.name, 'size': row.size,
            'mime': row.mime, 'category': row.category, 'source': row.source,
            'attribution': row.attribution, 'url': f'/api/leads/{row.lead_id}/media/{row.id}'}


def image_from_bytes(data):
    with Image.open(io.BytesIO(data), formats=['PNG', 'JPEG', 'WEBP']) as image:
        if image.width * image.height > 20_000_000 or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Image animée ou dimensions trop grandes.')
        return ImageOps.exif_transpose(image).convert('RGBA')


def validate(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Fichier vide ou supérieur à 24 Mio.')
    if data.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff')) or (
        data.startswith(b'RIFF') and data[8:12] == b'WEBP'
    ):
        try:
            image = image_from_bytes(data)
            output = io.BytesIO()
            image.save(output, 'PNG')
            encoded = output.getvalue()
            if len(encoded) > MAX_BYTES:
                raise ValueError('Image trop volumineuse après décodage.')
            return 'image/png', encoded
        except (OSError, Image.DecompressionBombError, SyntaxError) as error:
            raise ValueError('Image illisible.') from error
    if data[4:8] == b'ftyp':
        demuxer = 'mov'
    elif data.startswith(b'RIFF') and data[8:12] == b'WAVE':
        demuxer = 'wav'
    elif data.startswith(b'ID3') or len(data) >= 2 and data[0] == 255 and data[1] & 224 == 224:
        demuxer = 'mp3'
    else:
        raise ValueError('Format non pris en charge.')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'upload'
        path.write_bytes(data)
        try:
            result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
                                     '-f', demuxer, '-show_streams', '-show_format', '-of', 'json', str(path)],
                                    capture_output=True, check=True, timeout=15)
            info = json.loads(result.stdout)
            streams = [s for s in info['streams'] if s['codec_type'] in ('video', 'audio')
                       and not s.get('disposition', {}).get('attached_pic')]
            video = next((s for s in streams if s['codec_type'] == 'video'), None)
            audio = next((s for s in streams if s['codec_type'] == 'audio'), None)
            formats = info['format']['format_name'].split(',')
            duration = float(info['format'].get('duration', 0))
            if not 0 < duration <= 180 or len(streams) > 2:
                raise ValueError()
            if video and video['width'] * video['height'] <= 3840 * 2160 and video['codec_name'] == 'h264' and 'mp4' in formats:
                mime = 'video/mp4'
            elif not video and audio and audio['codec_name'] == 'mp3' and 'mp3' in formats:
                mime = 'audio/mpeg'
            elif not video and audio and audio['codec_name'].startswith('pcm_') and 'wav' in formats:
                mime = 'audio/wav'
            else:
                raise ValueError()
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-threads', '2',
                            '-protocol_whitelist', 'file', '-f', demuxer, '-i', str(path), '-map',
                            '0:v:0' if video else '0:a:0', '-f', 'null', '-'],
                           capture_output=True, check=True, timeout=45)
            return mime, data
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
            raise ValueError('Fichier illisible ou format non pris en charge. Utilisez PNG, JPEG, WebP, MP4 H.264, MP3 ou WAV (3 minutes maximum).') from error


def save_media(db, lead_id, name, category, data, source='upload', attribution=''):
    if category not in CATEGORIES:
        raise HTTPException(400, 'Catégorie invalide.')
    try:
        mime, content = validate(data)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if mime.startswith('audio/') and len(content) > MAX_AUDIO:
        raise HTTPException(413, 'Les fichiers audio sont limités à 20 Mio.')
    if category == 'logo' and not mime.startswith('image/'):
        raise HTTPException(400, 'Un logo doit être une image.')
    row = ProspectMedia(id=uuid4().hex, lead_id=lead_id, name=(name or 'Média')[:255],
                        category=category, mime=mime, content=content, size=len(content),
                        source=source, attribution=attribution)
    db.add(row)
    db.commit()
    return media_payload(row)


@router.get('/media')
def library(request: Request, lead_id: int | None = None, db: Session = Depends(get_db)):
    if lead_id is not None:
        require_lead(db, lead_id)
    return templates.TemplateResponse(request, 'media_library.html', {
        'lead_id': lead_id, 'leads': db.execute(select(Lead.id, Lead.name).order_by(Lead.name)).all(),
        'categories': CATEGORIES})


@router.get('/api/leads/{lead_id}/media')
def list_media(lead_id: int, db: Session = Depends(get_db)):
    lead = require_lead(db, lead_id)
    photos = stored_json(lead.photos_json, [])
    return {'media': [media_payload(row) for row in db.scalars(select(ProspectMedia).where(
        ProspectMedia.lead_id == lead_id).order_by(ProspectMedia.created_at.desc()))],
        'google': [{'index': i, 'url': f'/api/leads/{lead_id}/photos/{i}',
                    'authors': [a.get('displayName', '') for a in photo.get('authorAttributions', [])]}
                   for i, photo in enumerate(photos) if photo.get('media_uri')]}


@router.post('/api/leads/{lead_id}/media', status_code=201)
def upload(lead_id: int, category: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    require_lead(db, lead_id)
    return save_media(db, lead_id, file.filename, category, file.file.read(MAX_BYTES + 1))


@router.post('/api/leads/{lead_id}/media/google/{index}', status_code=201)
def import_google(lead_id: int, index: int, db: Session = Depends(get_db)):
    lead = require_lead(db, lead_id)
    photos = stored_json(lead.photos_json, [])
    if not 0 <= index < len(photos):
        raise HTTPException(404, 'Photo Google introuvable.')
    photo = photos[index]
    uri = urlsplit(photo.get('media_uri') or '')
    if uri.scheme != 'https' or uri.username or uri.password or uri.port not in (None, 443) or not (
        uri.hostname == 'lh3.googleusercontent.com' or (uri.hostname or '').endswith('.googleusercontent.com')
    ):
        raise HTTPException(400, 'Adresse de la photo Google indisponible.')
    try:
        content = bytearray()
        with httpx.stream('GET', uri.geturl(), timeout=15, follow_redirects=False) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise HTTPException(413, 'Photo trop volumineuse.')
    except httpx.HTTPError as error:
        raise HTTPException(502, 'Photo Google indisponible.') from error
    attribution = ', '.join(a.get('displayName', '') for a in photo.get('authorAttributions', []))
    return save_media(db, lead_id, f'Photo Google {index + 1}', 'other', bytes(content), 'google', attribution)


@router.get('/api/leads/{lead_id}/media/{identifier}')
def media_file(lead_id: int, identifier: str, request: Request, db: Session = Depends(get_db)):
    row, = selected_media(db, lead_id, [identifier])
    data = row.content
    headers = {'X-Content-Type-Options': 'nosniff', 'Accept-Ranges': 'bytes'}
    byte_range = request.headers.get('range')
    if byte_range:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', byte_range)
        if match and any(match.groups()):
            first, last = match.groups()
            start = int(first) if first else max(0, len(data) - int(last))
            end = min(len(data) - 1, int(last)) if first and last else len(data) - 1
            if 0 <= start <= end:
                headers['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
                return Response(data[start:end + 1], status_code=206, media_type=row.mime, headers=headers)
        return Response(status_code=416, headers={'Content-Range': f'bytes */{len(data)}'})
    return Response(data, media_type=row.mime, headers=headers)


@router.patch('/api/leads/{lead_id}/media/{identifier}')
def categorize(lead_id: int, identifier: str, category: str = Form(...), db: Session = Depends(get_db)):
    row, = selected_media(db, lead_id, [identifier])
    if category not in CATEGORIES or (category == 'logo' and not row.mime.startswith('image/')):
        raise HTTPException(400, 'Catégorie invalide pour ce média.')
    row.category = category
    db.commit()
    return media_payload(row)
