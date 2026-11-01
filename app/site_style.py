"""Bounded art directions shared by generated websites and offline video captures."""
import re

DIRECTION_LABELS={'editorial':'Éditorial','minimal':'Minimaliste','luxury':'Élégant','organic':'Organique','vibrant':'Expressif','technical':'Technique','brutalist':'Brutaliste','playful':'Ludique'}
DIRECTIONS=('editorial','minimal','luxury','organic','vibrant','technical','brutalist','playful')
HEADINGS={'elegant':'Georgia,serif','classic':'Palatino,"Book Antiqua",serif','modern':'Arial,Helvetica,sans-serif',
          'humanist':'"Trebuchet MS",Arial,sans-serif','mono':'"Courier New",monospace'}
BODIES={'sans':'Arial,Helvetica,sans-serif','humanist':'"Trebuchet MS",Arial,sans-serif','serif':'Georgia,serif'}
PALETTES={
    'editorial':{'background':'#f3eee5','surface':'#fffcf7','ink':'#29231e','muted':'#665d53','accent':'#984c2c','accent_text':'#ffffff','border':'#c9beb0'},
    'minimal':{'background':'#fafafa','surface':'#ffffff','ink':'#1b2531','muted':'#526071','accent':'#2449b1','accent_text':'#ffffff','border':'#d6dce4'},
    'luxury':{'background':'#f2eee7','surface':'#fffcf7','ink':'#29231c','muted':'#685b49','accent':'#68522b','accent_text':'#ffffff','border':'#c7baa4'},
    'organic':{'background':'#edf1e7','surface':'#fcfdf8','ink':'#26392c','muted':'#52604c','accent':'#386346','accent_text':'#ffffff','border':'#bdcbb6'},
    'vibrant':{'background':'#fff3ea','surface':'#fffdf7','ink':'#2c1744','muted':'#695273','accent':'#7b2ba3','accent_text':'#ffffff','border':'#dabed6'},
    'technical':{'background':'#edf3f7','surface':'#ffffff','ink':'#162c3d','muted':'#496070','accent':'#075a86','accent_text':'#ffffff','border':'#b4cad8'},
    'brutalist':{'background':'#f6f3df','surface':'#fffdf3','ink':'#17221b','muted':'#4f594b','accent':'#d5ee48','accent_text':'#17221b','border':'#17221b'},
    'playful':{'background':'#fff0ef','surface':'#fffaf5','ink':'#422534','muted':'#795464','accent':'#a43152','accent_text':'#ffffff','border':'#e1b9bc'},
}
STYLE_IDEAS=[
    {'direction':'editorial','hero_style':'editorial','layout_style':'editorial','heading_font':'elegant','note':'Grands titres, composition de magazine, filets fins et images alternées.'},
    {'direction':'minimal','hero_style':'centered','layout_style':'minimal','heading_font':'modern','note':'Beaucoup d’espace, peu de cadres, typographie sobre et contenu hiérarchisé.'},
    {'direction':'luxury','hero_style':'full_image','layout_style':'showcase','heading_font':'classic','note':'Immersion photographique, navigation discrète, élégance et détails soignés.'},
    {'direction':'organic','hero_style':'split','layout_style':'editorial','heading_font':'humanist','note':'Formes organiques, teintes naturelles et rythme doux.'},
    {'direction':'vibrant','hero_style':'mosaic','layout_style':'magazine','heading_font':'modern','note':'Mosaïque visuelle, contrastes colorés et titres affirmés.'},
    {'direction':'technical','hero_style':'service_first','layout_style':'service_grid','heading_font':'mono','note':'Structure fonctionnelle, grille précise et services immédiatement accessibles.'},
    {'direction':'brutalist','hero_style':'editorial','layout_style':'minimal','heading_font':'modern','note':'Typographie massive, traits francs, angles droits et composition sans fioriture.'},
    {'direction':'playful','hero_style':'mosaic','layout_style':'cards','heading_font':'humanist','note':'Composition ludique, formes arrondies et couleurs joyeuses.'},
]


def contrast(a,b):
    def luminance(value):
        rgb=[int(value[i:i+2],16)/255 for i in (1,3,5)]
        rgb=[n/12.92 if n<=.04045 else ((n+.055)/1.055)**2.4 for n in rgb]
        return sum(n*w for n,w in zip(rgb,(.2126,.7152,.0722)))
    high,low=sorted((luminance(a),luminance(b)),reverse=True)
    return (high+.05)/(low+.05)


def website_art(site):
    raw=site.get('visual_identity')
    raw=raw if isinstance(raw,dict) else {}
    direction=raw.get('direction')
    direction=direction if direction in DIRECTIONS else 'minimal'
    palette=dict(PALETTES[direction])
    colors=raw.get('palette')
    if isinstance(colors,dict):
        for key in palette:
            value=colors.get(key)
            if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value):palette[key]=value
    if contrast(palette['ink'],palette['background'])<4.5:
        palette['ink']=max(('#101010','#ffffff'),key=lambda color:contrast(color,palette['background']))
    # One foreground must stay legible on both body and panel surfaces.
    if contrast(palette['ink'],palette['surface'])<4.5:
        palette['surface']=palette['background']
    if min(contrast(palette['muted'],palette[bg]) for bg in ('background','surface'))<4.5:
        palette['muted']=palette['ink']
    if contrast(palette['accent_text'],palette['accent'])<4.5:
        palette['accent_text']=max(('#101010','#ffffff'),key=lambda color:contrast(color,palette['accent']))
    def choice(key,allowed,default):
        value=raw.get(key)
        return value if isinstance(value,str) and value in allowed else default
    return {'direction':direction,'label':DIRECTION_LABELS[direction],'palette':palette,
            'heading_font':HEADINGS[choice('heading_font',HEADINGS,'modern')],
            'body_font':BODIES[choice('body_font',BODIES,'sans')],
            'density':choice('density',('airy','balanced','compact'),'balanced'),
            'header_style':choice('header_style',('inline','centered','stacked'),'inline'),
            'button_style':choice('button_style',('square','soft','pill'),'soft'),
            'image_style':choice('image_style',('photography','illustration','graphic','none'),'photography'),
            'rationale':raw.get('rationale','')[:500] if isinstance(raw.get('rationale',''),str) else ''}
