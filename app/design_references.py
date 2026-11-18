"""Google Images discovery and a shared library of selected Image Ads references."""
import base64
import binascii
import hashlib
import hmac
import http.client
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from time import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .db import get_db
from .media import MAX_BYTES, image_from_bytes
from .models import DesignReference
from .website_identity import public_resource

router = APIRouter(prefix='/api/design-references')
IMAGE_TYPES = ('image/png', 'image/jpeg', 'image/webp')
logger = logging.getLogger(__name__)
imports = ThreadPoolExecutor(max_workers=2, thread_name_prefix='design-import')
downloads = ThreadPoolExecutor(max_workers=6, thread_name_prefix='design-download')
import_jobs = {}
import_lock = Lock()


def web_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return ''
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not (parsed.username or parsed.password):
            return value
    except ValueError:
        pass
    return ''


def trusted_thumbnail(value):
    url = web_url(value)
    if not url:
        return ''
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme == 'https' and (host == 'gstatic.com' or host.endswith('.gstatic.com') or
                                     host == 'serpapi.com' or host.endswith('.serpapi.com')):
        return url
    return ''


def result_token(result, key):
    data = base64.urlsafe_b64encode(json.dumps({**result, 'expires': int(time()) + 3600}).encode())
    return data.decode() + '.' + hmac.new(key.encode(), data, hashlib.sha256).hexdigest()


class Bookmark(BaseModel):
    token: str = Field(max_length=14000)


def unpack_result(token, key):
    try:
        data, signature = token.split('.', 1)
        if not hmac.compare_digest(hmac.new(key.encode(), data.encode(), hashlib.sha256).hexdigest(), signature):
            raise ValueError()
        result = json.loads(base64.urlsafe_b64decode(data))
        if result['expires'] < time():
            raise ValueError()
        return result
    except (ValueError, KeyError, TypeError, binascii.Error) as error:
        raise HTTPException(400, 'Résultat expiré ou invalide. Relancez la recherche.') from error


def payload(row):
    return {'id': row.id, 'title': row.title, 'source_url': row.source_url,
            'url': f'/api/design-references/{row.id}/image'}


def selected_design_references(db, identifiers):
    if not identifiers:
        return []
    matches = {row.id: row for row in db.scalars(select(DesignReference).where(DesignReference.id.in_(identifiers)))}
    if len(matches) != len(identifiers):
        raise HTTPException(400, 'Sélection de références indisponible ou invalide.')
    return [matches[identifier] for identifier in identifiers]


@router.get('')
def library(db: Session = Depends(get_db)):
    saved = db.scalars(select(DesignReference).order_by(DesignReference.created_at.desc())).all()
    return {'search_available': bool(settings().serpapi_api_key), 'references': [payload(row) for row in saved]}


@router.get('/search')
def search(q: str = Query(min_length=2, max_length=150), db: Session = Depends(get_db)):
    key = settings().serpapi_api_key
    if not key:
        raise HTTPException(503, 'Configurez SERPAPI_API_KEY pour utiliser la recherche.')
    query = ' '.join(q.split())
    if len(query) < 2:
        raise HTTPException(400, 'Saisissez au moins deux caractères.')
    try:
        response = httpx.get('https://serpapi.com/search.json', params={
            'engine': 'google_images', 'q': query, 'api_key': key,
        }, timeout=15)
        if response.status_code == 429:
            raise HTTPException(429, 'Quota SerpAPI atteint. Les références enregistrées restent disponibles.')
        response.raise_for_status()
        data = response.json()
        results = data.get('images_results', [])
        if data.get('error'):
            raise HTTPException(502, 'SerpAPI a refusé la recherche. Vérifiez la clé et le quota.')
    except (httpx.HTTPError, ValueError, AttributeError) as error:
        raise HTTPException(502, 'Recherche Google Images indisponible.') from error
    output = []
    to_import = []
    seen = set()
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        original = web_url(item.get('original'))
        thumbnails = [trusted_thumbnail(item.get('thumbnail')), trusted_thumbnail(item.get('serpapi_thumbnail'))]
        thumbnail = next((value for value in thumbnails if value), '')
        if not original or original in seen:
            continue
        seen.add(original)
        title = str(item.get('title') or 'Référence Google Images')[:255]
        source = web_url(item.get('link')) or original
        result = {'title': title, 'source_url': source, 'original': original, 'thumbnail': thumbnail}
        to_import.append(result)
        output.append({
            'id': reference_id(result), 'title': title, 'source_url': source,
            'thumbnail': thumbnail, 'token': result_token(result, key),
        })
    batch_id = None
    if to_import:
        batch_id = uuid4().hex
        with import_lock:
            for old_id in list(import_jobs):
                if len(import_jobs) < 100:
                    break
                if import_jobs[old_id].done():
                    del import_jobs[old_id]
            import_jobs[batch_id] = imports.submit(import_results, sessionmaker(bind=db.get_bind()), to_import)
    return {'results': output, 'batch_id': batch_id}


def reference_id(result):
    return hashlib.sha256(result['original'].encode()).hexdigest()[:32]


def download_reference(result):
    for url in (result['original'], result['thumbnail']):
        if not url:
            continue
        try:
            original = public_resource(url, IMAGE_TYPES, MAX_BYTES)
            image = image_from_bytes(original)
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, http.client.HTTPException):
            continue
        break
    else:
        return None
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


def persist_reference(db, result, content):
    identifier = reference_id(result)
    db.execute(insert(DesignReference).values(
        id=identifier, title=result['title'], source_url=result['source_url'], content=content
    ).on_conflict_do_nothing(index_elements=['id']))
    db.commit()
    return identifier


def import_results(sessions, results):
    by_id = {reference_id(result): result for result in results}
    with sessions() as db:
        existing = set(db.scalars(select(DesignReference.id).where(DesignReference.id.in_(by_id))))
    saved = len(existing)
    pending = {downloads.submit(download_reference, result): result
               for identifier, result in by_id.items() if identifier not in existing}
    for future in as_completed(pending):
        result = pending.pop(future)
        try:
            content = future.result()
            if content:
                with sessions() as db:
                    persist_reference(db, result, content)
                saved += 1
        except Exception:
            logger.warning('Échec d’import d’une référence de design.', exc_info=True)
    return {'saved': saved, 'unavailable': len(by_id) - saved}


@router.get('/imports/{batch_id}')
def import_status(batch_id: str):
    with import_lock:
        job = import_jobs.get(batch_id)
    if job is None:
        raise HTTPException(404, 'Import introuvable.')
    if not job.done():
        return {'status': 'running'}
    if job.exception():
        raise HTTPException(500, 'Import interrompu. Relancez la recherche pour compléter la bibliothèque.')
    return {'status': 'completed', **job.result()}


@router.post('', status_code=201)
def save(bookmark: Bookmark, db: Session = Depends(get_db)):
    key = settings().serpapi_api_key
    if not key:
        raise HTTPException(503, 'Configurez SERPAPI_API_KEY pour enregistrer un nouveau résultat.')
    result = unpack_result(bookmark.token, key)
    identifier = reference_id(result)
    existing = db.get(DesignReference, identifier)
    if existing:
        return payload(existing)
    content = download_reference(result)
    if content is None:
        raise HTTPException(422, 'Image indisponible ou incompatible. Choisissez un autre résultat.')
    persist_reference(db, result, content)
    return payload(db.get(DesignReference, identifier))


@router.get('/{identifier}/image')
def image(identifier: str, db: Session = Depends(get_db)):
    row = db.get(DesignReference, identifier)
    if not row:
        raise HTTPException(404, 'Référence introuvable.')
    return Response(row.content, media_type='image/png', headers={'X-Content-Type-Options': 'nosniff'})
