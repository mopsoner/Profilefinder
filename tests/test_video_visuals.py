import base64
import json
import struct
from types import SimpleNamespace
from unittest.mock import patch
import zlib
import httpx
import pytest
from app import video_visuals
from app.video_render import validate_slides, templates


def png():
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x90\x70\x50'*2)*2))+chunk(b'IEND',b'')


@pytest.fixture
def cfg(monkeypatch):
    value=SimpleNamespace(openai_api_key='test',openai_model='configured-model',openai_image_model='configured-image-model',video_ai_max_images=4)
    monkeypatch.setattr(video_visuals,'settings',lambda:value)
    return value


def test_planner_requests_full_frame_visuals_and_short_text(cfg):
    data={'shots':[{'index':0,'on_screen_text':'Le goût des saisons','image_prompt':'Cinematic close-up of seasonal ingredients, warm natural light.','text_position':'left'}]}
    response=httpx.Response(200,request=httpx.Request('POST','https://api.openai.com/v1/responses'),json={'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(data)}]}]})
    with patch('app.video_visuals.httpx.post',return_value=response) as send:
        result=video_visuals.plan_shots({'theme':'warm'},[{'caption':'Notre cuisine met en avant les produits de saison.'}],{'name':'Restaurant'})
    assert result==data['shots']
    assert 'plein écran' in send.call_args.kwargs['json']['instructions']
    assert '7 mots' in send.call_args.kwargs['json']['instructions']
    assert send.call_args.kwargs['json']['model']=='configured-model'


def test_image_generator_uses_image_model_and_portrait_format(cfg,tmp_path):
    response=httpx.Response(200,request=httpx.Request('POST','https://api.openai.com/v1/images/generations'),json={'data':[{'b64_json':base64.b64encode(png()).decode()}]})
    with patch('app.video_visuals.httpx.post',return_value=response) as send:
        video_visuals.generate_image('Cinematic food photography.','portrait',tmp_path/'visual.png')
    assert (tmp_path/'visual.png').read_bytes()==png()
    assert send.call_args.kwargs['json']['model']=='configured-image-model'
    assert send.call_args.kwargs['json']['size']=='1024x1536'


def test_cached_images_survive_overlay_edits_and_reordering(cfg,tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(video_visuals,'plan_shots',lambda site,slides,lead:[{'index':i,'on_screen_text':'Quelques mots','image_prompt':'Original image '+s['caption'],'text_position':'left'} for i,s in enumerate(slides)])
    def image(prompt,format_name,path):calls.append(prompt);path.write_bytes(png())
    monkeypatch.setattr(video_visuals,'generate_image',image)
    slides=[{'caption':'Premier passage','layout':'intro'},{'caption':'Deuxième passage','layout':'cta'}]
    video_visuals.ensure_shots(tmp_path,{},slides,{'name':'Entreprise'},'portrait')
    assert len(calls)==2
    slides[0]['on_screen_text']='Mon texte modifié'
    slides.reverse()
    video_visuals.ensure_shots(tmp_path,{},slides,{'name':'Entreprise'},'portrait')
    assert len(calls)==2 and slides[1]['on_screen_text']=='Mon texte modifié'
    assert [s['visual_index'] for s in slides]==[1,0]


def test_overlays_are_separate_from_narration_and_bounded():
    slide={'caption':'Ce texte complet reste associé à la voix off.','on_screen_text':'Un message court','text_position':'none','page_index':0,'duration':3,'_shot_key':'a'*64}
    result=validate_slides([slide],1,3)[0]
    assert result['caption']==slide['caption'] and result['on_screen_text']=='Un message court'
    assert result['text_position']=='none' and result['_shot_key']=='a'*64
    with pytest.raises(ValueError):validate_slides([{**slide,'on_screen_text':'un deux trois quatre cinq six sept huit'}],1,3)


def test_cinematic_template_has_no_presentation_frame_or_counter():
    art={'image':'data:image/png;base64,'+base64.b64encode(png()).decode(),'headline':'Le goût des saisons','text_position':'left','serif':True,'show_contact':False}
    html=templates.get_template('video_shot.html').render(art=art,lead={'name':'Entreprise','phone':'0123456789'},index=2,count=4,portrait=True,headline_size=90)
    assert 'Le goût des saisons' in html
    assert 'website-frame' not in html and 'class="counter"' not in html
    assert '0123456789' not in html
