import copy
import json
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from app import site_generator
from app.site_style import website_art, contrast, PALETTES, STYLE_IDEAS
from app.video_render import templates


def fixture_site(**changes):
    return {'site_title':'Maison Locale','tagline':'Une autre idée du quotidien','design':'restaurant','theme':'light',
            'hero_style':'split','layout_style':'editorial','radius_style':'soft',
            'visual_identity':{'direction':'minimal','palette':PALETTES['minimal'],'heading_font':'modern','body_font':'sans',
                'density':'airy','header_style':'inline','button_style':'square','image_style':'photography','rationale':'Un univers épuré demandé par le client.'},
            'pages':[{'slug':slug,'nav_label':title,'title':title,'intro':'Une cuisine de saison pensée pour les moments partagés.',
                      'sections':[{'title':'Une cuisine généreuse','text':'Le goût des produits et le plaisir de se retrouver.','items':['Une cuisine de saison','Des moments partagés'],'image_prompt':'Ingredients on a table.'}]} for slug,title in [('accueil','La simplicité a du goût'),('cuisine','Notre cuisine'),('contact','Rencontrons-nous')]],
            'cta_title':'Faisons connaissance','cta_text':'Contactez-nous pour en savoir plus.',**changes}


def provider_response(value,status='completed'):
    return httpx.Response(200,request=httpx.Request('POST',site_generator.API_URL),json={'status':status,'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]})


def test_brief_has_priority_and_recent_styles_are_in_the_generation_context(monkeypatch):
    monkeypatch.setattr(site_generator,'settings',lambda:SimpleNamespace(openai_api_key='test',openai_model='configured-model'))
    lead=SimpleNamespace(name='Maison Locale',business_type='restaurant',city='Paris',address='',phone='',rating=None,reviews_count=0,website=None)
    recent=[{'direction':'editorial','hero_style':'editorial','layout_style':'magazine'}]
    brief='Minimaliste blanc et bleu, sans empattements, pas de cartes.'
    with patch.object(site_generator.httpx,'post',return_value=provider_response(fixture_site())) as send:
        result=site_generator.generate_lead_website(lead,{},brief,style_context=recent)
    body=send.call_args.kwargs['json']
    assert brief in body['input'] and 'PRIORITAIRE' in body['instructions']
    facts=json.loads(body['input'].split('Données du prospect : ',1)[1].split('\nBrief créatif du client')[0])
    assert facts['directions_recentes_a_differencier']==recent
    assert len(facts['pistes_creatives_non_imposees'])==3
    assert all(idea['direction']!='editorial' for idea in facts['pistes_creatives_non_imposees'])
    assert result['_style_version']==2 and result['visual_identity']['direction']=='minimal'
    assert body['model']=='configured-model'
    assert 'visual_identity' in body['text']['format']['schema']['required']


@pytest.mark.parametrize('direction',PALETTES)
def test_readable_safe_palette_for_each_direction(direction):
    art=website_art({'visual_identity':{'direction':direction,'palette':PALETTES[direction]}})
    palette=art['palette']
    for foreground in ('ink','muted'):
        for background in ('background','surface'):assert contrast(palette[foreground],palette[background])>=4.5
    assert contrast(palette['accent_text'],palette['accent'])>=4.5


def test_palette_keeps_client_colors_and_repairs_bad_contrast_without_css_injection():
    raw={'direction':'playful','palette':{'background':'#ffe9ed','surface':'#ffffff','ink':'#ffe9ed','accent':'#f4c6dc','accent_text':'#ffffff','border':'red;display:none'},'heading_font':['bad'],'body_font':'Arial;display:none'}
    art=website_art({'visual_identity':raw})
    assert art['palette']['background']=='#ffe9ed' and art['palette']['accent']=='#f4c6dc'
    assert contrast(art['palette']['ink'],art['palette']['background'])>=4.5
    assert contrast(art['palette']['accent_text'],art['palette']['accent'])>=4.5
    assert 'display:none' not in json.dumps(art)
    dark=website_art({'visual_identity':{'palette':{'background':'#000000','surface':'#ffffff','ink':'#000000'}}})
    assert contrast(dark['palette']['ink'],dark['palette']['background'])>=4.5
    assert contrast(dark['palette']['ink'],dark['palette']['surface'])>=4.5


def test_new_compositions_render_and_legacy_sites_keep_the_previous_template():
    site=fixture_site(_style_version=2)
    lead={'id':1,'name':'Maison Locale','phone':'0123456789','city':'Paris'}
    for idea in STYLE_IDEAS:
        variant=copy.deepcopy(site)
        variant.update({key:idea[key] for key in ('hero_style','layout_style')})
        variant['visual_identity']['direction']=idea['direction']
        html=templates.get_template('lead_web.html').render(site=variant,pages=variant['pages'],page=variant['pages'][0],lead=lead,photo_count=0)
        assert 'website-v2' in html and 'direction-'+idea['direction'] in html
        assert 'class="section-copy"' in html and 'Contactez-nous' in html
    legacy=copy.deepcopy(site);legacy.pop('_style_version')
    html=templates.get_template('lead_web.html').render(site=legacy,pages=legacy['pages'],page=legacy['pages'][0],lead=lead,photo_count=0)
    assert 'website-v2' not in html and 'class="sections"' in html


def test_incomplete_site_does_not_replace_a_saved_website(monkeypatch):
    monkeypatch.setattr(site_generator,'settings',lambda:SimpleNamespace(openai_api_key='test',openai_model='model'))
    lead=SimpleNamespace(name='Entreprise',business_type='restaurant',city='',address='',phone='',rating=None,reviews_count=0,website=None)
    for value,status in [({'site_title':'Incomplet'},'completed'),(fixture_site(),'incomplete')]:
        with patch.object(site_generator.httpx,'post',return_value=provider_response(value,status)):
            with pytest.raises(ValueError):site_generator.generate_lead_website(lead,{})


def test_new_video_scenes_inherit_site_palette_and_font_unless_overridden():
    from app.video_direction import identity
    site=fixture_site(_style_version=2)
    art=identity(site)
    assert art['bg']==PALETTES['minimal']['background']
    assert art['accent']==PALETTES['minimal']['accent'] and art['serif'] is False
    site['_video_direction']={'theme':'dark','typography':'serif'}
    overridden=identity(site)
    assert overridden['bg']=='#080a12' and overridden['serif'] is True


def test_image_generation_follows_client_medium_and_can_be_disabled(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(site_generator,'settings',lambda:SimpleNamespace(site_ai_images=True,openai_api_key='test',site_ai_max_images=1,openai_image_model='configured-image-model'))
    site=fixture_site(_style_version=2)
    site['visual_identity']['image_style']='illustration'
    response=httpx.Response(200,request=httpx.Request('POST',site_generator.IMAGE_URL),json={'data':[]})
    with patch.object(site_generator.httpx,'post',return_value=response) as send:
        site_generator.generate_site_images(1,site)
    assert 'original editorial illustration' in send.call_args.kwargs['json']['prompt']
    assert 'realistic commercial photography' not in send.call_args.kwargs['json']['prompt']
    site['visual_identity']['image_style']='none'
    with patch.object(site_generator.httpx,'post') as send:
        site_generator.generate_site_images(1,site)
        send.assert_not_called()
    html=templates.get_template('lead_web.html').render(site=site,pages=site['pages'],page=site['pages'][0],lead={'id':1,'name':'Entreprise'},photo_count=3)
    assert 'class="hero-media"' not in html
