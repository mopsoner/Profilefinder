"""Compose original advertising scenes from a site's visual identity and narration."""
import base64
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS = ('intro', 'spotlight', 'editorial', 'statement', 'cta', 'website')
LAYOUT_NAMES = {'intro':'Accroche', 'spotlight':'Bénéfice', 'editorial':'Éditorial', 'statement':'Message fort', 'cta':'Appel à l’action', 'website':'Site en situation'}
PALETTES = {
    'dark': ('#080a12','#f7f8ff','#70f0ff','#111522','#aeb4ca'),
    'light': ('#f7f3ec','#171512','#9d542d','#e8e0d5','#625d55'),
    'warm': ('#f7f3ec','#171512','#b56439','#e9dac8','#75604e'),
    'natural': ('#101811','#f5f5ef','#a9cc88','#263327','#b4c1a5'),
    'luxury': ('#0e0c0a','#f7f0e5','#d9ba7d','#252019','#b8a78e'),
    'bold': ('#111111','#ffffff','#d4f75b','#28282b','#aeb1b9'),
}


def identity(site):
    options=site.get('_video_direction') or {}
    theme = options.get('theme') if options.get('theme') not in (None,'site') else site.get('theme','dark')
    bg, fg, accent, surface, muted = PALETTES.get(theme, PALETTES['dark'])
    custom = options.get('accent_color') or site.get('accent_color')
    if isinstance(custom,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',custom):
        accent = custom
    design = site.get('design','general')
    serif=design in ('restaurant','hospitality','beauty')
    if options.get('typography') in ('serif','sans'):
        serif=options['typography']=='serif'
    return {'theme':theme if theme in PALETTES else 'dark', 'bg':bg, 'fg':fg, 'accent':accent,
            'surface':surface, 'muted':muted, 'serif':serif, 'show_contact':options.get('show_contact',True),
            'uppercase':design in ('automotive','trades','fitness')}


def scene_layout(index, count):
    if index == count-1 and count > 1:
        return 'cta'
    if index == 0:
        return 'intro'
    return ('spotlight','editorial','statement')[(index-1)%3]


def local_image(src):
    if not isinstance(src,str) or not src.startswith('/static/generated/'):
        return None
    path = (ROOT/'app'/src.lstrip('/')).resolve()
    if not path.is_relative_to((ROOT/'app/static/generated').resolve()) or not path.is_file() or path.stat().st_size>12*1024*1024:
        return None
    mime = {'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}.get(path.suffix.lower())
    return 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode() if mime else None


def direction(site, pages, slide, index, count):
    page = pages[slide['page_index']]
    words = slide['caption'].split()
    layout=slide.get('layout') or scene_layout(index,count)
    clause=re.split(r'[,;.!?]',slide['caption'])[0].strip()
    if layout=='cta' and isinstance(site.get('site_title'),str) and len(site['site_title'])<70:
        headline='Découvrez '+site['site_title']
    elif layout not in ('intro','cta') and isinstance(page.get('title'),str) and len(page['title'])<=100:
        headline=page['title']
    elif 2<=len(clause.split())<=11:
        headline=clause
    else:
        chosen=words[:9]
        while len(chosen)>3 and chosen[-1].lower().strip(',.!?;:') in ('de','du','des','et','un','une','le','la','les','à','au','aux','pour','en'):
            chosen.pop()
        headline=' '.join(chosen).rstrip(',.!?;:')
    title_words = headline.split()
    sections = page.get('sections') or []
    image = None
    for section in sections:
        if isinstance(section,dict):
            image=local_image(section.get('image_url'))
            if image:
                break
    return {**identity(site), 'layout':layout,
            'headline_prefix':' '.join(title_words[:-2]), 'headline_accent':' '.join(title_words[-2:]),
            'headline':headline, 'support':slide['caption'] if headline.strip('.!? ')!=slide['caption'].strip('.!? ') else '',
            'page_title':str(page.get('nav_label') or page.get('title') or 'Notre univers')[:90],
            'image':image, 'index':index+1, 'count':count}
