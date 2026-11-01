"""Serve Ads Studio inside the main ProfileFinder application."""
import json
from pathlib import Path
import urllib.error

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from ads.server import mix_audio
from .models import Job
from .db import SessionLocal
from .job_tracking import start_task, finish_task
from .voice import synthesize, voice_status, VoiceUnavailable

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent


@router.get('/ads', include_in_schema=False)
@router.get('/ads/', include_in_schema=False)
def studio():
    return FileResponse(ROOT / 'ads/index.html')


@router.get('/theme.css', include_in_schema=False)
def theme():
    return FileResponse(ROOT / 'shared/theme.css', media_type='text/css')


@router.get('/layout.js', include_in_schema=False)
def layout():
    return FileResponse(ROOT / 'shared/layout.js', media_type='text/javascript')


@router.get('/app.js', include_in_schema=False)
def script():
    return FileResponse(ROOT / 'ads/app.js', media_type='text/javascript')


@router.get('/api/status')
def status():
    return voice_status()


def tracked_audio(data, mix=False):
    with SessionLocal() as db:
        lead_id=data.get('lead_id')
        if lead_id is not None and type(lead_id) is not int:
            raise ValueError('Identifiant de prospect invalide.')
        task=start_task(db,'audio_mix' if mix else 'audio_voice',lead_id,
                        stage='Mixage FFmpeg' if mix else 'Synthèse vocale · '+('ElevenLabs' if data.get('provider')=='elevenlabs' else 'OpenAI'))
        db.commit()
        task_id=task.id
    try:
        result=mix_audio(data) if mix else synthesize(data)
    except Exception as error:
        message=str(error) if isinstance(error,(ValueError,VoiceUnavailable)) else 'Le mixage audio a échoué.' if mix else 'La génération vocale a échoué. Vérifiez la connexion, la clé et les crédits du fournisseur.'
        with SessionLocal() as db:
            task=db.get(Job,task_id)
            if task: finish_task(task,message)
            db.commit()
        raise
    with SessionLocal() as db:
        task=db.get(Job,task_id)
        if task: finish_task(task)
        db.commit()
    return Response(result,media_type='audio/mpeg')


@router.post('/api/mix')
@router.post('/api/voice')
async def audio(request: Request):
    origin = request.headers.get('origin')
    if origin and origin != f'{request.url.scheme}://{request.headers.get("host", "")}':
        return JSONResponse({'error': 'Origine non autorisée.'}, status_code=403)
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        return JSONResponse({'error': 'Une requête JSON est requise.'}, status_code=415)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 57 * 1024 * 1024:
            return JSONResponse({'error': 'Requête trop volumineuse.'}, status_code=413)
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError('Objet JSON attendu.')
        if request.url.path == '/api/mix':
            return await run_in_threadpool(tracked_audio, data, True)
        return await run_in_threadpool(tracked_audio, data)
    except (ValueError, UnicodeDecodeError) as error:
        return JSONResponse({'error': str(error)}, status_code=400)
    except VoiceUnavailable as error:
        return JSONResponse({'error': str(error)}, status_code=503)
    except urllib.error.HTTPError as error:
        return JSONResponse({'error': f'Le moteur vocal a refusé la génération (HTTP {error.code}). Vérifiez sa clé, la voix et vos crédits.'}, status_code=502)
    except (urllib.error.URLError, TimeoutError):
        return JSONResponse({'error': 'Le moteur vocal est injoignable.'}, status_code=502)
