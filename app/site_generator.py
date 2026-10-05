import json
import httpx
from .config import settings

API_URL="https://api.openai.com/v1/responses"

def generate_lead_website(lead,reviews):
    cfg=settings()
    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    review_rows=[]
    for r in reviews[:8]:
        text=((r.get("text") or {}).get("text") or "").strip()
        if text:
            review_rows.append({"rating":r.get("rating"),"text":text[:1200]})
    facts={
        "name":lead.name,"business_type":lead.business_type,"city":lead.city,
        "address":lead.address,"phone":lead.phone,"rating":lead.rating,
        "reviews_count":lead.reviews_count,"website":lead.website,
        "reviews":review_rows
    }
    schema={
      "type":"object","additionalProperties":False,
      "properties":{
        "eyebrow":{"type":"string"},"headline":{"type":"string"},"subheadline":{"type":"string"},
        "about_title":{"type":"string"},"about_text":{"type":"string"},
        "services":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"title":{"type":"string"},"text":{"type":"string"}},"required":["title","text"]}},
        "strengths":{"type":"array","items":{"type":"string"}},
        "cta_title":{"type":"string"},"cta_text":{"type":"string"},
        "theme":{"type":"string","enum":["electric","midnight","aurora","sunset"]}
      },
      "required":["eyebrow","headline","subheadline","about_title","about_text","services","strengths","cta_title","cta_text","theme"]
    }
    instructions="""Tu conçois le contenu d'un site vitrine futuriste pour une entreprise locale.
Utilise uniquement les faits fournis. Les avis servent à comprendre les qualités perçues et besoins clients, sans inventer de services, prix, horaires, distinctions ou promesses.
N'affirme jamais qu'un élément provenant d'un avis est un fait certain sur l'entreprise. Écris en français, ton commercial premium, phrases courtes.
Si les services exacts ne sont pas connus, utilise des formulations prudentes adaptées au type d'établissement."""
    body={"model":cfg.openai_model,"instructions":instructions,
          "input":"Données du prospect : "+json.dumps(facts,ensure_ascii=False),
          "text":{"format":{"type":"json_schema","name":"lead_website","strict":True,"schema":schema}}}
    headers={"Authorization":"Bearer "+cfg.openai_api_key,"Content-Type":"application/json"}
    response=httpx.post(API_URL,json=body,headers=headers,timeout=120)
    response.raise_for_status()
    payload=response.json()
    chunks=[]
    for item in payload.get("output",[]):
        if item.get("type")=="message":
            for part in item.get("content",[]):
                if part.get("type")=="output_text": chunks.append(part.get("text",""))
    if not chunks: raise RuntimeError("OpenAI did not return website content")
    return json.loads("".join(chunks))
