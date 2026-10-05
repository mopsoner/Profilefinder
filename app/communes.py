import logging
import httpx

URL="https://geo.api.gouv.fr/departements/971/communes"
logger=logging.getLogger("profilefinder.communes")

# Official INSEE COG 2026 list. Coordinates are refreshed from geo.api.gouv.fr.
FALLBACK_NAMES=[
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
    try:
        r=httpx.get(URL,params={"fields":"nom,code,centre","format":"json"},timeout=10)
        r.raise_for_status()
        rows=[]
        for x in r.json():
            coords=(x.get("centre") or {}).get("coordinates") or []
            if len(coords)==2:
                rows.append({"code":x["code"],"name":x["nom"],"latitude":coords[1],"longitude":coords[0]})
        if len(rows)==32:
            return sorted(rows,key=lambda x:x["name"])
        logger.warning("Unexpected commune count from geo.api.gouv.fr: %s",len(rows))
    except Exception as exc:
        logger.warning("Unable to refresh Guadeloupe communes: %s",exc)
    return [{"code":code,"name":name,"latitude":None,"longitude":None} for code,name in sorted(FALLBACK_NAMES,key=lambda x:x[1])]
