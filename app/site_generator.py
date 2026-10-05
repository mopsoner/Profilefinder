import json
import httpx
from .config import settings
API_URL="https://api.openai.com/v1/responses"

def generate_lead_website(lead,insights):
    cfg=settings()
    if not cfg.openai_api_key: raise RuntimeError("OPENAI_API_KEY is not configured")
    facts={"name":lead.name,"business_type":lead.business_type,"city":lead.city,"address":lead.address,"phone":lead.phone,"rating":lead.rating,"reviews_count":lead.reviews_count,"website":lead.website,"review_insights":insights or {}}
    section={"type":"object","additionalProperties":False,"properties":{"title":{"type":"string"},"text":{"type":"string"},"items":{"type":"array","items":{"type":"string"}},"example":{"type":"boolean"}},"required":["title","text","items","example"]}
    page={"type":"object","additionalProperties":False,"properties":{"slug":{"type":"string"},"nav_label":{"type":"string"},"title":{"type":"string"},"intro":{"type":"string"},"sections":{"type":"array","items":section}},"required":["slug","nav_label","title","intro","sections"]}
    schema={"type":"object","additionalProperties":False,"properties":{"site_title":{"type":"string"},"tagline":{"type":"string"},"theme":{"type":"string","enum":["electric","midnight","aurora","sunset"]},"pages":{"type":"array","minItems":3,"maxItems":7,"items":page},"cta_title":{"type":"string"},"cta_text":{"type":"string"}},"required":["site_title","tagline","theme","pages","cta_title","cta_text"]}
    instructions="""Conçois un site vitrine professionnel complet adapté au métier du prospect. Génère entre 3 et 7 pages réellement utiles : accueil puis, selon le métier, services, prestations, menu, galerie, à propos, FAQ ou contact. Utilise les faits et insights fournis. Tu peux proposer des exemples pertinents pour démontrer le potentiel du site. Toute information non confirmée comme un prix, menu, prestation détaillée, horaire, membre d'équipe ou réalisation doit rester explicitement une proposition et la section doit avoir example=true. N'invente jamais certification, distinction, adresse, téléphone, note ou témoignage. Écris en français, style premium et orienté conversion. Les slugs sont courts, minuscules, sans accents; la première page utilise accueil."""
    body={"model":cfg.openai_model,"instructions":instructions,"input":"Données du prospect : "+json.dumps(facts,ensure_ascii=False),"text":{"format":{"type":"json_schema","name":"business_website","strict":True,"schema":schema}}}
    response=httpx.post(API_URL,json=body,headers={"Authorization":"Bearer "+cfg.openai_api_key,"Content-Type":"application/json"},timeout=120)
    response.raise_for_status(); payload=response.json(); chunks=[]
    for item in payload.get("output",[]):
        if item.get("type")=="message":
            for part in item.get("content",[]):
                if part.get("type")=="output_text": chunks.append(part.get("text",""))
    if not chunks: raise RuntimeError("OpenAI did not return website content")
    return json.loads("".join(chunks))
