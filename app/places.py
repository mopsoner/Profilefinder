import time
import httpx
from .config import settings

URL="https://places.googleapis.com/v1/places:searchNearby"
MASK=",".join(["places.id","places.displayName","places.formattedAddress","places.nationalPhoneNumber","places.internationalPhoneNumber","places.websiteUri","places.userRatingCount","places.rating","places.location"])

class Places:
    def nearby(self,lat,lng,radius,business_type,max_results=20):
        key=settings().google_places_api_key
        if not key:
            raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured")
        body={"includedTypes":[business_type],"maxResultCount":min(20,max(1,max_results)),"locationRestriction":{"circle":{"center":{"latitude":lat,"longitude":lng},"radius":float(min(radius,50000))}}}
        headers={"X-Goog-Api-Key":key,"X-Goog-FieldMask":MASK,"Content-Type":"application/json"}
        with httpx.Client(timeout=30) as client:
            for attempt in range(4):
                response=client.post(URL,json=body,headers=headers)
                if response.status_code not in (429,500,502,503,504):
                    response.raise_for_status()
                    return response.json().get("places",[])
                time.sleep(2**attempt)
            response.raise_for_status()
