import csv,io,json,threading
from datetime import datetime
from fastapi import FastAPI,Depends,Form,Request
from fastapi.responses import HTMLResponse,RedirectResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select,func,text
from sqlalchemy.orm import Session
from .db import Base,engine,SessionLocal,get_db
from .models import Job,Lead,JobLead
from .core import grid_points,normalize_phone,score
from .places import Places
from .communes import get_communes,get_or_resolve_commune,initialize_communes

Base.metadata.create_all(engine)
# Lightweight SQLite migration for search parameters added after V1.
with engine.begin() as conn:
    if engine.dialect.name=="sqlite":
        cols={row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if "max_results" not in cols: conn.execute(text("ALTER TABLE jobs ADD COLUMN max_results INTEGER DEFAULT 20"))
        if "rings" not in cols: conn.execute(text("ALTER TABLE jobs ADD COLUMN rings INTEGER DEFAULT 1"))
app=FastAPI(title="ProfileFinder",version="1.0.0")

@app.on_event("startup")
def startup_initialize_reference_data():
    # Do not block the web server while Google resolves missing communes.
    threading.Thread(target=initialize_communes,daemon=True,name="commune-init").start()
app.mount("/static",StaticFiles(directory="app/static"),name="static")
tpl=Jinja2Templates(directory="app/templates")
TYPES=["restaurant","bar","bakery","meal_takeaway","beauty_salon","hair_care","laundry","car_repair","car_wash","plumber","electrician","painter","locksmith","moving_company","home_goods_store","furniture_store","hardware_store","florist","pet_store","veterinary_care","gym","spa","real_estate_agency","clothing_store","shoe_store","jewelry_store","electronics_store","convenience_store"]

def worker(jid,types,max_results,rings):
    db=SessionLocal(); job=db.get(Job,jid)
    try:
        job.status="running"; job.started_at=datetime.utcnow(); db.commit()
        seen={}; client=Places()
        points=grid_points(job.latitude,job.longitude,job.radius,rings)
        total_calls=max(1,len(points)*len(types)); completed_calls=0
        for lat,lng in points:
            for typ in types:
                for place in client.nearby(lat,lng,job.radius,typ,max_results):
                    if place.get("id"): seen[place["id"]]=(place,typ)
                completed_calls += 1
                job.total_found=len(seen)
                job.error=f"PROGRESS:{completed_calls}/{total_calls}"
                db.commit()
        job.total_found=len(seen)
        for pid,(place,typ) in seen.items():
            phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber")
            website=place.get("websiteUri")
            if website or not phone: continue
            digits=normalize_phone(phone)
            if not digits: continue
            lead=db.scalar(select(Lead).where(Lead.place_id==pid)); loc=place.get("location",{})
            values=dict(name=place.get("displayName",{}).get("text","Unnamed"),business_type=typ,city=job.city,address=place.get("formattedAddress"),phone=phone,phone_digits=digits,whatsapp_url="https://wa.me/"+digits,website=website,reviews_count=place.get("userRatingCount") or 0,rating=place.get("rating"),latitude=loc.get("latitude"),longitude=loc.get("longitude"),score=score(place.get("userRatingCount") or 0,website,phone),updated_at=datetime.utcnow())
            if lead:
                for key,value in values.items(): setattr(lead,key,value)
            else:
                lead=Lead(place_id=pid,**values); db.add(lead); db.flush()
            if not db.scalar(select(JobLead).where(JobLead.job_id==jid,JobLead.lead_id==lead.id)):
                db.add(JobLead(job_id=jid,lead_id=lead.id))
        db.flush()
        job.total_filtered=db.scalar(select(func.count()).select_from(JobLead).where(JobLead.job_id==jid))
        job.status="completed"; job.error=None; job.finished_at=datetime.utcnow(); db.commit()
    except Exception as exc:
        job.status="failed"; job.error=str(exc); job.finished_at=datetime.utcnow(); db.commit()
    finally: db.close()

@app.get("/",response_class=HTMLResponse)
def home(request:Request,db:Session=Depends(get_db)):
    return tpl.TemplateResponse(request,"index.html",{"leads":db.scalar(select(func.count()).select_from(Lead)) or 0,"jobs":db.scalar(select(func.count()).select_from(Job)) or 0,"recent":db.scalars(select(Job).order_by(Job.id.desc()).limit(8)).all()})

@app.get("/search",response_class=HTMLResponse)
def search_page(request:Request,db:Session=Depends(get_db)): return tpl.TemplateResponse(request,"search.html",{"types":TYPES,"communes":get_communes(),"previous":db.scalars(select(Job).order_by(Job.id.desc()).limit(20)).all()})

@app.get("/api/communes/{code}/resolve")
def api_resolve_commune(code:str):
    try:
        return {"ok":True,"commune":get_or_resolve_commune(code)}
    except Exception as exc:
        return {"ok":False,"error":str(exc)}

@app.post("/search")
def search(city:str=Form(...),latitude:float=Form(...),longitude:float=Form(...),radius:int=Form(1000),business_types:list[str]=Form(...),max_results:int=Form(20),rings:int=Form(1),db:Session=Depends(get_db)):
    job=Job(city=city,latitude=latitude,longitude=longitude,radius=radius,types=json.dumps(business_types),max_results=max_results,rings=rings); db.add(job); db.commit(); db.refresh(job)
    threading.Thread(target=worker,args=(job.id,business_types,max_results,rings),daemon=True).start()
    return RedirectResponse("/jobs",303)

@app.post("/search/rerun/{job_id}")
def rerun_search(job_id:int,db:Session=Depends(get_db)):
    source=db.get(Job,job_id)
    if not source: return RedirectResponse("/search",303)
    try: business_types=json.loads(source.types)
    except (TypeError,json.JSONDecodeError): business_types=[]
    max_results=source.max_results or 20
    rings=source.rings if source.rings is not None else 1
    job=Job(city=source.city,latitude=source.latitude,longitude=source.longitude,radius=source.radius,types=source.types,max_results=max_results,rings=rings)
    db.add(job); db.commit(); db.refresh(job)
    threading.Thread(target=worker,args=(job.id,business_types,max_results,rings),daemon=True).start()
    return RedirectResponse("/ops",303)

@app.get("/jobs",response_class=HTMLResponse)
def jobs(request:Request,db:Session=Depends(get_db)): return tpl.TemplateResponse(request,"jobs.html",{"jobs":db.scalars(select(Job).order_by(Job.id.desc())).all()})

@app.get("/ops",response_class=HTMLResponse)
def ops(request:Request,db:Session=Depends(get_db)):
    rows=db.scalars(select(Job).order_by(Job.id.desc()).limit(100)).all()
    now=datetime.utcnow()
    running=sum(1 for x in rows if x.status=="running")
    failed=sum(1 for x in rows if x.status=="failed")
    completed=sum(1 for x in rows if x.status=="completed")
    return tpl.TemplateResponse(request,"ops.html",{"rows":rows,"running":running,"failed":failed,"completed":completed,"now":now})

@app.get("/api/ops/logs")
def api_ops_logs():
    from pathlib import Path
    path=Path("data/logs/places.log")
    if not path.exists(): return {"lines":[]}
    return {"lines":path.read_text(encoding="utf-8",errors="replace").splitlines()[-200:]}

@app.get("/api/ops")
def api_ops(db:Session=Depends(get_db)):
    rows=db.scalars(select(Job).order_by(Job.id.desc()).limit(100)).all()
    def payload(x):
        progress=None
        if x.status=="completed": progress=100
        elif x.error and x.error.startswith("PROGRESS:"):
            try:
                done,total=map(int,x.error.split(":",1)[1].split("/")); progress=round(done*100/total)
            except (ValueError,ZeroDivisionError): pass
        return {"id":x.id,"city":x.city,"status":x.status,"progress":progress,"total_found":x.total_found,"total_filtered":x.total_filtered,"error":None if (x.error or "").startswith("PROGRESS:") else x.error,"created_at":x.created_at.isoformat() if x.created_at else None,"started_at":x.started_at.isoformat() if x.started_at else None,"finished_at":x.finished_at.isoformat() if x.finished_at else None}
    return [payload(x) for x in rows]

@app.get("/leads",response_class=HTMLResponse)
def leads(request:Request,q:str="",min_score:int=0,db:Session=Depends(get_db)):
    rows=db.scalars(select(Lead).where(Lead.score>=min_score).order_by(Lead.score.desc(),Lead.id.desc())).all(); q=q.lower().strip()
    rows=[x for x in rows if not q or q in x.name.lower() or q in (x.address or "").lower()]
    return tpl.TemplateResponse(request,"leads.html",{"rows":rows,"q":q,"min_score":min_score})

@app.get("/leads/{lead_id}",response_class=HTMLResponse)
def lead_detail(lead_id:int,request:Request,db:Session=Depends(get_db)):
    lead=db.get(Lead,lead_id)
    if not lead: return RedirectResponse("/leads",303)
    jobs=db.scalars(select(Job).join(JobLead,JobLead.job_id==Job.id).where(JobLead.lead_id==lead_id).order_by(Job.id.desc())).all()
    return tpl.TemplateResponse(request,"lead_detail.html",{"lead":lead,"jobs":jobs})

@app.get("/export.csv")
def export(db:Session=Depends(get_db)):
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(["name","type","city","address","phone","whatsapp","rating","reviews","score"])
    for x in db.scalars(select(Lead).order_by(Lead.score.desc())).all(): writer.writerow([x.name,x.business_type,x.city,x.address,x.phone,x.whatsapp_url,x.rating,x.reviews_count,x.score])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=profilefinder-leads.csv"})

@app.get("/api/stats")
def stats(db:Session=Depends(get_db)): return {"leads":db.scalar(select(func.count()).select_from(Lead)) or 0,"jobs":db.scalar(select(func.count()).select_from(Job)) or 0}
@app.get("/api/jobs")
def api_jobs(db:Session=Depends(get_db)): return [{"id":x.id,"city":x.city,"status":x.status,"total_found":x.total_found,"total_filtered":x.total_filtered,"error":x.error} for x in db.scalars(select(Job).order_by(Job.id.desc())).all()]
@app.get("/api/jobs/{job_id}")
def api_job(job_id:int,db:Session=Depends(get_db)):
    x=db.get(Job,job_id); return {"id":x.id,"city":x.city,"status":x.status,"total_found":x.total_found,"total_filtered":x.total_filtered,"error":x.error} if x else {"error":"not found"}
@app.get("/api/leads")
def api_leads(db:Session=Depends(get_db)): return [{"id":x.id,"place_id":x.place_id,"name":x.name,"phone":x.phone,"whatsapp_url":x.whatsapp_url,"score":x.score,"reviews_count":x.reviews_count,"rating":x.rating} for x in db.scalars(select(Lead).order_by(Lead.score.desc())).all()]
