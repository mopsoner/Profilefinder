import json
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from app import ad_copy


def test_context_contains_profile_reviews_analysis_and_site():
    lead=SimpleNamespace(name='Maison Sauvage',business_type='restaurant',city='Bordeaux',address='12 rue des Arts',phone='0556000000',website=None,rating=4.7,reviews_count=80,insights_json=json.dumps({'strengths':['Cuisine de saison']}),reviews_json=json.dumps([{'rating':5,'text':{'text':'Très bon accueil'},'authorAttribution':{'displayName':'Nom privé'}}]))
    facts=ad_copy.lead_facts(lead,SimpleNamespace(content_json=json.dumps({'pages':[{'title':'Notre cuisine'}]})))
    text=json.dumps(facts,ensure_ascii=False)
    assert all(value in text for value in ('Maison Sauvage','Cuisine de saison','Très bon accueil','Notre cuisine','12 rue des Arts'))
    assert 'Nom privé' not in text


def test_openai_reuses_model_and_key_and_returns_editable_script(monkeypatch):
    monkeypatch.setattr(ad_copy,'settings',lambda:SimpleNamespace(openai_api_key='test-key',openai_model='configured-model'))
    response=httpx.Response(200,request=httpx.Request('POST','https://api.openai.com/v1/responses'),json={'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'script':'Découvrez Maison Sauvage à Bordeaux.'})}]}]})
    with patch('app.ad_copy.httpx.post',return_value=response) as send:
        result=ad_copy.generate_copy({'profil':{'nom':'Maison Sauvage'}},'warm',30,'Cuisine locale')
    body=send.call_args.kwargs['json']
    assert body['model']=='configured-model'
    assert 'Maison Sauvage' in body['input'] and 'Cuisine locale' in body['input']
    assert '30 secondes' in body['instructions'] and "N'invente" in body['instructions']
    assert result['script']=='Découvrez Maison Sauvage à Bordeaux.'
    assert result['provider']=='openai'


def test_missing_key_does_not_call_provider(monkeypatch):
    monkeypatch.setattr(ad_copy,'settings',lambda:SimpleNamespace(openai_api_key=''))
    with patch('app.ad_copy.httpx.post') as send:
        with pytest.raises(ad_copy.CopyUnavailable):ad_copy.generate_copy({},'warm',30)
        send.assert_not_called()


def test_unusable_provider_output_is_reported(monkeypatch):
    monkeypatch.setattr(ad_copy,'settings',lambda:SimpleNamespace(openai_api_key='test',openai_model='configured-model'))
    response=httpx.Response(200,request=httpx.Request('POST','https://api.openai.com/v1/responses'),json={'output':[]})
    with patch('app.ad_copy.httpx.post',return_value=response):
        with pytest.raises(ad_copy.CopyUnavailable):ad_copy.generate_copy({},'warm',15)
