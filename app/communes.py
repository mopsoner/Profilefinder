import logging
import httpx
from .config import settings

TEXT_SEARCH_URL="https://places.googleapis.com/v1/places:searchText"
logger=logging.getLogger("profilefinder.communes")

# Official INSEE COG 2026 list for department 971. Google Places resolves the
# operational Place ID and coordinates when the user selects a commune.
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

def get_communes():
    return [{"code":code,"name":name} for code,name in sorted(COMMUNES,key=lambda x:x[1])]

def resolve_commune(code):
    row=next(((c,n) for c,n in COMMUNES if c==code),None)
    if not row:
        raise ValueError("Commune de Guadeloupe inconnue")
    _,name=row
    key=settings().google_places_api_key
    if not key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured")
    headers={
        "Content-Type":"application/json",
        "X-Goog-Api-Key":key,
        "X-Goog-FieldMask":"places.id,places.displayName,places.formattedAddress,places.location,places.types"
    }
    body={"textQuery":f"{name}, Guadeloupe, France","languageCode":"fr","regionCode":"FR","maxResultCount":5}
    response=httpx.post(TEXT_SEARCH_URL,json=body,headers=headers,timeout=30)
    response.raise_for_status()
    places=response.json().get("places",[])
    if not places:
        raise RuntimeError(f"Google Places n'a trouvé aucune correspondance pour {name}")
    # Prefer the exact commune name; otherwise keep Google's first ranked result.
    def norm(v): return (v or "").casefold().replace("-"," ").replace("'"," ")
    exact=[p for p in places if norm((p.get("displayName") or {}).get("text"))==norm(name)]
    place=(exact or places)[0]
    loc=place.get("location") or {}
    if loc.get("latitude") is None or loc.get("longitude") is None:
        raise RuntimeError(f"Google Places n'a pas renvoyé de coordonnées pour {name}")
    result={
        "code":code,
        "name":name,
        "google_place_id":place.get("id"),
        "google_name":(place.get("displayName") or {}).get("text"),
        "formatted_address":place.get("formattedAddress"),
        "latitude":loc["latitude"],
        "longitude":loc["longitude"],
        "types":place.get("types",[])
    }
    logger.info("COMMUNE_RESOLVE code=%s name=%s place_id=%s lat=%s lng=%s",code,name,result["google_place_id"],result["latitude"],result["longitude"])
    return result
