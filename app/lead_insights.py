import json
import httpx
from .config import settings

API_URL="https://api.openai.com/v1/responses"

def build_insights(lead,items):
    cfg=settings()
    if not cfg.openai_api_key: raise RuntimeError("OPENAI_API_KEY is not configured")
    rows=[]
    for item in items[:8]:
        value=((item.get("text") or {}).get("text") or "").strip()
        if value: rows.append({"rating":item.get("rating"),"text":value[:1200]})
    schema={"type":"object","additionalProperties":False,"properties":{
      "summary":{"type":"string"},"sentiment":{"type":"string"},
      "strengths":{"type":"array","items":{"type":"string"}},
      "weaknesses":{"type":"array","items":{"type":"string"}},
      "customer_needs":{"type":"array","items":{"type":"string"}},
      "services_mentioned":{"type":"array","items":{"type":"string"}}
    },"required":["summary","sentiment","strengths","weaknesses","customer_needs","services_mentioned"]}
    body={"model":cfg.openai_model,
      "instructions":"Analyse les retours clients fournis. Conserve seulement les tendances soutenues par le contenu. N'invente aucun fait. Les éléments incertains restent des signaux clients.",
      "input":json.dumps({"name":lead.name,"business_type":lead.business_type,"items":rows},ensure_ascii=False),
      "text":{"format":{"type":"json_schema","name":"lead_insights","strict":True,"schema":schema}}}
    response=httpx.post(API_URL,json=body,headers={"Authorization":"Bearer "+cfg.openai_api_key,"Content-Type":"application/json"},timeout=120)
    response.raise_for_status(); payload=response.json(); chunks=[]
    for item in payload.get("output",[]):
        if item.get("type")=="message":
            for part in item.get("content",[]):
                if part.get("type")=="output_text": chunks.append(part.get("text",""))
    if not chunks: raise RuntimeError("OpenAI did not return insights")
    return json.loads("".join(chunks))
