import csv,io,json,threading
from datetime import datetime,timedelta
from fastapi import FastAPI,Depends,Form,Request
from fastapi.responses import HTMLResponse,RedirectResponse,StreamingResponse,Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select,func,text
from sqlalchemy.orm import Session
from .db import Base,engine,SessionLocal,get_db
from .models import Job,Lead,JobLead
from .core import grid_points,normalize_phone,score
from .places import Places
from .communes import get_communes,get_departments,get_or_resolve_commune,initialize_communes,initialize_department,force_resolve_commune,commune_stats,add_department,delete_department

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
TYPE_CATEGORIES={
"Restauration & boissons":["restaurant","african_restaurant","caribbean_restaurant","french_restaurant","italian_restaurant","chinese_restaurant","indian_restaurant","japanese_restaurant","korean_restaurant","thai_restaurant","mexican_restaurant","mediterranean_restaurant","seafood_restaurant","pizza_restaurant","fast_food_restaurant","hamburger_restaurant","sandwich_shop","sushi_restaurant","steak_house","vegan_restaurant","vegetarian_restaurant","bakery","cafe","coffee_shop","bar","cocktail_bar","pub","sports_bar","wine_bar","juice_shop","ice_cream_shop","dessert_shop","meal_takeaway","meal_delivery"],
"Beauté & bien-être":["barber_shop","beautician","beauty_salon","hair_care","hair_salon","makeup_artist","nail_salon","massage","massage_spa","skin_care_clinic","spa","tanning_studio","wellness_center","yoga_studio"],
"Automobile & mobilité":["car_dealer","car_rental","car_repair","car_wash","tire_shop","truck_dealer","auto_parts_store","gas_station","electric_vehicle_charging_station"],
"Artisans & services":["electrician","plumber","painter","locksmith","roofing_contractor","moving_company","laundry","tailor","florist","courier_service","shipping_service","storage","consultant","marketing_consultant","employment_agency","insurance_agency","lawyer","accounting","telecommunications_service_provider","catering_service"],
"Commerce & boutiques":["store","general_store","convenience_store","grocery_store","supermarket","hypermarket","discount_store","food_store","butcher_shop","farmers_market","market","clothing_store","womens_clothing_store","shoe_store","jewelry_store","cosmetics_store","electronics_store","cell_phone_store","furniture_store","home_goods_store","home_improvement_store","hardware_store","building_materials_store","garden_center","gift_shop","book_store","toy_store","pet_store","bicycle_store","sporting_goods_store","sportswear_store","thrift_store","wholesaler"],
"Santé":["doctor","dentist","dental_clinic","medical_clinic","medical_center","medical_lab","hospital","general_hospital","pharmacy","drugstore","physiotherapist","chiropractor","veterinary_care","foot_care"],
"Sport & loisirs":["gym","fitness_center","sports_club","sports_coaching","sports_complex","sports_school","swimming_pool","tennis_court","golf_course","dance_hall","bowling_alley","amusement_center","amusement_park","indoor_playground","video_arcade","paintball_center","go_karting_venue"],
"Événementiel & tourisme":["event_venue","wedding_venue","banquet_hall","night_club","live_music_venue","concert_hall","convention_center","tour_agency","travel_agency","tourist_information_center","tourist_attraction","visitor_center","marina"],
"Hébergement":["hotel","resort_hotel","motel","hostel","guest_house","bed_and_breakfast","lodging","inn","cottage","campground","camping_cabin","farmstay"],
"Immobilier & habitat":["real_estate_agency","apartment_building","apartment_complex","condominium_complex","housing_complex"],
"Entreprises & professionnels":["business_center","corporate_office","coworking_space","farm","manufacturer","supplier","association_or_organization","non_profit_organization"],
"Éducation":["preschool","primary_school","secondary_school","school","university","educational_institution","research_institute","library"],
"Culture":["art_gallery","art_museum","art_studio","museum","performing_arts_theater","cultural_center","historical_place","historical_landmark"],
"Transport":["taxi_service","chauffeur_service","transportation_service","ferry_service","ferry_terminal","bus_station","train_station","airport","international_airport"]
}
TYPES=list(dict.fromkeys(t for values in TYPE_CATEGORIES.values() for t in values))

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
            if not phone: continue
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
    now=datetime.utcnow(); since_24h=now-timedelta(hours=24); since_7d=now-timedelta(days=7)
    total=db.scalar(select(func.count()).select_from(Lead)) or 0
    new_24h=db.scalar(select(func.count()).select_from(Lead).where(Lead.first_seen_at>=since_24h)) or 0
    new_7d=db.scalar(select(func.count()).select_from(Lead).where(Lead.first_seen_at>=since_7d)) or 0
    no_website=db.scalar(select(func.count()).select_from(Lead).where(Lead.website.is_(None))) or 0
    high_score=db.scalar(select(func.count()).select_from(Lead).where(Lead.score>=4)) or 0
    recent_leads=db.scalars(select(Lead).order_by(Lead.first_seen_at.desc()).limit(12)).all()
    top_leads=db.scalars(select(Lead).order_by(Lead.score.desc(),Lead.reviews_count.desc(),Lead.first_seen_at.desc()).limit(8)).all()
    recent_jobs=db.scalars(select(Job).order_by(Job.id.desc()).limit(8)).all()
    latest_job=recent_jobs[0] if recent_jobs else None
    return tpl.TemplateResponse(request,"index.html",{"leads":total,"new_24h":new_24h,"new_7d":new_7d,"no_website":no_website,"high_score":high_score,"jobs":db.scalar(select(func.count()).select_from(Job)) or 0,"recent":recent_jobs,"recent_leads":recent_leads,"top_leads":top_leads,"latest_job":latest_job})

@app.get("/search",response_class=HTMLResponse)
def search_page(request:Request,db:Session=Depends(get_db)): return tpl.TemplateResponse(request,"search.html",{"types":TYPES,"type_categories":TYPE_CATEGORIES,"communes":get_communes(),"previous":db.scalars(select(Job).order_by(Job.id.desc()).limit(20)).all()})

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

@app.get("/jobs/{job_id}",response_class=HTMLResponse)
def job_detail(job_id:int,request:Request,db:Session=Depends(get_db)):
    job=db.get(Job,job_id)
    if not job: return RedirectResponse("/jobs",303)
    try: business_types=json.loads(job.types or "[]")
    except (TypeError,json.JSONDecodeError): business_types=[]
    leads=db.scalars(select(Lead).join(JobLead,JobLead.lead_id==Lead.id).where(JobLead.job_id==job_id).order_by(Lead.score.desc(),Lead.id.desc())).all()
    progress=None
    if job.status=="completed": progress=100
    elif job.error and job.error.startswith("PROGRESS:"):
        try:
            done,total=map(int,job.error.split(":",1)[1].split("/")); progress=round(done*100/total)
        except (ValueError,ZeroDivisionError): pass
    duration=None
    if job.started_at:
        end=job.finished_at or datetime.utcnow()
        duration=max(0,round((end-job.started_at).total_seconds()))
    return tpl.TemplateResponse(request,"job_detail.html",{"job":job,"leads":leads,"business_types":business_types,"progress":progress,"duration":duration})

@app.get("/ops",response_class=HTMLResponse)
def ops(request:Request,db:Session=Depends(get_db)):
    rows=db.scalars(select(Job).order_by(Job.id.desc()).limit(100)).all()
    now=datetime.utcnow()
    running=sum(1 for x in rows if x.status=="running")
    failed=sum(1 for x in rows if x.status=="failed")
    completed=sum(1 for x in rows if x.status=="completed")
    return tpl.TemplateResponse(request,"ops.html",{"rows":rows,"running":running,"failed":failed,"completed":completed,"now":now,"communes":get_communes(),"departments":get_departments(),"commune_stats":commune_stats()})

@app.post("/ops/departments")
def ops_add_department(department_code:str=Form(...)):
    try:
        dep=add_department(department_code)
        threading.Thread(target=initialize_department,args=(dep["code"],),daemon=True,name=f'department-init-{dep["code"]}').start()
    except Exception: pass
    return RedirectResponse("/ops#communes",303)

@app.post("/ops/departments/{department_code}/delete")
def ops_delete_department(department_code:str):
    try: delete_department(department_code)
    except Exception: pass
    return RedirectResponse("/ops#communes",303)

@app.post("/ops/database/clear-prospects")
def ops_clear_prospects(db:Session=Depends(get_db)):
    db.query(JobLead).delete(synchronize_session=False)
    db.query(Lead).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse("/ops#database",303)

@app.post("/ops/database/clear-jobs")
def ops_clear_jobs(db:Session=Depends(get_db)):
    db.query(JobLead).delete(synchronize_session=False)
    db.query(Job).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse("/ops#database",303)

@app.post("/ops/database/clear-all")
def ops_clear_all(db:Session=Depends(get_db)):
    db.query(JobLead).delete(synchronize_session=False)
    db.query(Lead).delete(synchronize_session=False)
    db.query(Job).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse("/ops#database",303)

@app.post("/ops/departments/{department_code}/initialize")
def ops_initialize_department(department_code:str):
    threading.Thread(target=initialize_department,args=(department_code,),daemon=True,name=f'department-init-{department_code}').start()
    return RedirectResponse("/ops#communes",303)

@app.post("/ops/departments/{department_code}/communes/{code}/sync")
def ops_sync_commune(department_code:str,code:str):
    try: force_resolve_commune(code,department_code)
    except Exception: pass
    return RedirectResponse("/ops#communes",303)

@app.get("/api/ops/communes")
def api_ops_communes():
    return {"stats":commune_stats(),"departments":get_departments()}

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
    photos=[]
    try: photos=Places().photos(lead.place_id,10)
    except Exception: pass
    return tpl.TemplateResponse(request,"lead_detail.html",{"lead":lead,"jobs":jobs,"photos":photos})

@app.get("/api/leads/{lead_id}/photos")
def api_lead_photos(lead_id:int,db:Session=Depends(get_db)):
    lead=db.get(Lead,lead_id)
    if not lead: return {"photos":[]}
    try:
        photos=Places().photos(lead.place_id,10)
        return {"photos":[{"url":f"/api/leads/{lead_id}/photos/{i}","width":p.get("widthPx"),"height":p.get("heightPx"),"attributions":p.get("authorAttributions",[])} for i,p in enumerate(photos)]}
    except Exception as exc: return {"photos":[],"error":str(exc)}

@app.get("/api/leads/{lead_id}/photos/{index}")
def lead_photo(lead_id:int,index:int,db:Session=Depends(get_db)):
    lead=db.get(Lead,lead_id)
    if not lead: return Response(status_code=404)
    try:
        photos=Places().photos(lead.place_id,10)
        if index<0 or index>=len(photos): return Response(status_code=404)
        uri=Places().photo_media(photos[index]["name"],800,800)
        return RedirectResponse(uri)
    except Exception: return Response(status_code=404)

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
