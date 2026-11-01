"""Voice providers shared by the application and standalone Ads server."""
import json
import re
import shutil
import urllib.request
from .config import settings

OPENAI_VOICES = ('alloy', 'ash', 'coral', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer')


class VoiceUnavailable(Exception):
    pass


def voice_status():
    cfg = settings()
    return {'default_provider': 'openai', 'openai': bool(cfg.openai_api_key),
            'elevenlabs': bool(cfg.elevenlabs_api_key),
            'ffmpeg': bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))}


def synthesize(data):
    cfg = settings()
    provider = data.get('provider', 'openai')
    if provider not in ('openai', 'elevenlabs'):
        raise ValueError('Moteur vocal invalide.')
    text = data.get('text', '')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4096:
        raise ValueError('Le texte doit contenir entre 1 et 4 096 caractères.')
    if provider == 'openai':
        if not cfg.openai_api_key:
            raise VoiceUnavailable('La clé OpenAI de ProfileFinder n’est pas configurée. Vous pouvez importer une voix off.')
        voice = data.get('voice', 'coral')
        if voice not in OPENAI_VOICES:
            raise ValueError('Voix OpenAI invalide.')
        instructions = data.get('instructions', '')
        if not isinstance(instructions, str) or len(instructions) > 1000:
            raise ValueError('Les consignes vocales sont limitées à 1 000 caractères.')
        body = {'model': cfg.openai_tts_model, 'input': text, 'voice': voice, 'response_format': 'mp3'}
        if instructions.strip():
            body['instructions'] = instructions.strip()
        url = 'https://api.openai.com/v1/audio/speech'
        headers = {'Authorization': 'Bearer ' + cfg.openai_api_key}
    else:
        if not cfg.elevenlabs_api_key:
            raise VoiceUnavailable('ElevenLabs est optionnel. Configurez sa clé ou utilisez OpenAI.')
        voice = data.get('voice_id', '')
        if not isinstance(voice, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', voice):
            raise ValueError('Identifiant de voix ElevenLabs invalide.')
        body = {'text': text, 'model_id': 'eleven_multilingual_v2'}
        url = f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128'
        headers = {'xi-api-key': cfg.elevenlabs_api_key}
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'})
    with urllib.request.urlopen(request, timeout=90) as response:
        audio = response.read()
        if not audio:
            raise VoiceUnavailable('Le moteur vocal a renvoyé un fichier vide. Réessayez.')
        return audio
