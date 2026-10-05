import csv,io,json,threading,re
from concurrent.futures import ThreadPoolExecutor,as_completed
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
from .config import settings
from .communes import get_communes,get_departments,get_or_resolve_commune,initialize_communes,initialize_department,force_resolve_commune,commune_stats,add_department,delete_department

Base.metadata.create_all(engine)
# Lightweight SQLite migration for search parameters added after V1.
with engine.begin() as conn:
    if engine.dialect.name=="sqlite":
        cols={row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if "max_results" not in cols: conn.execute(text("ALTER TABLE jobs ADD COLUMN max_results INTEGER DEFAULT 20"))
        if "rings" not in cols: conn.execute(text("ALTER TABLE jobs ADD COLUMN rings INTEGER DEFAULT 1"))
        if "postal_codes" not in cols: conn.execute(text("ALTER TABLE jobs ADD COLUMN postal_codes TEXT"))
        lead_cols={row[1] for row in conn.execute(text("PRAGMA table_info(leads)"))}
        if "google_activity_at" not in lead_cols: conn.execute(text("ALTER TABLE leads ADD COLUMN google_activity_at DATETIME"))
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
TYPE_LABELS={
"restaurant":"Restaurant","caribbean_restaurant":"Restaurant caribéen","african_restaurant":"Restaurant africain","french_restaurant":"Restaurant français","italian_restaurant":"Restaurant italien","chinese_restaurant":"Restaurant chinois","indian_restaurant":"Restaurant indien","japanese_restaurant":"Restaurant japonais","korean_restaurant":"Restaurant coréen","thai_restaurant":"Restaurant thaïlandais","mexican_restaurant":"Restaurant mexicain","mediterranean_restaurant":"Restaurant méditerranéen","seafood_restaurant":"Restaurant de fruits de mer","pizza_restaurant":"Pizzeria","fast_food_restaurant":"Restauration rapide","hamburger_restaurant":"Restaurant de burgers","sandwich_shop":"Sandwicherie","sushi_restaurant":"Restaurant de sushis","steak_house":"Grill / Steakhouse","vegan_restaurant":"Restaurant végan","vegetarian_restaurant":"Restaurant végétarien","bakery":"Boulangerie","cafe":"Café","coffee_shop":"Coffee shop","bar":"Bar","cocktail_bar":"Bar à cocktails","pub":"Pub","sports_bar":"Bar sportif","wine_bar":"Bar à vin","juice_shop":"Bar à jus","ice_cream_shop":"Glacier","dessert_shop":"Pâtisserie / Desserts","meal_takeaway":"Plats à emporter","meal_delivery":"Livraison de repas",
"barber_shop":"Barbier / Coiffeur homme","beautician":"Esthéticien(ne)","beauty_salon":"Institut de beauté","hair_care":"Soins capillaires","hair_salon":"Salon de coiffure","makeup_artist":"Maquilleur / Maquilleuse","nail_salon":"Salon de manucure","massage":"Massage","massage_spa":"Spa / Massage","skin_care_clinic":"Centre de soins de la peau","spa":"Spa","tanning_studio":"Centre de bronzage","wellness_center":"Centre de bien-être","yoga_studio":"Studio de yoga",
"car_dealer":"Concessionnaire automobile","car_rental":"Location de voitures","car_repair":"Garage automobile","car_wash":"Lavage automobile","tire_shop":"Magasin de pneus","truck_dealer":"Concessionnaire poids lourds","auto_parts_store":"Magasin de pièces automobiles","gas_station":"Station-service","electric_vehicle_charging_station":"Borne de recharge électrique",
"electrician":"Électricien","plumber":"Plombier","painter":"Peintre","locksmith":"Serrurier","roofing_contractor":"Couvreur","moving_company":"Entreprise de déménagement","laundry":"Blanchisserie / Laverie","tailor":"Tailleur / Couturier","florist":"Fleuriste","courier_service":"Service de coursier","shipping_service":"Service d'expédition","storage":"Garde-meuble / Stockage","consultant":"Consultant","marketing_consultant":"Consultant marketing","employment_agency":"Agence d'emploi","insurance_agency":"Agence d'assurance","lawyer":"Avocat","accounting":"Comptable","telecommunications_service_provider":"Télécommunications","catering_service":"Traiteur",
"store":"Magasin","general_store":"Magasin général","convenience_store":"Supérette","grocery_store":"Épicerie","supermarket":"Supermarché","hypermarket":"Hypermarché","discount_store":"Magasin discount","food_store":"Commerce alimentaire","butcher_shop":"Boucherie","farmers_market":"Marché de producteurs","market":"Marché","clothing_store":"Magasin de vêtements","womens_clothing_store":"Vêtements pour femmes","shoe_store":"Magasin de chaussures","jewelry_store":"Bijouterie","cosmetics_store":"Magasin de cosmétiques","electronics_store":"Magasin d'électronique","cell_phone_store":"Magasin de téléphones","furniture_store":"Magasin de meubles","home_goods_store":"Équipement de la maison","home_improvement_store":"Aménagement de la maison","hardware_store":"Quincaillerie","building_materials_store":"Matériaux de construction","garden_center":"Jardinerie","gift_shop":"Boutique de cadeaux","book_store":"Librairie","toy_store":"Magasin de jouets","pet_store":"Animalerie","bicycle_store":"Magasin de vélos","sporting_goods_store":"Articles de sport","sportswear_store":"Vêtements de sport","thrift_store":"Friperie","wholesaler":"Grossiste"
}
TYPE_LABELS.update({
"doctor":"Médecin","dentist":"Dentiste","dental_clinic":"Clinique dentaire","medical_clinic":"Clinique médicale","medical_center":"Centre médical","medical_lab":"Laboratoire médical","hospital":"Hôpital","general_hospital":"Hôpital général","pharmacy":"Pharmacie","drugstore":"Parapharmacie / Drugstore","physiotherapist":"Kinésithérapeute","chiropractor":"Chiropracteur","veterinary_care":"Vétérinaire","foot_care":"Soins des pieds",
"gym":"Salle de sport","fitness_center":"Centre de fitness","sports_club":"Club sportif","sports_coaching":"Coach sportif","sports_complex":"Complexe sportif","sports_school":"École de sport","swimming_pool":"Piscine","tennis_court":"Court de tennis","golf_course":"Golf","dance_hall":"Salle de danse","bowling_alley":"Bowling","amusement_center":"Centre de loisirs","amusement_park":"Parc d'attractions","indoor_playground":"Aire de jeux intérieure","video_arcade":"Salle d'arcade","paintball_center":"Centre de paintball","go_karting_venue":"Karting",
"event_venue":"Lieu événementiel","wedding_venue":"Lieu de mariage","banquet_hall":"Salle de réception","night_club":"Discothèque","live_music_venue":"Salle de musique live","concert_hall":"Salle de concert","convention_center":"Centre de congrès","tour_agency":"Agence d'excursions","travel_agency":"Agence de voyages","tourist_information_center":"Office de tourisme","tourist_attraction":"Attraction touristique","visitor_center":"Centre d'accueil touristique","marina":"Marina",
"hotel":"Hôtel","resort_hotel":"Hôtel resort","motel":"Motel","hostel":"Auberge de jeunesse","guest_house":"Maison d'hôtes","bed_and_breakfast":"Chambre d'hôtes","lodging":"Hébergement","inn":"Auberge","cottage":"Gîte","campground":"Camping","camping_cabin":"Cabane de camping","farmstay":"Séjour à la ferme",
"real_estate_agency":"Agence immobilière","apartment_building":"Immeuble résidentiel","apartment_complex":"Résidence d'appartements","condominium_complex":"Copropriété","housing_complex":"Ensemble résidentiel",
"business_center":"Centre d'affaires","corporate_office":"Bureau d'entreprise","coworking_space":"Espace de coworking","farm":"Exploitation agricole","manufacturer":"Fabricant","supplier":"Fournisseur","association_or_organization":"Association / Organisation","non_profit_organization":"Organisation à but non lucratif",
"preschool":"École maternelle","primary_school":"École primaire","secondary_school":"Collège / Lycée","school":"École","university":"Université","educational_institution":"Établissement d'enseignement","research_institute":"Institut de recherche","library":"Bibliothèque",
"art_gallery":"Galerie d'art","art_museum":"Musée d'art","art_studio":"Atelier d'art","museum":"Musée","performing_arts_theater":"Salle de spectacle","cultural_center":"Centre culturel","historical_place":"Lieu historique","historical_landmark":"Monument historique",
"taxi_service":"Service de taxi","chauffeur_service":"Service de chauffeur","transportation_service":"Service de transport","ferry_service":"Service de ferry","ferry_terminal":"Terminal ferry","bus_station":"Gare routière","train_station":"Gare ferroviaire","airport":"Aéroport","international_airport":"Aéroport international"
})
def type_label(value):
    return TYPE_LABELS.get(value,(value or "").replace("_"," ").capitalize())
tpl.env.globals["type_label"]=type_label

TYPE_LABELS={
"restaurant":"Restaurant","african_restaurant":"Restaurant africain","caribbean_restaurant":"Restaurant caribéen","french_restaurant":"Restaurant français","italian_restaurant":"Restaurant italien","chinese_restaurant":"Restaurant chinois","indian_restaurant":"Restaurant indien","japanese_restaurant":"Restaurant japonais","korean_restaurant":"Restaurant coréen","thai_restaurant":"Restaurant thaïlandais","mexican_restaurant":"Restaurant mexicain","mediterranean_restaurant":"Restaurant méditerranéen","seafood_restaurant":"Restaurant de fruits de mer","pizza_restaurant":"Pizzeria","fast_food_restaurant":"Restauration rapide","hamburger_restaurant":"Restaurant de burgers","sandwich_shop":"Sandwicherie","sushi_restaurant":"Restaurant de sushis","steak_house":"Grill / Steakhouse","vegan_restaurant":"Restaurant végan","vegetarian_restaurant":"Restaurant végétarien","bakery":"Boulangerie","cafe":"Café","coffee_shop":"Coffee shop","bar":"Bar","cocktail_bar":"Bar à cocktails","pub":"Pub","sports_bar":"Bar sportif","wine_bar":"Bar à vin","juice_shop":"Bar à jus","ice_cream_shop":"Glacier","dessert_shop":"Pâtisserie / Desserts","meal_takeaway":"Plats à emporter","meal_delivery":"Livraison de repas",
"barber_shop":"Barbier / Coiffeur homme","beautician":"Esthéticien(ne)","beauty_salon":"Institut de beauté","hair_care":"Soins capillaires","hair_salon":"Salon de coiffure","makeup_artist":"Maquilleur / Maquilleuse","nail_salon":"Salon de manucure","massage":"Massage","massage_spa":"Spa / Massage","skin_care_clinic":"Centre de soins de la peau","spa":"Spa","tanning_studio":"Centre de bronzage","wellness_center":"Centre de bien-être","yoga_studio":"Studio de yoga",
"car_dealer":"Concessionnaire automobile","car_rental":"Location de voitures","car_repair":"Garage automobile","car_wash":"Lavage automobile","tire_shop":"Magasin de pneus","truck_dealer":"Concessionnaire poids lourds","auto_parts_store":"Magasin de pièces automobiles","gas_station":"Station-service","electric_vehicle_charging_station":"Borne de recharge électrique",
"electrician":"Électricien","plumber":"Plombier","painter":"Peintre","locksmith":"Serrurier","roofing_contractor":"Couvreur","moving_company":"Entreprise de déménagement","laundry":"Blanchisserie / Laverie","tailor":"Tailleur / Couturier","florist":"Fleuriste","courier_service":"Service de coursier","shipping_service":"Service d'expédition","storage":"Garde-meuble / Stockage","consultant":"Consultant","marketing_consultant":"Consultant marketing","employment_agency":"Agence d'emploi","insurance_agency":"Agence d'assurance","lawyer":"Avocat","accounting":"Comptable","telecommunications_service_provider":"Télécommunications","catering_service":"Traiteur",
"store":"Magasin","general_store":"Magasin général","convenience_store":"Supérette","grocery_store":"Épicerie","supermarket":"Supermarché","hypermarket":"Hypermarché","discount_store":"Magasin discount","food_store":"Commerce alimentaire","butcher_shop":"Boucherie","farmers_market":"Marché de producteurs","market":"Marché","clothing_store":"Magasin de vêtements","womens_clothing_store":"Vêtements pour femmes","shoe_store":"Magasin de chaussures","jewelry_store":"Bijouterie","cosmetics_store":"Magasin de cosmétiques","electronics_store":"Magasin d'électronique","cell_phone_store":"Magasin de téléphones","furniture_store":"Magasin de meubles","home_goods_store":"Équipement de la maison","home_improvement_store":"Aménagement de la maison","hardware_store":"Quincaillerie","building_materials_store":"Matériaux de construction","garden_center":"Jardinerie","gift_shop":"Boutique de cadeaux","book_store":"Librairie","toy_store":"Magasin de jouets","pet_store":"Animalerie","bicycle_store":"Magasin de vélos","sporting_goods_store":"Articles de sport","sportswear_store":"Vêtements de sport","thrift_store":"Friperie","wholesaler":"Grossiste",
"doctor":"Médecin","dentist":"Dentiste","dental_clinic":"Clinique dentaire","medical_clinic":"Clinique médicale","medical_center":"Centre médical","medical_lab":"Laboratoire médical","hospital":"Hôpital","general_hospital":"Hôpital général","pharmacy":"Pharmacie","drugstore":"Parapharmacie / Drugstore","physiotherapist":"Kinésithérapeute","chiropractor":"Chiropracteur","veterinary_care":"Vétérinaire","foot_care":"Soins des pieds",
"gym":"Salle de sport","fitness_center":"Centre de fitness","sports_club":"Club sportif","sports_coaching":"Coach sportif","sports_complex":"Complexe sportif","sports_school":"École de sport","swimming_pool":"Piscine","tennis_court":"Court de tennis","golf_course":"Golf","dance_hall":"Salle de danse","bowling_alley":"Bowling","amusement_center":"Centre de loisirs","amusement_park":"Parc d'attractions","indoor_playground":"Aire de jeux intérieure","video_arcade":"Salle d'arcade","paintball_center":"Centre de paintball","go_karting_venue":"Karting",
"event_venue":"Lieu événementiel","wedding_venue":"Lieu de mariage","banquet_hall":"Salle de réception","night_club":"Discothèque","live_music_venue":"Salle de musique live","concert_hall":"Salle de concert","convention_center":"Centre de congrès","tour_agency":"Agence d'excursions","travel_agency":"Agence de voyages","tourist_information_center":"Office de tourisme","tourist_attraction":"Attraction touristique","visitor_center":"Centre d'accueil touristique","marina":"Marina",
"hotel":"Hôtel","resort_hotel":"Hôtel resort","motel":"Motel","hostel":"Auberge de jeunesse","guest_house":"Maison d'hôtes","bed_and_breakfast":"Chambre d'hôtes","lodging":"Hébergement","inn":"Auberge","cottage":"Gîte","campground":"Camping","camping_cabin":"Cabane de camping","farmstay":"Séjour à la ferme",
"real_estate_agency":"Agence immobilière","apartment_building":"Immeuble résidentiel","apartment_complex":"Résidence d'appartements","condominium_complex":"Copropriété","housing_complex":"Ensemble résidentiel",
"business_center":"Centre d'affaires","corporate_office":"Siège / Bureau d'entreprise","coworking_space":"Espace de coworking","farm":"Exploitation agricole","manufacturer":"Fabricant","supplier":"Fournisseur","association_or_organization":"Association / Organisation","non_profit_organization":"Organisation à but non lucratif",
"preschool":"École maternelle","primary_school":"École primaire","secondary_school":"Collège / Lycée","school":"École","university":"Université","educational_institution":"Établissement d'enseignement","research_institute":"Institut de recherche","library":"Bibliothèque",
"art_gallery":"Galerie d'art","art_museum":"Musée d'art","art_studio":"Atelier d'art","museum":"Musée","performing_arts_theater":"Salle de spectacle","cultural_center":"Centre culturel","historical_place":"Lieu historique","historical_landmark":"Monument historique",
"taxi_service":"Service de taxi","chauffeur_service":"Service de chauffeur","transportation_service":"Service de transport","ferry_service":"Service de ferry","ferry_terminal":"Terminal ferry","bus_station":"Gare routière","train_station":"Gare ferroviaire","airport":"Aéroport","international_airport":"Aéroport international"
}
def type_label(value):
    return TYPE_LABELS.get(value,(value or "").replace("_"," ").capitalize())
tpl.env.globals["type_label"]=type_label

def google_age_label(lead):
    if lead.google_activity_at:
        days=(datetime.utcnow()-lead.google_activity_at).days
        if days<=90: return "Récent"
        if days>=730: return "Établi"
        return "Actif"
    return "Ancienneté inconnue"

def detection_label(lead):
    if not lead.first_seen_at: return "Inconnue"
    days=(datetime.utcnow()-lead.first_seen_at).days
    if days<=1: return "Nouveau"
    if days<=7: return "Détecté récemment"
    return "Déjà connu"

tpl.env.globals["google_age_label"]=google_age_label
tpl.env.globals["detection_label"]=detection_label

def worker(jid,types,max_results,rings):
    db=SessionLocal(); job=db.get(Job,jid)
    try:
        job.status="running"; job.started_at=datetime.utcnow(); db.commit()
        seen_ids=set(); client=Places()
        try: target_postal_codes=set(json.loads(job.postal_codes or "[]"))
        except (TypeError,json.JSONDecodeError): target_postal_codes=set()
        points=grid_points(job.latitude,job.longitude,job.radius,rings)
        calls=[(lat,lng,typ) for lat,lng in points for typ in types]
        total_calls=max(1,len(calls)); completed_calls=0
        workers=max(1,min(settings().google_places_workers,len(calls) or 1))

        def nearby_call(item):
            lat,lng,typ=item
            return typ,client.nearby(lat,lng,job.radius,typ,max_results)

        def process_place(place,typ):
            pid=place.get("id")
            if not pid or pid in seen_ids: return False
            seen_ids.add(pid)
            if target_postal_codes:
                address=place.get("formattedAddress") or ""
                place_postal_codes=set(re.findall(r"(?<!\\d)\\d{5}(?!\\d)",address))
                if not (place_postal_codes & target_postal_codes): return False
            phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber")
            if not phone: return False
            digits=normalize_phone(phone)
            if not digits: return False
            website=place.get("websiteUri")
            lead=db.scalar(select(Lead).where(Lead.place_id==pid))
            loc=place.get("location",{})
            values=dict(name=place.get("displayName",{}).get("text","Unnamed"),business_type=typ,city=job.city,address=place.get("formattedAddress"),phone=phone,phone_digits=digits,whatsapp_url="https://wa.me/"+digits,website=website,reviews_count=place.get("userRatingCount") or 0,rating=place.get("rating"),latitude=loc.get("latitude"),longitude=loc.get("longitude"),score=score(place.get("userRatingCount") or 0,website,phone),updated_at=datetime.utcnow())
            if lead:
                for key,value in values.items(): setattr(lead,key,value)
            else:
                google_activity_at=None
                try:
                    review_time=client.oldest_review_time(pid)
                    if review_time: google_activity_at=datetime.fromisoformat(review_time.replace("Z","+00:00")).replace(tzinfo=None)
                except Exception: pass
                lead=Lead(place_id=pid,google_activity_at=google_activity_at,**values)
                db.add(lead); db.flush()
            if not db.scalar(select(JobLead).where(JobLead.job_id==jid,JobLead.lead_id==lead.id)):
                db.add(JobLead(job_id=jid,lead_id=lead.id))
            return True

        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix="places-nearby") as pool:
            futures=[pool.submit(nearby_call,item) for item in calls]
            for future in as_completed(futures):
                typ,places=future.result()
                for place in places:
                    process_place(place,typ)
                completed_calls+=1
                job.total_found=len(seen_ids)
                job.total_filtered=db.scalar(select(func.count()).select_from(JobLead).where(JobLead.job_id==jid)) or 0
                job.error=f"PROGRESS:{completed_calls}/{total_calls}"
                db.commit()

        job.total_found=len(seen_ids)
        job.total_filtered=db.scalar(select(func.count()).select_from(JobLead).where(JobLead.job_id==jid)) or 0
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
def search(city:str=Form(...),latitude:float=Form(...),longitude:float=Form(...),radius:int=Form(1000),business_types:list[str]=Form(...),max_results:int=Form(20),rings:int=Form(1),postal_codes:str=Form(""),db:Session=Depends(get_db)):
    postal_list=[x.strip() for x in postal_codes.split(",") if re.fullmatch(r"\\d{5}",x.strip())]
    job=Job(city=city,latitude=latitude,longitude=longitude,radius=radius,types=json.dumps(business_types),max_results=max_results,rings=rings,postal_codes=json.dumps(postal_list)); db.add(job); db.commit(); db.refresh(job)
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
    job=Job(city=source.city,latitude=source.latitude,longitude=source.longitude,radius=source.radius,types=source.types,max_results=max_results,rings=rings,postal_codes=source.postal_codes)
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
    photos=[]; reviews=[]
    places=Places()
    try: photos=places.photos(lead.place_id,10)
    except Exception: pass
    try: reviews=places.reviews(lead.place_id)
    except Exception: pass
    return tpl.TemplateResponse(request,"lead_detail.html",{"lead":lead,"jobs":jobs,"photos":photos,"reviews":reviews})

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
