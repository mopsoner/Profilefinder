import io
import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import voice
from app.ads import router


@pytest.fixture
def config(monkeypatch):
    cfg = SimpleNamespace(openai_api_key='test-openai', elevenlabs_api_key='test-eleven', openai_tts_model='gpt-4o-mini-tts')
    monkeypatch.setattr(voice, 'settings', lambda: cfg)
    return cfg


def test_openai_default_reuses_configured_key_and_sends_direction(config):
    with patch('app.voice.urllib.request.urlopen', return_value=io.BytesIO(b'voice-mp3')) as send:
        assert voice.synthesize({'text': 'Découvrez notre entreprise.', 'instructions': 'Chaleureux.'}) == b'voice-mp3'
    request = send.call_args.args[0]
    assert request.full_url == 'https://api.openai.com/v1/audio/speech'
    assert request.get_header('Authorization') == 'Bearer test-openai'
    assert json.loads(request.data) == {'model': 'gpt-4o-mini-tts', 'input': 'Découvrez notre entreprise.', 'voice': 'coral', 'response_format': 'mp3', 'instructions': 'Chaleureux.'}


def test_elevenlabs_is_explicit_option(config):
    with patch('app.voice.urllib.request.urlopen', return_value=io.BytesIO(b'eleven-mp3')) as send:
        assert voice.synthesize({'provider': 'elevenlabs', 'text': 'Bonjour', 'voice_id': 'voice123'}) == b'eleven-mp3'
    request = send.call_args.args[0]
    assert request.full_url.startswith('https://api.elevenlabs.io/v1/text-to-speech/voice123?')
    assert request.get_header('Xi-api-key') == 'test-eleven'
    assert request.get_header('Authorization') is None


def test_missing_openai_key_does_not_fallback_or_make_requests(config):
    config.openai_api_key = ''
    with patch('app.voice.urllib.request.urlopen') as send:
        with pytest.raises(voice.VoiceUnavailable):
            voice.synthesize({'text': 'Bonjour'})
        send.assert_not_called()


@pytest.mark.parametrize('data', [
    {'text': ''}, {'text': 'a' * 4097}, {'text': 'Bonjour', 'provider': 'unknown'},
    {'text': 'Bonjour', 'voice': 'invalid'}, {'text': 'Bonjour', 'instructions': 'a' * 1001},
    {'text': 'Bonjour', 'provider': 'elevenlabs', 'voice_id': '../invalid'},
])
def test_invalid_inputs_never_reach_provider(config, data):
    with patch('app.voice.urllib.request.urlopen') as send:
        with pytest.raises(ValueError):
            voice.synthesize(data)
        send.assert_not_called()


def test_api_serves_audio_and_reports_configuration_without_secrets(config):
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        status = client.get('/api/status').json()
        assert status['default_provider'] == 'openai'
        assert status['openai'] is True
        assert 'test-openai' not in json.dumps(status)
        with patch('app.voice.urllib.request.urlopen', return_value=io.BytesIO(b'mp3')):
            response = client.post('/api/voice', json={'text': 'Bonjour'})
        assert response.status_code == 200
        assert response.headers['content-type'] == 'audio/mpeg'
        assert response.content == b'mp3'
        config.openai_api_key = ''
        assert client.post('/api/voice', json={'text': 'Bonjour'}).status_code == 503
