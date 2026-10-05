import json
import logging
import time
from pathlib import Path
import httpx
from .config import settings

URL="https://places.googleapis.com/v1/places:searchNearby"
MASK=",".join(["places.id","places.displayName","places.formattedAddress","places.nationalPhoneNumber","places.internationalPhoneNumber","places.websiteUri","places.userRatingCount","places.rating","places.location"])

Path("data/logs").mkdir(parents=True,exist_ok=True)
logger=logging.getLogger("profilefinder.places")
if not logger.handlers:
    handler=logging.FileHandler("data/logs/places.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

class Places:
    def nearby(self,lat,lng,radius,business_type,max_results=20):
        key=settings().google_places_api_key
        if not key:
            logger.error("API_KEY_MISSING type=%s lat=%s lng=%s",business_type,lat,lng)
            raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured")
        body={"includedTypes":[business_type],"maxResultCount":min(20,max(1,max_results)),"locationRestriction":{"circle":{"center":{"latitude":lat,"longitude":lng},"radius":float(min(radius,50000))}}}
        headers={"X-Goog-Api-Key":key,"X-Goog-FieldMask":MASK,"Content-Type":"application/json"}
        with httpx.Client(timeout=30) as client:
            for attempt in range(4):
                try:
                    response=client.post(URL,json=body,headers=headers)
                except httpx.RequestError as exc:
                    logger.error("NETWORK_ERROR type=%s lat=%.6f lng=%.6f attempt=%s error=%s",business_type,lat,lng,attempt+1,exc)
                    if attempt==3: raise
                    time.sleep(2**attempt); continue
                try: payload=response.json()
                except ValueError: payload={}
                count=len(payload.get("places",[])) if isinstance(payload,dict) else 0
                google_error=payload.get("error",{}) if isinstance(payload,dict) else {}
                logger.info("CALL type=%s lat=%.6f lng=%.6f radius=%s attempt=%s status=%s results=%s google_status=%s message=%s",business_type,lat,lng,radius,attempt+1,response.status_code,count,google_error.get("status","-"),json.dumps(google_error.get("message","-"),ensure_ascii=False))
                if response.status_code not in (429,500,502,503,504):
                    response.raise_for_status()
                    return payload.get("places",[])
                time.sleep(2**attempt)
            response.raise_for_status()
