import base64
import io
import json
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageChops
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import ads, image_ads, media, video_ads
from app.db import Base, get_db
from app.job_tracking import activity_feed, start_task
from app.models import ImageAd, Lead, LeadWebsite
from app.video_render import encode_video


def png(color='tomato', size=(120, 90)):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, 'PNG')
    return buffer.getvalue()


@pytest.fixture
def studio(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "studio.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def dependency():
        with sessions() as db:
            yield db

    with sessions() as db:
        photos = [{'media_uri': 'https://lh3.googleusercontent.com/photo',
                   'authorAttributions': [{'displayName': 'Photographe'}]}]
        db.add_all([Lead(id=1, name='Alpha', place_id='a', photos_json=json.dumps(photos)),
                    Lead(id=2, name='Bravo', place_id='b'),
                    LeadWebsite(lead_id=1, content_json='{"theme":"warm"}')])
        db.commit()
    monkeypatch.setattr(image_ads, 'SessionLocal', sessions)
    monkeypatch.setattr(ads, 'SessionLocal', sessions)
    monkeypatch.setattr(video_ads, 'MEDIA', tmp_path / 'media')
    api = FastAPI()
    api.dependency_overrides[get_db] = dependency
    for router in (media.router, image_ads.router, ads.router, video_ads.router):
        api.include_router(router)
    with TestClient(api) as client:
        yield client, sessions
    engine.dispose()


def upload(client, lead=1, category='products', data=None, name='asset.png'):
    return client.post(f'/api/leads/{lead}/media', data={'category': category},
                       files={'file': (name, png() if data is None else data)})


def wait(client, identifier, status='completed'):
    for _ in range(120):
        response = client.get(f'/api/leads/1/image-ads/{identifier}')
        project = response.json()
        if project['jobs'][0]['status'] in ('completed', 'failed'):
            assert project['jobs'][0]['status'] == status, project
            return project
        time.sleep(.05)
    pytest.fail('Image Ads job timed out')


def test_media_scope_content_and_categories(studio):
    client, _ = studio
    media_row = upload(client).json()
    assert media_row['mime'] == 'image/png'
    assert client.get(media_row['url']).content == media.validate(png())[1]
    assert client.get(media_row['url'], headers={'Range': 'bytes=0-7'}).status_code == 206
    assert client.get(media_row['url'].replace('/1/', '/2/')).status_code == 404
    assert client.patch(media_row['url'].replace('/1/', '/2/'), data={'category': 'logo'}).status_code == 404
    assert client.patch(media_row['url'], data={'category': 'work'}).json()['category'] == 'work'
    assert upload(client, data=b'this is not an image').status_code == 400
    assert upload(client, data=png()[:30]).status_code == 400
    assert upload(client, data=b'x' * (media.MAX_BYTES + 1)).status_code == 400
    google = client.get('/api/leads/1/media').json()['google']
    assert google == [{'index': 0, 'url': '/api/leads/1/photos/0', 'authors': ['Photographe']}]
    assert client.get('/api/leads/2/media').json() == {'media': [], 'google': []}
    assert client.post('/api/mix', json={'lead_id': 2, 'voice_media_id': media_row['id']}).status_code == 404
    assert client.post('/api/ads/message', json={'lead_id': 2, 'media_ids': [media_row['id']]}).status_code == 404


def test_real_image_and_image_ai_reuse_background(studio, monkeypatch):
    client, sessions = studio
    photo = upload(client).json()['id']
    logo = upload(client, category='logo', data=png('lime', (80, 30))).json()['id']
    options = {'mode': 'photo', 'format': 'story', 'message': 'Pour vous', 'media_ids': [photo], 'logo_id': logo}
    url = '/api/leads/1/image-ads'
    assert client.post(url.replace('/1/', '/2/'), json=options).status_code == 404
    first = client.post(url, json=options)
    assert first.status_code == 202
    identifier = first.json()['id']
    project = wait(client, identifier)
    assert project['options']['display_name'] == 'Alpha'
    assert client.get(project['png'].replace('/1/', '/2/')).status_code == 404
    output = client.get(project['png'] + '?download=true')
    image = Image.open(io.BytesIO(output.content))
    assert image.size == (1080, 1920)
    assert image.getpixel((110, 110)) == (0, 255, 0)
    assert image.getpixel((540, 960)) == (255, 99, 71)
    assert 'attachment' in output.headers['content-disposition']

    calls = []
    monkeypatch.setattr(image_ads, 'settings', lambda: SimpleNamespace(
        openai_api_key='mock', openai_image_model='test-image'))

    def fake_image(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {'data': [{'b64_json': base64.b64encode(png('blue')).decode()}]})

    monkeypatch.setattr(image_ads.httpx, 'post', fake_image)
    monkeypatch.setattr(image_ads, 'generate_copy', lambda *args, **kwargs: {'script': 'Texte simulé'})
    assert client.post(url + '/message', json=options).json()['script'] == 'Texte simulé'
    previous_flyer = output.content
    options.update(mode='ai', format='square', mood='lumineuse', use_previous_flyer=True)
    path = f'{url}/{identifier}'
    assert client.post(path, json=options).status_code == 202
    wait(client, identifier)
    assert calls[0][0].endswith('/edits')
    assert calls[0][1]['files'][0][1][1] == media.validate(png())[1]
    assert calls[0][1]['files'][-1] == ('image[]', ('flyer-precedent.png', previous_flyer, 'image/png'))
    assert 'Ne reproduis aucun texte' in calls[0][1]['data']['prompt']
    previous_png = client.get(wait(client, identifier)['png']).content
    options.update(display_name='Atelier Alpha')
    assert client.post(path, json=options).status_code == 202
    renamed = wait(client, identifier)
    assert renamed['options']['display_name'] == 'Atelier Alpha'
    assert client.get(renamed['png']).content != previous_png
    assert len(calls) == 1
    options.update(message='Autre message', position='top')
    assert client.post(path, json=options).status_code == 202
    project = wait(client, identifier)
    assert len(calls) == 1
    assert len(project['jobs']) == 4
    previous_flyer = client.get(project['png']).content
    instruction = 'Privilégier un cadrage serré sur le produit.'
    options['operator_instruction'] = instruction
    assert client.post(path, json=options).status_code == 202
    project = wait(client, identifier)
    assert project['options']['operator_instruction'] == instruction
    assert len(calls) == 2
    assert instruction in calls[1][1]['data']['prompt']
    assert calls[1][1]['files'][0][1] == ('fond-precedent.png', png('blue'), 'image/png')
    assert calls[1][1]['files'][-1][1][1] == previous_flyer
    options['operator_instruction'] = '  ' + instruction + '  '
    assert client.post(path, json=options).json()['job_id'] == project['jobs'][0]['id']
    assert len(calls) == 2
    for style in ('flyer', 'poster'):
        options['image_style'] = style
        assert client.post(path, json=options).status_code == 202
        project = wait(client, identifier)
        assert project['options']['image_style'] == style
        label, direction = image_ads.IMAGE_STYLES[style]
        assert label in calls[-1][1]['data']['prompt']
        assert direction in calls[-1][1]['data']['prompt']
    assert len(calls) == 3
    assert client.post(path, json={**options, 'image_style': 'unknown'}).status_code == 422
    assert 'style visuel' not in calls[-1][1]['data']['prompt']
    options['visual_style'] = 'minimalist'
    options.pop('position')
    assert client.post(path, json=options).status_code == 202
    project = wait(client, identifier)
    assert project['options']['visual_style'] == 'minimalist'
    assert project['options']['position'] == 'top'
    label, direction = image_ads.VISUAL_STYLES['minimalist']
    assert label in calls[-1][1]['data']['prompt']
    assert direction in calls[-1][1]['data']['prompt']
    assert len(calls) == 4
    with sessions() as db:
        jobs = activity_feed(db)
        assert all(job['result_url'].endswith(identifier) for job in jobs if job['kind'] == 'image_render')
        assert any(job['kind'] == 'image_copy' and job['status'] == 'completed' for job in jobs)
        row = db.get(ImageAd, identifier)
        assert row.background != row.png


def test_restart_history_and_retry(studio):
    client, sessions = studio
    photo = upload(client).json()['id']
    options = {'mode': 'photo', 'format': 'square', 'message': 'Une annonce', 'media_ids': [photo]}
    url = '/api/leads/1/image-ads'
    identifier = client.post(url, json=options).json()['id']
    wait(client, identifier)
    with sessions() as db:
        interrupted = start_task(db, 'image_render', 1, identifier, 'Composition')
        db.commit()
        interrupted_id = interrupted.id
    assert client.post(f'{url}/{identifier}', json=options).status_code == 409
    image_ads.recover_image_jobs()
    failed = wait(client, identifier, 'failed')['jobs'][0]
    assert failed['id'] == interrupted_id
    assert 'redémarrage' in failed['error']
    assert client.post(f'{url}/{identifier}', json=options).status_code == 202
    assert len(wait(client, identifier)['jobs']) == 3


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg indisponible')
def test_audio_roles_and_real_video_frames(studio, tmp_path):
    client, _ = studio
    voice = tmp_path / 'voice.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                    str(voice)], check=True)
    audio = upload(client, data=voice.read_bytes(), name='voice.wav').json()
    assert audio['mime'] == 'audio/wav'
    mixed = client.post('/api/mix', json={'lead_id': 1, 'voice_media_id': audio['id']})
    assert mixed.status_code == 200
    saved = client.post('/api/ads/audio', json={'lead_id': 1, 'script': 'Voix réelle',
        'media': {'voice': audio['id']}, 'audio': base64.b64encode(mixed.content).decode()})
    assert saved.json()['media']['voice'] == audio['id']
    clip = tmp_path / 'motion.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x160:rate=30:duration=1',
                    '-threads', '1', '-c:v', 'libx264', str(clip)], check=True)
    row = upload(client, data=clip.read_bytes(), name='motion.mp4').json()
    assert row['mime'] == 'video/mp4'
    assert client.get(row['url']).content == clip.read_bytes()
    for layer in ('copy', 'chrome', 'background'):
        Image.new('RGBA', (160, 160)).save(tmp_path / f'{layer}-0.png')
    encode_video(tmp_path, voice, [{'duration': 2}], 2, lambda _: None,
                 scene_media={0: {'video': clip}})
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(tmp_path / 'spot.mp4'),
                             '-an', '-f', 'framemd5', '-'], capture_output=True, check=True)
    frames = [row.split(b',')[-1] for row in result.stdout.splitlines() if not row.startswith(b'#')]
    assert len(set(frames)) > 20


def test_google_photo_import_preserves_attribution(studio, monkeypatch):
    from contextlib import contextmanager

    client, _ = studio

    @contextmanager
    def photo_stream(method, url, **kwargs):
        assert method == 'GET' and url == 'https://lh3.googleusercontent.com/photo'
        assert not kwargs['follow_redirects']
        yield SimpleNamespace(raise_for_status=lambda: None, iter_bytes=lambda: [png()])

    monkeypatch.setattr(media.httpx, 'stream', photo_stream)
    assert client.post('/api/leads/2/media/google/0').status_code == 404
    imported = client.post('/api/leads/1/media/google/0')
    assert imported.status_code == 201
    assert imported.json()['source'] == 'google'
    assert imported.json()['attribution'] == 'Photographe'


def test_site_identity_extracts_declared_colors(monkeypatch):
    from app import website_identity

    monkeypatch.setattr(website_identity, 'public_homepage', lambda url:
        '<meta name="theme-color" content="#123456"><style>body {color:#abcdef}</style>')
    assert website_identity.homepage_identity('https://example.test')['palette'] == {
        'theme': '#123456', 'color_1': '#abcdef'}


def test_project_gallery_lists_each_render_for_the_selected_prospect(studio):
    client, sessions = studio
    with sessions() as db:
        db.add_all([
            ImageAd(id='a'*32, lead_id=1, options_json='{}', png=png('red')),
            ImageAd(id='b'*32, lead_id=1, options_json='{}', png=png('blue')),
            ImageAd(id='c'*32, lead_id=1, options_json='{}'),
            ImageAd(id='d'*32, lead_id=2, options_json='{}', png=png('green')),
        ])
        db.commit()

    projects = {project['id']: project['png']
                for project in client.get('/api/leads/1/image-ads').json()['projects']}
    assert set(projects) == {'a'*32, 'b'*32, 'c'*32}
    assert projects['c'*32] is None
    assert client.get(projects['a'*32]).content == png('red')
    assert client.get(projects['b'*32]).content == png('blue')



def test_flyer_without_slogan_and_automatic_slogan_placement(studio):
    client, sessions = studio
    with sessions() as db:
        lead = db.get(Lead, 1)
        lead.business_type = 'restaurant'
        lead.phone = '+590 590 00 00 00'
        lead.address = '12 rue des Lilas'
        db.commit()

    photo = upload(client).json()['id']
    path = '/api/leads/1/image-ads'
    response = client.post(path, json={'mode': 'photo', 'format': 'square', 'media_ids': [photo]})
    assert response.status_code == 202
    project = wait(client, response.json()['id'])
    options = project['options']
    assert options['display_name'] == 'Alpha'
    assert options['message'] == ''
    assert options['business'] == {'activity': 'Restaurant', 'phone': '+590 590 00 00 00',
                                    'address': '12 rue des Lilas', 'website': ''}
    size = (1080, 1080)
    background = png('tomato', size)
    plain = Image.open(io.BytesIO(image_ads.compose(background, None, options)))
    slogan = {**options, 'message': 'À découvrir', 'operator_instruction': 'Accroche : en haut.'}
    top = Image.open(io.BytesIO(image_ads.compose(background, None, slogan)))
    bottom = Image.open(io.BytesIO(image_ads.compose(background, None, {**slogan, 'position': 'bottom'})))
    top_region = ImageChops.difference(plain, top).getbbox()
    bottom_region = ImageChops.difference(plain, bottom).getbbox()
    assert top_region[3] < bottom_region[1]
    styled = Image.open(io.BytesIO(image_ads.compose(background, None, {**slogan, 'visual_style': 'editorial'})))
    assert ImageChops.difference(top, styled).getbbox()



def test_flyer_contact_overrides_can_be_saved_empty_without_editing_lead(studio):
    client, sessions = studio
    with sessions() as db:
        lead = db.get(Lead, 1)
        lead.business_type = 'restaurant'
        lead.phone = '01 00 00 00 00'
        lead.address = 'Adresse originale'
        lead.website = 'https://example.test/'
        db.commit()

    photo = upload(client).json()['id']
    options = {'mode': 'photo', 'format': 'square', 'media_ids': [photo],
               'display_name': '', 'activity': '  Table   locale ', 'phone': '   ',
               'address': 'Nouvelle adresse', 'website': ''}
    response = client.post('/api/leads/1/image-ads', json=options)
    assert response.status_code == 202
    project = wait(client, response.json()['id'])
    assert project['options']['display_name'] == ''
    assert project['options']['business'] == {'activity': 'Table locale', 'phone': '',
                                              'address': 'Nouvelle adresse', 'website': ''}
    assert client.get(project['png']).status_code == 200
    original = client.get('/api/leads/1/image-ads').json()
    assert original['name'] == 'Alpha'
    assert original['business'] == {'activity': 'Restaurant', 'phone': '01 00 00 00 00',
                                    'address': 'Adresse originale', 'website': 'example.test'}



def test_image_preview_versions_restore_and_variant(studio, monkeypatch):
    client, _ = studio
    calls = []

    def fake_background(prompt, format_name, refs, **references):
        calls.append(references)
        return png('blue' if len(calls) == 1 else 'green')

    monkeypatch.setattr(image_ads, 'generate_background', fake_background)
    url = '/api/leads/1/image-ads'
    options = {'mode': 'ai', 'format': 'square', 'action': 'ai'}
    identifier = client.post(url, json=options).json()['id']
    first = wait(client, identifier)
    path = f'{url}/{identifier}'
    version = first['versions'][0]
    original = client.get(version['png']).content
    options.update(action='local', layout='promotion', message='Offre du jour')
    preview = client.post(path + '/preview', json=options)
    assert preview.status_code == 200 and preview.content != original
    assert len(client.get(path).json()['versions']) == 1
    assert client.post(path, json=options).status_code == 202
    revised = wait(client, identifier)
    assert len(revised['versions']) == 2
    assert client.get(revised['png']).content == preview.content
    assert len(calls) == 1
    assert client.get(version['png'].replace('/1/', '/2/')).status_code == 404

    restore = path + '/versions/' + str(version['id']) + '/restore'
    assert client.post(restore).status_code == 200
    restored = client.get(path).json()
    assert len(restored['versions']) == 3
    assert client.get(restored['png']).content == original
    assert len(calls) == 1

    options.update(action='variant')
    variant_id = client.post(path, json=options).json()['id']
    assert variant_id != identifier
    variant = wait(client, variant_id)
    assert client.get(variant['png']).content != original
    assert client.get(restored['png']).content == original
    assert calls[-1] == {'previous_background': png('blue'), 'previous_flyer': None}
