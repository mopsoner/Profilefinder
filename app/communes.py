import json
import logging
from pathlib import Path
from datetime import datetime,timezone
import httpx
from .config import settings

TEXT_SEARCH_URL="https://places.googleapis.com/v1/places:searchText"
CACHE_PATH=Path("data/communes_guadeloupe.json")
logger=logging.getLogger("profilefinder.communes")

COMMUNES=[
("97101","Les Abymes"),("97102","Anse-Bertrand"),("97103","Baie-Mahault"),("97104","Baillif"),
("97105","Basse-Terre"),("97106","Bouillante"),("97107","Capesterre-Belle-Eau"),
("97108","Capesterre-de-Marie-Galante"),("97111","Deshaies"),("97110","La Désirade"),
("97113","Le Gosier"),("97109","Gourbeyre"),("97114","Goyave"),("97112","Grand-Bourg"),
("97115","Lamentin"),("97116","Morne-à-l'Eau"),("97117","Le Moule"),("97118","Petit-Bourg"),
("97119","Petit-Canal"),("97121","Pointe-Noire"),("97120","Pointe-à-Pitre"),("97122","Port-Louis"),
("97124","Saint-Claude"),("97125","Saint-François"),("97126","Saint-Louis"),("97128","Sainte-Anne"),
("97129","Sainte-Rose"),("97130","Terre-de-Bas"),("97131","Terre-de-Haut"),("97132","Trois-Rivières"),
("97133","Vieux-Fort"),("97134","Vieux-Habitants")
]

def _load_cache():
    if not CACHE_PATH.exists(): return {}
    try:
        rows=json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {x["code"]:x for x in rows if x.get("code")}
    except Exception as exc:
        logger.warning("COMMUNE_CACHE_READ_ERROR error=%s",exc)
        return {}

def _save_cache(cache):
    CACHE_PATH.parent.mkdir(parents=True,exist_ok=True)
    rows=sorted(cache.values(),key=lambda x:x["name"])
    tmp=CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(CACHE_PATH)

def get_communes():
    cache=_load_cache()
    return [cache.get(code,{"code":code,"name":name,"resolved":False}) for code,name in sorted(COMMUNES,key=lambda x:x[1])]

def resolve_commune(code):
    row=next(((c,n) for c,n in COMMUNES if c==code),None)
    if not row: raise ValueError("Commune de Guadeloupe inconnue")
    _,name=row
    key=settings().google_places_api_key
    if not key: raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured")
    headers={"Content-Type":"application/json","X-Goog-Api-Key":key,"X-Goog-FieldMask":"places.id,places.displayName,places.formattedAddress,places.location,places.types"}
    body={"textQuery":f"{name}, Guadeloupe, France","languageCode":"fr","regionCode":"FR","maxResultCount":5}
    response=httpx.post(TEXT_SEARCH_URL,json=body,headers=headers,timeout=30)
    response.raise_for_status()
    places=response.json().get("places",[])
    if not places: raise RuntimeError(f"Google Places n'a trouvé aucune correspondance pour {name}")
    def norm(v): return (v or "").casefold().replace("-"," ").replace("'"," ")
    exact=[p for p in places if norm((p.get("displayName") or {}).get("text"))==norm(name)]
    place=(exact or places)[0]; loc=place.get("location") or {}
    if loc.get("latitude") is None or loc.get("longitude") is None: raise RuntimeError(f"Google Places n'a pas renvoyé de coordonnées pour {name}")
    return {"code":code,"name":name,"google_place_id":place.get("id"),"google_name":(place.get("displayName") or {}).get("text"),"formatted_address":place.get("formattedAddress"),"latitude":loc["latitude"],"longitude":loc["longitude"],"types":place.get("types",[]),"resolved":True,"resolved_at":datetime.now(timezone.utc).isoformat()}

def initialize_communes():
    cache=_load_cache(); missing=[]
    for code,name in COMMUNES:
        x=cache.get(code)
        if not x or not x.get("google_place_id") or x.get("latitude") is None or x.get("longitude") is None:
            missing.append((code,name))
    if not missing:
        logger.info("COMMUNE_INIT complete cached=%s missing=0",len(cache)); return
    logger.info("COMMUNE_INIT start cached=%s missing=%s",len(cache),len(missing))
    for code,name in missing:
        try:
            cache[code]=resolve_commune(code); _save_cache(cache)
            logger.info("COMMUNE_INIT_OK code=%s name=%s place_id=%s",code,name,cache[code]["google_place_id"])
        except Exception as exc:
            logger.error("COMMUNE_INIT_ERROR code=%s name=%s error=%s",code,name,exc)
    logger.info("COMMUNE_INIT done resolved=%s total=%s",sum(1 for x in cache.values() if x.get("resolved")),len(COMMUNES))

def get_or_resolve_commune(code):
    cached=_load_cache().get(code)
    if cached and cached.get("google_place_id") and cached.get("latitude") is not None and cached.get("longitude") is not None: return cached
    result=resolve_commune(code); cache=_load_cache(); cache[code]=result; _save_cache(cache); return result

def force_resolve_commune(code):
    result=resolve_commune(code)
    cache=_load_cache(); cache[code]=result; _save_cache(cache)
    return result

def commune_stats():
    rows=get_communes()
    resolved=sum(1 for x in rows if x.get("google_place_id") and x.get("latitude") is not None and x.get("longitude") is not None)
    return {"total":len(rows),"resolved":resolved,"missing":len(rows)-resolved}
