import json
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from app import creative_brief, site_generator
from app.video_direction import identity


def options(**changes):
    return {'theme':'warm','motion':'calm','transition':'fade','typography':'serif','composition':'editorial','text_size':'large','accent_color':'#bd8756','show_contact':False,'note':'',**changes}


def response(value):
    return httpx.Response(200,request=httpx.Request('POST','https://api.openai.com/v1/responses'),json={'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]})


def test_client_brief_is_optional_and_bounded():
    assert creative_brief.clean_brief('  ') == ''
    assert creative_brief.clean_brief('  Clair et élégant. ') == 'Clair et élégant.'
    for value in (None,123,'x'*3001):
        with pytest.raises(ValueError): creative_brief.clean_brief(value)


def test_video_brief_maps_to_safe_renderer_options(monkeypatch):
    monkeypatch.setattr(creative_brief,'settings',lambda:SimpleNamespace(openai_api_key='test',openai_model='configured-model'))
    with patch('app.creative_brief.httpx.post',return_value=response(options())) as send:
        result=creative_brief.video_direction_from_brief('Beige, élégant, lent et sans téléphone.',{'theme':'dark'})
    assert result==options()
    assert 'Beige, élégant' in send.call_args.kwargs['json']['input']
    assert send.call_args.kwargs['json']['model']=='configured-model'
    site={'theme':'dark','design':'fitness','_video_direction':result}
    art=identity(site)
    assert art['theme']=='warm' and art['serif'] is True
    assert art['accent']=='#bd8756' and art['show_contact'] is False
    assert site['theme']=='dark'  # Video instructions do not change the client's website.


def test_unsafe_or_unavailable_direction_is_reported(monkeypatch):
    monkeypatch.setattr(creative_brief,'settings',lambda:SimpleNamespace(openai_api_key='test',openai_model='model'))
    with patch('app.creative_brief.httpx.post',return_value=response(options(accent_color='red;display:none'))):
        with pytest.raises(ValueError): creative_brief.video_direction_from_brief('Rouge',{})
    monkeypatch.setattr(creative_brief,'settings',lambda:SimpleNamespace(openai_api_key=''))
    with patch('app.creative_brief.httpx.post') as send:
        with pytest.raises(ValueError): creative_brief.video_direction_from_brief('Élégant',{})
        send.assert_not_called()


def test_website_receives_the_client_brief(monkeypatch):
    monkeypatch.setattr(site_generator,'settings',lambda:SimpleNamespace(openai_api_key='test',openai_model='model'))
    lead=SimpleNamespace(name='Entreprise',business_type='restaurant',city='Paris',address='',phone='',rating=None,reviews_count=0,website=None)
    with patch('app.site_generator.httpx.post',return_value=response({'site_title':'Entreprise','visual_identity':{},'pages':[{}, {}, {}]})) as send:
        site_generator.generate_lead_website(lead,{},'Un site clair avec une page services détaillée.')
    body=send.call_args.kwargs['json']
    assert 'page services détaillée' in body['input']
    assert 'brief créatif du client' in body['instructions']
