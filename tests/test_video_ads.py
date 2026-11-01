import base64
import io
import json
import math
import shutil
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.models import Lead, AudioAd, VideoAd
from app import video_ads
from app.video_render import split_script, validate_slides, site_pages, embed_local_images


def test_script_is_preserved_and_timing_fills_audio():
    script = ' '.join(f'mot{i}' for i in range(130))
    slides = split_script(script, [{'title':'Accueil'}, {'title':'Services'}], 31.5)
    assert ' '.join(slide['caption'] for slide in slides) == script
    assert 2 <= len(slides) <= 8
    assert math.isclose(sum(slide['duration'] for slide in slides), 31.5)
    assert {slide['page_index'] for slide in slides} == {0, 1}


def test_slide_order_and_duration_are_validated():
    slides = validate_slides([{'page_index':1,'caption':'Services','duration':3}, {'page_index':0,'caption':'Contact','duration':7}], 2, 16)
    assert [s['page_index'] for s in slides] == [1, 0]
    assert math.isclose(sum(s['duration'] for s in slides), 16)
    assert all(s['duration'] >= .5 for s in slides)
    again = validate_slides(slides, 2, 16)
    assert all(math.isclose(a['duration'], b['duration']) for a,b in zip(slides, again))
    for invalid in ([], [{'page_index':9,'caption':'Test','duration':3}], [{'page_index':0,'caption':'Test','duration':float('nan')}], [{'page_index':0,'caption':'','duration':3}]):
        with pytest.raises(ValueError):
            validate_slides(invalid, 2, 16)


def test_legacy_sites_and_remote_images():
    assert site_pages({'headline':'Bienvenue'}, 'Entreprise')[0]['title'] == 'Bienvenue'
    html = embed_local_images('<img src="https://example.com/image.jpg"><img src="/static/generated/../../../../etc/passwd">')
    assert 'example.com' not in html
    assert 'passwd' not in html
    assert html.count('data:image/svg+xml') == 2
    assert site_pages({'pages':None}, 'Entreprise')[0]['title'] == 'Entreprise'


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path/'test.db'), connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([Lead(id=1, place_id='test1', name='Entreprise A'), Lead(id=2, place_id='test2', name='Entreprise B')])
        db.add(AudioAd(id='a'*32, lead_id=1, script='Bonjour', duration=3))
        db.commit()
    monkeypatch.setattr(video_ads, 'MEDIA', tmp_path/'media')
    monkeypatch.setattr(video_ads, 'SessionLocal', sessions)
    monkeypatch.setattr(video_ads, 'video_tools_ready', lambda: True)
    app = FastAPI()
    app.include_router(video_ads.router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, sessions
    engine.dispose()


def test_audio_must_belong_to_selected_lead(client):
    http, _ = client
    response = http.post('/api/video-ads/prepare', json={'lead_id':2,'audio_id':'a'*32,'format':'portrait'})
    assert response.status_code == 400
    assert 'appartenant' in response.json()['detail']
    assert http.post('/api/video-ads/prepare',json={'lead_id':1,'audio_id':'a'*32,'format':[]}).status_code == 400


def test_audio_requires_script_and_a_real_lead(client):
    http, _ = client
    assert http.post('/api/ads/audio',json={'lead_id':999,'script':'Bonjour','audio':'bad'}).status_code == 404
    assert http.post('/api/ads/audio',json={'lead_id':1,'script':'','audio':'bad'}).status_code == 400
    assert http.post('/api/ads/audio',json={'lead_id':1,'script':'Bonjour','audio':'bad'}).status_code == 400


def test_message_endpoint_uses_server_profile_and_validates_settings(client, monkeypatch):
    http, _ = client
    captured = []
    def generate(facts, tone, duration, details):
        captured.append((facts,tone,duration,details))
        return {'script':'Découvrez Entreprise A.','estimated_duration':3}
    monkeypatch.setattr(video_ads,'generate_copy',generate)
    response=http.post('/api/ads/message',json={'lead_id':1,'profile':{'name':'Profil falsifié'},'tone':'bold','duration':15,'details':'Un accueil chaleureux'})
    assert response.status_code==200
    assert captured[0][0]['profil']['nom']=='Entreprise A'
    assert captured[0][1:]==('bold',15,'Un accueil chaleureux')
    assert http.post('/api/ads/message',json={'lead_id':999}).status_code==404
    assert http.post('/api/ads/message',json={'lead_id':1,'duration':300}).status_code==400


@pytest.mark.skipif(not shutil.which('ffprobe'), reason='ffprobe required')
def test_audio_persists_and_can_be_reused(client):
    http, sessions = client
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(b'\x00\x00'*16000)
    response = http.post('/api/ads/audio',json={'lead_id':1,'script':'Découvrez notre entreprise.','audio':base64.b64encode(buffer.getvalue()).decode()})
    assert response.status_code == 200
    value = response.json()
    assert math.isclose(value['duration'], 2, abs_tol=.1)
    assert http.get(value['url']).content == buffer.getvalue()
    assert value['id'] in [a['id'] for a in http.get('/api/video-ads/leads/1').json()['audios']]
    with sessions() as db:
        assert db.get(AudioAd, value['id']).script == 'Découvrez notre entreprise.'


def test_restart_marks_only_interrupted_jobs_failed(client):
    _, sessions = client
    with sessions() as db:
        for status in ('rendering', 'ready'):
            db.add(VideoAd(id=status, lead_id=1, audio_id='a'*32, status=status, site_json='{}', slides_json='[]'))
        db.commit()
    video_ads.recover_interrupted_jobs()
    with sessions() as db:
        assert db.get(VideoAd, 'rendering').status == 'failed'
        assert db.get(VideoAd, 'ready').status == 'ready'
