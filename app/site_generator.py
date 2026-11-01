import base64
import json
from pathlib import Path
import httpx
from .config import settings

API_URL="https://api.openai.com/v1/responses"
IMAGE_URL="https://api.openai.com/v1/images/generations"

DESIGN_HINTS={
    "restaurant":"warm editorial food photography, generous menu cards, reservation-forward layout",
    "cafe":"bright artisanal café, warm natural materials, lifestyle photography",
    "bakery":"warm craft bakery, product-first editorial grid, cream and earthy tones",
    "bar":"dark cinematic nightlife, bold typography, atmospheric photography",
    "beauty_salon":"soft luxury beauty editorial, airy spacing, elegant typography",
    "hair_salon":"fashion editorial salon, strong portrait-led layout, refined contrast",
    "spa":"calm wellness luxury, organic shapes, soft natural palette",
    "gym":"high-energy fitness, bold condensed typography, dynamic action imagery",
    "dentist":"clean reassuring healthcare, bright whitespace, trust-led layout",
    "doctor":"calm professional healthcare, accessible cards, clean typography",
    "lawyer":"authoritative premium editorial, restrained palette, serif accents",
    "real_estate_agency":"architectural luxury editorial, large property imagery, refined grid",
    "car_repair":"industrial technical, strong service cards, workshop imagery",
    "plumber":"clean practical local service, trust badges, strong contact actions",
    "electrician":"modern technical service, structured grid, confident accent color",
    "hotel":"immersive hospitality editorial, full-bleed imagery, elegant booking feel",
    "travel_agency":"aspirational travel magazine, destination imagery, vibrant editorial cards",
    "photographer":"minimal portfolio-first gallery, oversized imagery, quiet typography",
}

def design_hint(business_type):
    value=(business_type or "").lower()
    for key,hint in DESIGN_HINTS.items():
        if key in value: return hint
    return "modern local business, image-rich editorial layout adapted to the profession"

def generate_lead_website(lead,insights):
    cfg=settings()
    if not cfg.openai_api_key: raise RuntimeError("OPENAI_API_KEY is not configured")
    facts={"name":lead.name,"business_type":lead.business_type,"city":lead.city,"address":lead.address,"phone":lead.phone,"rating":lead.rating,"reviews_count":lead.reviews_count,"website":lead.website,"review_insights":insights or {},"design_hint":design_hint(lead.business_type)}
    section={"type":"object","additionalProperties":False,"properties":{"title":{"type":"string"},"text":{"type":"string"},"items":{"type":"array","items":{"type":"string"}},"image_prompt":{"type":"string"}},"required":["title","text","items","image_prompt"]}
    page={"type":"object","additionalProperties":False,"properties":{"slug":{"type":"string"},"nav_label":{"type":"string"},"title":{"type":"string"},"intro":{"type":"string"},"sections":{"type":"array","items":section}},"required":["slug","nav_label","title","intro","sections"]}
    schema={"type":"object","additionalProperties":False,"properties":{"site_title":{"type":"string"},"tagline":{"type":"string"},"design":{"type":"string","enum":["restaurant","hospitality","beauty","wellness","professional","trades","automotive","retail","creative","fitness","healthcare","general"]},"theme":{"type":"string","enum":["warm","light","dark","natural","bold","luxury"]},"hero_style":{"type":"string","enum":["split","full_image","editorial","centered","mosaic","service_first"]},"layout_style":{"type":"string","enum":["cards","editorial","magazine","minimal","showcase","service_grid"]},"radius_style":{"type":"string","enum":["square","soft","round"]},"pages":{"type":"array","minItems":3,"maxItems":7,"items":page},"cta_title":{"type":"string"},"cta_text":{"type":"string"}},"required":["site_title","tagline","design","theme","hero_style","layout_style","radius_style","pages","cta_title","cta_text"]}
    instructions="""Tu es directeur artistique et concepteur web senior. Crée un vrai site professionnel complet dont la direction artistique, l'architecture, le ton et les pages sont SPECIFIQUES au type d'entreprise. Un restaurant doit ressembler à un restaurant, un salon à un site beauté, un artisan à un site de service local, un hôtel à un site hospitality, etc. Évite absolument un template générique répété. Choisis design, theme, hero_style, layout_style et radius_style selon le métier et les données. Ces choix doivent réellement varier entre catégories : restauration/hôtellerie privilégient image plein écran, magazine ou éditorial; beauté/wellness des compositions aérées et raffinées; artisans des grilles de services très lisibles et CTA immédiats; automobile un rendu industriel angulaire; créatifs un portfolio/showcase; santé et professions libérales un rendu clair, rassurant et minimal. Ne choisis pas systématiquement dark/split/cards. Génère 3 à 7 pages utiles au métier. Le rendu est final : n'utilise jamais les mots exemple, proposition, démonstration, fictif ou contenu proposé. Pour les informations inconnues, reste commercial et prudent sans inventer prix, horaires, certifications, distinctions, témoignages, équipe ou réalisations. Rends le site riche visuellement : donne un image_prompt photographique détaillé à 2 ou 3 sections importantes maximum. Ces prompts doivent produire des images éditoriales réalistes adaptées au métier, sans logo, sans texte dans l'image, sans prétendre représenter le vrai établissement, ses employés ou ses réalisations. Écris en français. Slugs courts sans accents; première page accueil."""
    body={"model":cfg.openai_model,"instructions":instructions,"input":"Données du prospect : "+json.dumps(facts,ensure_ascii=False),"text":{"format":{"type":"json_schema","name":"business_website","strict":True,"schema":schema}}}
    response=httpx.post(API_URL,json=body,headers={"Authorization":"Bearer "+cfg.openai_api_key,"Content-Type":"application/json"},timeout=120)
    response.raise_for_status(); payload=response.json(); chunks=[]
    for item in payload.get("output",[]):
        if item.get("type")=="message":
            for part in item.get("content",[]):
                if part.get("type")=="output_text": chunks.append(part.get("text",""))
    if not chunks: raise RuntimeError("OpenAI did not return website content")
    return json.loads("".join(chunks))

def generate_site_images(lead_id,site):
    cfg=settings()
    if not cfg.site_ai_images or not cfg.openai_api_key: return site
    out=Path("app/static/generated")/str(lead_id); out.mkdir(parents=True,exist_ok=True)
    count=0
    for page in site.get("pages",[]):
        for section in page.get("sections",[]):
            prompt=(section.get("image_prompt") or "").strip()
            if not prompt or count>=max(0,cfg.site_ai_max_images): continue
            body={"model":cfg.openai_image_model,"prompt":prompt+", professional commercial website photography, realistic, polished editorial lighting, no words, no logos, no watermarks","size":"1536x1024","quality":"medium","n":1}
            try:
                r=httpx.post(IMAGE_URL,json=body,headers={"Authorization":"Bearer "+cfg.openai_api_key,"Content-Type":"application/json"},timeout=180)
                r.raise_for_status(); data=r.json().get("data") or []
                if not data: continue
                raw=data[0].get("b64_json")
                if not raw: continue
                name=f"{page.get('slug','page')}-{count+1}.png"
                (out/name).write_bytes(base64.b64decode(raw))
                section["image_url"]=f"/static/generated/{lead_id}/{name}"
                count+=1
            except Exception:
                continue
    return site
