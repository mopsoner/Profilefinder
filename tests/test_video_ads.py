import base64
import io
import json
import math
import shutil
import sys
import threading
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.models import Lead, LeadWebsite, AudioAd, VideoAd
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


def test_missing_dependencies_are_named_and_rechecked(monkeypatch):
    monkeypatch.setattr(video_ads.shutil,'which',lambda _: None)
    monkeypatch.setitem(sys.modules,'playwright.sync_api',None)
    assert video_ads.video_dependencies()['missing']==['FFmpeg','ffprobe','Playwright','Chromium']
    monkeypatch.setattr(video_ads.shutil,'which',lambda name:'/usr/bin/'+name)
    assert video_ads.video_dependencies()['missing']==['Playwright']


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


def test_scoped_video_studio_preserves_prospect_context(client):
    http, _ = client
    response=http.get('/leads/1/video-ads')
    assert response.status_code==200
    assert 'data-selected-lead="1"' in response.text
    assert 'Les publicités vidéo de <strong>Entreprise A</strong>' in response.text
    assert '<option value="2"' not in response.text
    assert '/leads/1#creations' in response.text
    assert http.get('/leads/999/video-ads').status_code==404


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
    restored = next(a for a in http.get('/api/video-ads/leads/1').json()['audios'] if a['id']==value['id'])
    assert restored['script']=='Découvrez notre entreprise.'
    with sessions() as db:
        assert db.get(AudioAd, value['id']).script == 'Découvrez notre entreprise.'


def test_storyboard_uses_the_message_saved_with_its_audio(client, monkeypatch):
    http, sessions = client
    script = 'Découvrez Entreprise A. Une annonce conservée avec sa voix off.'
    with sessions() as db:
        db.get(AudioAd,'a'*32).script=script
        db.add(LeadWebsite(lead_id=1,content_json=json.dumps({'pages':[{'title':'Accueil'}]})))
        db.commit()
    folder=video_ads.MEDIA/'audio'
    folder.mkdir(parents=True)
    (folder/('a'*32+'.mp3')).write_bytes(b'fixture')
    monkeypatch.setattr(video_ads,'slot',threading.BoundedSemaphore(1))
    monkeypatch.setattr(video_ads.pool,'submit',lambda *args:None)
    try:
        response=http.post('/api/video-ads/prepare',json={'lead_id':1,'audio_id':'a'*32,'format':'portrait','script':'Un autre texte ne doit pas remplacer le message audio.'})
        assert response.status_code==200
        assert ' '.join(s['caption'] for s in response.json()['slides'])==script
    finally:
        video_ads.slot.release()


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
