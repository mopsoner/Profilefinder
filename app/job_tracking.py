"""Shared job tracking and activity feed for acquisition and creative studios."""
from datetime import datetime
from sqlalchemy import select
from .models import Job, Lead, VideoAd, AudioAd

KINDS = {'search':'Recherche Google Places','site_ai':'Création de site IA',
         'audio_copy':'Texte publicitaire IA','audio_voice':'Voix off IA','audio_mix':'Mixage audio',
         'video_prepare':'Préparation des plans','video_preview':'Actualisation des plans',
         'video_render':'Export vidéo MP4','audio_saved':'Audio enregistré'}
STATUSES = {'queued':'En attente','running':'En cours','completed':'Terminé','failed':'En erreur','ready':'Plans prêts'}
ACTIVE = ('queued','running')


def start_task(db, kind, lead_id=None, resource_id=None, stage=None):
    lead = db.get(Lead, lead_id) if type(lead_id) is int else None
    row = Job(kind=kind, lead_id=lead.id if lead else None, resource_id=resource_id,
              city=lead.name if lead else 'Studio Ads', latitude=0, longitude=0, radius=0,
              types='[]', max_results=0, rings=0, status='running',
              started_at=datetime.utcnow(), stage=stage)
    db.add(row)
    db.flush()
    return row


def finish_task(row, error=None):
    row.status='failed' if error else 'completed'
    row.error=error
    row.finished_at=datetime.utcnow()
    if not error: row.stage='Terminé'


def job_payload(row, leads=None):
    lead=(leads or {}).get(row.lead_id)
    kind=row.kind or 'search'
    progress=100 if row.status=='completed' else None
    error=row.error
    if (error or '').startswith('PROGRESS:'):
        try:
            done,total=map(int,error.split(':',1)[1].split('/'))
            progress=max(0,min(100,round(done*100/total)))
        except (ValueError,ZeroDivisionError): pass
        error=None
    result_url=None
    if lead:
        if kind=='site_ai': result_url=f'/leads/{lead.id}/web'
        elif kind.startswith('video_') and row.resource_id: result_url=f'/leads/{lead.id}/video-ads?project_id={row.resource_id}'
        elif kind.startswith('audio_'): result_url=f'/ads?lead_id={lead.id}'
    fallback={'search':'Recherche Google Places','site_ai':'Génération du site et de ses images','audio_voice':'Synthèse de la voix off','audio_mix':'Mixage FFmpeg'}
    return {'id':row.id,'kind':kind,'kind_label':KINDS.get(kind,kind),'city':lead.name if lead else row.city,
            'lead_id':lead.id if lead else None,'lead_url':f'/leads/{lead.id}' if lead else None,
            'status':row.status,'status_label':STATUSES.get(row.status,row.status),'progress':progress,
            'stage':'Terminé' if row.status=='completed' else row.stage or (fallback.get(kind,'Traitement en cours') if row.status in ACTIVE else ''),
            'total_found':row.total_found if kind=='search' else None,'total_filtered':row.total_filtered if kind=='search' else None,
            'error':error,'created_at':row.created_at.isoformat() if row.created_at else None,
            'started_at':row.started_at.isoformat() if row.started_at else None,
            'finished_at':row.finished_at.isoformat() if row.finished_at else None,
            'url':f'/jobs/{row.id}','result_url':result_url,'resource_id':row.resource_id}


def activity_feed(db):
    leads={lead.id:lead for lead in db.execute(select(Lead.id,Lead.name)).all()}
    jobs=db.scalars(select(Job)).all()
    rows=[job_payload(row,leads) for row in jobs]
    tracked={row.resource_id for row in jobs if row.resource_id}
    # Legacy projects and saved audio remain visible without inventing execution timings.
    for video in db.execute(select(VideoAd.id,VideoAd.lead_id,VideoAd.status,VideoAd.progress,VideoAd.error,VideoAd.created_at)).all():
        if video.id in tracked: continue
        lead=leads.get(video.lead_id)
        status={'preparing':'running','rendering':'running'}.get(video.status,video.status)
        kind='video_render' if video.status in ('rendering','completed') else 'video_prepare'
        rows.append({'id':'video-'+video.id[:8],'kind':kind,'kind_label':KINDS[kind],
                     'city':lead.name if lead else 'Prospect supprimé','lead_id':lead.id if lead else None,
                     'lead_url':f'/leads/{lead.id}' if lead else None,'status':status,'status_label':STATUSES.get(status,status),
                     'progress':video.progress,'stage':'Projet vidéo existant','error':video.error,
                     'created_at':video.created_at.isoformat(),'started_at':None,'finished_at':None,
                     'total_found':None,'total_filtered':None,'url':f'/leads/{video.lead_id}/video-ads?project_id={video.id}',
                     'result_url':None,'resource_id':video.id})
    for audio in db.execute(select(AudioAd.id,AudioAd.lead_id,AudioAd.created_at)).all():
        lead=leads.get(audio.lead_id)
        rows.append({'id':'audio-'+audio.id[:8],'kind':'audio_saved','kind_label':KINDS['audio_saved'],
                     'city':lead.name if lead else 'Prospect supprimé','lead_id':lead.id if lead else None,
                     'lead_url':f'/leads/{lead.id}' if lead else None,'status':'completed','status_label':'Enregistré',
                     'progress':100,'stage':'Audio et message sauvegardés','error':None,
                     'created_at':audio.created_at.isoformat(),'started_at':None,'finished_at':None,
                     'total_found':None,'total_filtered':None,'url':f'/leads/{audio.lead_id}/video-ads?audio_id={audio.id}',
                     'result_url':None,'resource_id':audio.id})
    return sorted(rows,key=lambda row:row['created_at'] or '',reverse=True)
