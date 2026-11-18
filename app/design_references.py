"""Google Images discovery and a shared library of selected Image Ads references."""
import base64
import binascii
import hashlib
import hmac
import http.client
import io
import json
from time import time
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .media import MAX_BYTES, image_from_bytes
from .models import DesignReference
from .website_identity import public_resource

router = APIRouter(prefix='/api/design-references')
IMAGE_TYPES = ('image/png', 'image/jpeg', 'image/webp')


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
def search(q: str = Query(min_length=2, max_length=150)):
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
        output.append({'title': title, 'source_url': source, 'thumbnail': thumbnail, 'token': result_token(result, key)})
    return {'results': output}


@router.post('', status_code=201)
def save(bookmark: Bookmark, db: Session = Depends(get_db)):
    key = settings().serpapi_api_key
    if not key:
        raise HTTPException(503, 'Configurez SERPAPI_API_KEY pour enregistrer un nouveau résultat.')
    result = unpack_result(bookmark.token, key)
    identifier = hashlib.sha256(result['original'].encode()).hexdigest()[:32]
    existing = db.get(DesignReference, identifier)
    if existing:
        return payload(existing)
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
        raise HTTPException(422, 'Image indisponible ou incompatible. Choisissez un autre résultat.')
    output = io.BytesIO()
    image.save(output, 'PNG')
    db.execute(insert(DesignReference).values(
        id=identifier, title=result['title'], source_url=result['source_url'], content=output.getvalue()
    ).on_conflict_do_nothing(index_elements=['id']))
    db.commit()
    return payload(db.get(DesignReference, identifier))


@router.get('/{identifier}/image')
def image(identifier: str, db: Session = Depends(get_db)):
    row = db.get(DesignReference, identifier)
    if not row:
        raise HTTPException(404, 'Référence introuvable.')
    return Response(row.content, media_type='image/png', headers={'X-Content-Type-Options': 'nosniff'})
