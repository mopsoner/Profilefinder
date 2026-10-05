import json
import logging
from pathlib import Path
from datetime import datetime,timezone
import httpx
from .config import settings

TEXT_SEARCH_URL="https://places.googleapis.com/v1/places:searchText"
GEO_URL="https://geo.api.gouv.fr"
CACHE_PATH=Path("data/geography.json")
LEGACY_CACHE_PATH=Path("data/communes_guadeloupe.json")
logger=logging.getLogger("profilefinder.communes")

GUADELOUPE=[
("97101","Les Abymes"),("97102","Anse-Bertrand"),("97103","Baie-Mahault"),("97104","Baillif"),("97105","Basse-Terre"),("97106","Bouillante"),("97107","Capesterre-Belle-Eau"),("97108","Capesterre-de-Marie-Galante"),("97111","Deshaies"),("97110","La Désirade"),("97113","Le Gosier"),("97109","Gourbeyre"),("97114","Goyave"),("97112","Grand-Bourg"),("97115","Lamentin"),("97116","Morne-à-l'Eau"),("97117","Le Moule"),("97118","Petit-Bourg"),("97119","Petit-Canal"),("97121","Pointe-Noire"),("97120","Pointe-à-Pitre"),("97122","Port-Louis"),("97124","Saint-Claude"),("97125","Saint-François"),("97126","Saint-Louis"),("97128","Sainte-Anne"),("97129","Sainte-Rose"),("97130","Terre-de-Bas"),("97131","Terre-de-Haut"),("97132","Trois-Rivières"),("97133","Vieux-Fort"),("97134","Vieux-Habitants")]

def _empty():
    return {"departments":{"971":{"code":"971","name":"Guadeloupe","communes":{code:{"code":code,"name":name,"resolved":False} for code,name in GUADELOUPE}}}}

def _load_cache():
    if CACHE_PATH.exists():
        try: return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception as exc: logger.warning("GEO_CACHE_READ_ERROR error=%s",exc)
    data=_empty()
    if LEGACY_CACHE_PATH.exists():
        try:
            for x in json.loads(LEGACY_CACHE_PATH.read_text(encoding="utf-8")):
                if x.get("code"): data["departments"]["971"]["communes"][x["code"]]=x
        except Exception as exc: logger.warning("LEGACY_GEO_CACHE_READ_ERROR error=%s",exc)
    _save_cache(data); return data

def _save_cache(data):
    CACHE_PATH.parent.mkdir(parents=True,exist_ok=True)
    tmp=CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(CACHE_PATH)

def get_departments():
    data=_load_cache()
    rows=[]
    for dep in data["departments"].values():
        communes=list(dep.get("communes",{}).values())
        resolved=sum(1 for x in communes if _is_resolved(x))
        rows.append({**dep,"communes":sorted(communes,key=lambda x:x["name"]),"total":len(communes),"resolved_count":resolved,"missing_count":len(communes)-resolved})
    return sorted(rows,key=lambda x:x["name"])

def get_communes(department_code="971"):
    dep=_load_cache()["departments"].get(department_code)
    return sorted((dep or {}).get("communes",{}).values(),key=lambda x:x["name"])

def _is_resolved(x):
    return bool(x.get("google_place_id") and x.get("latitude") is not None and x.get("longitude") is not None)

def add_department(code):
    code=code.strip().upper()
    with httpx.Client(timeout=30) as client:
        r=client.get(f"{GEO_URL}/departements/{code}")
        r.raise_for_status(); dep=r.json()
        r=client.get(f"{GEO_URL}/departements/{code}/communes",params={"fields":"nom,code,codesPostaux","format":"json"})
        r.raise_for_status(); communes=r.json()
    if not communes: raise RuntimeError(f"Aucune commune trouvée pour le département {code}")
    data=_load_cache()
    existing=data["departments"].get(code,{}).get("communes",{})
    data["departments"][code]={"code":code,"name":dep["nom"],"communes":{x["code"]:{**existing.get(x["code"],{}),"code":x["code"],"name":x["nom"],"postal_codes":x.get("codesPostaux",[]),"resolved":_is_resolved(existing.get(x["code"],{}))} for x in communes}}
    _save_cache(data)
    logger.info("DEPARTMENT_ADD code=%s name=%s communes=%s",code,dep["nom"],len(communes))
    return data["departments"][code]

def delete_department(code):
    code=code.strip().upper()
    data=_load_cache()
    dep=data["departments"].get(code)
    if not dep: raise ValueError("Département inconnu")
    removed=len(dep.get("communes",{}))
    name=dep.get("name",code)
    del data["departments"][code]
    _save_cache(data)
    logger.info("DEPARTMENT_DELETE code=%s name=%s communes=%s",code,name,removed)
    return {"code":code,"name":name,"communes_removed":removed}

def refresh_department_metadata(code):
    code=code.strip().upper()
    data=_load_cache(); current=data["departments"].get(code)
    if not current: return add_department(code)
    with httpx.Client(timeout=30) as client:
        r=client.get(f"{GEO_URL}/departements/{code}/communes",params={"fields":"nom,code,codesPostaux","format":"json"})
        r.raise_for_status(); rows=r.json()
    for x in rows:
        old=current["communes"].get(x["code"],{})
        current["communes"][x["code"]]={**old,"code":x["code"],"name":x["nom"],"postal_codes":x.get("codesPostaux",[]),"resolved":_is_resolved(old)}
    _save_cache(data); return current

def resolve_commune(code,department_code="971"):
    data=_load_cache(); dep=data["departments"].get(department_code)
    if not dep or code not in dep.get("communes",{}): raise ValueError("Commune inconnue dans ce département")
    name=dep["communes"][code]["name"]; dep_name=dep["name"]
    key=settings().google_places_api_key
    if not key: raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured")
    headers={"Content-Type":"application/json","X-Goog-Api-Key":key,"X-Goog-FieldMask":"places.id,places.displayName,places.formattedAddress,places.location,places.types"}
    body={"textQuery":f"{name}, {dep_name}, France","languageCode":"fr","regionCode":"FR","maxResultCount":5}
    response=httpx.post(TEXT_SEARCH_URL,json=body,headers=headers,timeout=30); response.raise_for_status()
    places=response.json().get("places",[])
    if not places: raise RuntimeError(f"Google Places n'a trouvé aucune correspondance pour {name}")
    def norm(v): return (v or "").casefold().replace("-"," ").replace("'"," ")
    exact=[p for p in places if norm((p.get("displayName") or {}).get("text"))==norm(name)]
    place=(exact or places)[0]; loc=place.get("location") or {}
    if loc.get("latitude") is None or loc.get("longitude") is None: raise RuntimeError(f"Google Places n'a pas renvoyé de coordonnées pour {name}")
    postal_codes=dep["communes"][code].get("postal_codes",[])
    return {"code":code,"name":name,"postal_codes":postal_codes,"department_code":department_code,"department_name":dep_name,"google_place_id":place.get("id"),"google_name":(place.get("displayName") or {}).get("text"),"formatted_address":place.get("formattedAddress"),"latitude":loc["latitude"],"longitude":loc["longitude"],"types":place.get("types",[]),"resolved":True,"resolved_at":datetime.now(timezone.utc).isoformat()}

def force_resolve_commune(code,department_code="971"):
    result=resolve_commune(code,department_code); data=_load_cache()
    data["departments"][department_code]["communes"][code]=result; _save_cache(data); return result

def get_or_resolve_commune(code,department_code="971"):
    data=_load_cache(); cached=data["departments"].get(department_code,{}).get("communes",{}).get(code)
    if cached and _is_resolved(cached): return cached
    return force_resolve_commune(code,department_code)

def initialize_department(department_code):
    try: refresh_department_metadata(department_code)
    except Exception as exc: logger.warning("DEPARTMENT_METADATA_REFRESH_ERROR code=%s error=%s",department_code,exc)
    data=_load_cache(); dep=data["departments"].get(department_code)
    if not dep: raise ValueError("Département inconnu")
    missing=[x for x in dep["communes"].values() if not _is_resolved(x)]
    logger.info("DEPARTMENT_INIT code=%s missing=%s",department_code,len(missing))
    for x in missing:
        try:
            force_resolve_commune(x["code"],department_code)
            logger.info("COMMUNE_INIT_OK department=%s code=%s name=%s",department_code,x["code"],x["name"])
        except Exception as exc: logger.error("COMMUNE_INIT_ERROR department=%s code=%s name=%s error=%s",department_code,x["code"],x["name"],exc)

def initialize_communes():
    initialize_department("971")

def commune_stats():
    deps=get_departments()
    return {"departments":len(deps),"total":sum(x["total"] for x in deps),"resolved":sum(x["resolved_count"] for x in deps),"missing":sum(x["missing_count"] for x in deps)}
