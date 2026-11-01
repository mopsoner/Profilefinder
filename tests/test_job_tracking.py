import json
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Lead, Job, VideoAd, AudioAd
from app.job_tracking import activity_feed, start_task, finish_task, job_payload
from app import ads, video_ads


@pytest.fixture
def sessions(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'jobs.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    monkeypatch.setattr(ads,'SessionLocal',factory)
    monkeypatch.setattr(video_ads,'SessionLocal',factory)
    with factory() as db:
        db.add(Lead(id=1,name='<script>Entreprise</script>',place_id='test'))
        db.add(AudioAd(id='a'*32,lead_id=1,script='Une voix off',duration=3))
        db.add(VideoAd(id='b'*32,lead_id=1,audio_id='a'*32,site_json='{}',status='ready',progress=100))
        db.commit()
    yield factory
    engine.dispose()


def test_feed_includes_legacy_media_and_preserves_search_results(sessions):
    with sessions() as db:
        search=Job(city='Paris',latitude=0,longitude=0,radius=1000,types='[]',status='running',error='PROGRESS:1/4',total_found=20,total_filtered=4)
        db.add(search);db.commit()
        rows=activity_feed(db)
        assert {row['kind'] for row in rows}=={'search','video_prepare','audio_saved'}
        task=next(row for row in rows if row['kind']=='search')
        assert task['progress']==25 and task['error'] is None
        assert task['total_found']==20 and task['total_filtered']==4
        video=next(row for row in rows if row['kind']=='video_prepare')
        assert video['status']=='ready' and 'project_id=' in video['url']
        assert video['started_at'] is None and video['finished_at'] is None


def test_video_tracking_keeps_each_run_and_avoids_legacy_duplicate(sessions):
    with sessions() as db:
        task=start_task(db,'video_prepare',1,'b'*32,'Plans IA');db.commit();first=task.id
    video_ads.update('b'*32,progress=45,stage='Création des visuels IA')
    with sessions() as db:
        task=db.get(Job,first)
        payload=job_payload(task,{1:db.get(Lead,1)})
        assert payload['progress']==45 and payload['stage']=='Création des visuels IA'
        assert payload['error'] is None and payload['total_found'] is None
    video_ads.update('b'*32,status='ready',progress=100)
    with sessions() as db:
        task=db.get(Job,first)
        assert task.status=='completed' and task.finished_at is not None
        rerun=start_task(db,'video_render',1,'b'*32,'Encodage MP4');db.commit();second=rerun.id
    video_ads.update('b'*32,status='failed',error='FFmpeg indisponible')
    with sessions() as db:
        assert db.get(Job,first).status=='completed'
        assert db.get(Job,second).error=='FFmpeg indisponible'
        rows=activity_feed(db)
        assert len([r for r in rows if r['kind'].startswith('video_')])==2
        assert all(r['result_url'].endswith('project_id='+'b'*32) for r in rows if r['kind'].startswith('video_'))


def test_audio_success_and_failure_persist_without_payload_or_credentials(sessions):
    with patch.object(ads,'synthesize',return_value=b'mp3'):
        response=ads.tracked_audio({'lead_id':1,'text':'Script privé','api_key':'secret'})
        assert response.body==b'mp3'
    with patch.object(ads,'mix_audio',side_effect=ValueError('Audio invalide')):
        with pytest.raises(ValueError):ads.tracked_audio({'lead_id':1},True)
    with sessions() as db:
        rows=activity_feed(db)
        voice=next(r for r in rows if r['kind']=='audio_voice')
        mix=next(r for r in rows if r['kind']=='audio_mix')
        assert voice['status']=='completed' and voice['lead_id']==1
        assert voice['finished_at'] and voice['progress']==100
        assert mix['status']=='failed' and mix['error']=='Audio invalide'
        assert 'Script privé' not in json.dumps(rows) and 'secret' not in json.dumps(rows)


def test_restart_marks_video_task_failed_without_touching_completed_history(sessions):
    with sessions() as db:
        task=start_task(db,'video_render',1,'b'*32);db.commit();identifier=task.id
        old=start_task(db,'video_prepare',1,'b'*32);finish_task(old);db.commit();old_id=old.id
        db.get(VideoAd,'b'*32).status='rendering';db.commit()
    video_ads.recover_interrupted_jobs()
    with sessions() as db:
        assert db.get(Job,identifier).status=='failed'
        assert db.get(Job,identifier).finished_at
        assert db.get(Job,old_id).status=='completed'
        assert db.get(VideoAd,'b'*32).status=='failed'
