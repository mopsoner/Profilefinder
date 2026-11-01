"""Local HD page captures, slide composition and MP4 encoding. No paid API calls."""
import base64
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from jinja2 import Environment, FileSystemLoader, select_autoescape
from .config import settings
from .video_direction import direction, scene_layout, LAYOUTS

ROOT = Path(__file__).resolve().parent.parent
MEDIA = (ROOT / settings().ads_media_root).resolve()
FORMATS = {'portrait': (1080, 1920), 'landscape': (1920, 1080), 'square': (1080, 1080)}
templates = Environment(loader=FileSystemLoader(ROOT / 'app/templates'), autoescape=select_autoescape(['html']))


def audio_duration(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries', 'format=duration', '-of', 'json', str(path)], capture_output=True, check=True, timeout=20)
    duration = float(json.loads(result.stdout)['format']['duration'])
    if not math.isfinite(duration) or not 1 <= duration <= 300:
        raise ValueError('L’audio doit durer entre 1 seconde et 5 minutes.')
    return duration


def site_pages(site, name):
    raw_pages = site.get('pages') or []
    pages = [p for p in raw_pages if isinstance(p, dict)] if isinstance(raw_pages, list) else []
    if not pages:
        pages = [{'slug': 'accueil', 'nav_label': 'Accueil', 'title': site.get('headline') or name,
                  'intro': site.get('subheadline') or site.get('about_text') or '', 'sections': []}]
    return pages[:8]


def split_script(script, pages, duration):
    # Balanced word groups keep all narration, including scripts without punctuation.
    words = []
    for token in script.split():
        if words and re.fullmatch(r'[.,!?;:]+', token):
            words[-1] += ' ' + token
        else:
            words.append(token)
    count = min(8, max(len(pages), math.ceil(len(words) / 24)), max(1, int(duration / 2)), max(1, len(words) // 4))
    groups = [words[round(i * len(words) / count):round((i + 1) * len(words) / count)] for i in range(count)]
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())
    if len(sentences) >= count:
        groups = [' '.join(sentences[round(i * len(sentences) / count):round((i+1) * len(sentences) / count)]).split() for i in range(count)]
    weights = [max(1, len(group)) for group in groups]
    return [{'page_index': i % len(pages), 'caption': ' '.join(group), 'layout':scene_layout(i,len(groups)),
             'duration': duration * weights[i] / sum(weights)} for i, group in enumerate(groups)]


def validate_slides(slides, page_count, duration):
    if not isinstance(slides, list) or not 1 <= len(slides) <= 8:
        raise ValueError('Choisissez entre 1 et 8 slides.')
    if len(slides) * .5 > duration:
        raise ValueError('L’audio est trop court pour autant de slides (0,5 seconde minimum par slide).')
    result = []
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise ValueError('Slide invalide.')
        index, caption, seconds = slide.get('page_index'), slide.get('caption'), slide.get('duration')
        if type(index) is not int or not 0 <= index < page_count:
            raise ValueError('Page de site invalide.')
        if not isinstance(caption, str) or not caption.strip() or len(caption) > 700:
            raise ValueError('Chaque slide doit contenir entre 1 et 700 caractères.')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not .5 <= seconds <= 300:
            raise ValueError('Durée de slide invalide (0,5 à 300 secondes).')
        layout=slide.get('layout') or scene_layout(len(result),len(slides))
        if not isinstance(layout,str) or layout not in LAYOUTS:
            raise ValueError('Style de scène invalide.')
        result.append({'page_index': index, 'caption': caption.strip(), 'duration': seconds, 'layout':layout})
    # Scale proportionally, clamping short slides without changing already normalized timings.
    pending = list(range(len(result)))
    remaining = duration
    while pending:
        total = sum(result[i]['duration'] for i in pending)
        short = [i for i in pending if remaining * result[i]['duration'] / total < .5]
        if not short:
            values = {i: remaining * result[i]['duration'] / total for i in pending}
            for i, seconds in values.items():
                result[i]['duration'] = seconds
            break
        for i in short:
            result[i]['duration'] = .5
            remaining -= .5
            pending.remove(i)
    return result


def embed_local_images(html):
    # Only cached, locally generated images are embedded. Capture workers never browse the network.
    def replace(match):
        src = match[1]
        if src.startswith('/static/generated/'):
            path = (ROOT / 'app' / src.lstrip('/')).resolve()
            allowed = (ROOT / 'app/static/generated').resolve()
            if path.is_relative_to(allowed) and path.is_file() and path.stat().st_size <= 12 * 1024 * 1024:
                mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(path.suffix.lower())
                if mime:
                    return 'src="data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode() + '"'
        return 'src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'10\' height=\'10\'%3E%3C/svg%3E"'
    return re.sub(r'src="([^"]*)"', replace, html)


def capture_pages(directory, site, lead, progress, format_name='landscape'):
    from playwright.sync_api import sync_playwright
    pages = site_pages(site, lead['name'])
    site = {**site, 'site_title': site.get('site_title') or lead['name']}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('chromium-browser'), args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            capture_size = {'portrait': {'width':1440, 'height':1600}, 'square': {'width':1440, 'height':1440}, 'landscape': {'width':1920, 'height':1080}}[format_name]
            page = browser.new_page(viewport=capture_size, device_scale_factor=1, java_script_enabled=False)
            page.route('**/*', lambda route: route.abort())
            for index, current in enumerate(pages):
                html = templates.get_template('lead_web.html').render(lead=lead, site=site, pages=pages, page=current, photo_count=0)
                page.set_content(embed_local_images(html), wait_until='load', timeout=20000)
                page.screenshot(path=str(directory / f'page-{index}.png'), animations='disabled')
                progress(round((index + 1) / len(pages) * 100))
        finally:
            browser.close()
    return pages


def compose_slides(directory, slides, lead, format_name, site=None, progress=lambda _:None):
    from playwright.sync_api import sync_playwright
    width, height = FORMATS[format_name]
    site=site or {}
    pages=site_pages(site,lead['name'])
    while len(pages)<=max(s['page_index'] for s in slides):
        pages.append({'title':'Notre univers','sections':[]})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('chromium-browser'), args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            page = browser.new_page(viewport={'width':width,'height':height}, java_script_enabled=False)
            page.route('**/*', lambda route: route.abort())
            for index, slide in enumerate(slides):
                art=direction(site,pages,slide,index,len(slides))
                image=base64.b64encode((directory/f'page-{slide["page_index"]}.png').read_bytes()).decode() if art['layout']=='website' else ''
                headline_size=max(52,round((122 if height>width else 98)*min(1,math.sqrt(75/max(75,len(art['headline']))))))
                body_size=max(24 if height>width else 19,round((40 if height>width else 31)*min(1,math.sqrt(200/max(200,len(art['support']))))))
                if (site.get('_video_direction') or {}).get('text_size')=='large':
                    headline_size=round(headline_size*1.15)
                    body_size=round(body_size*1.12)
                html=templates.get_template('video_slide.html').render(art=art,lead=lead,index=index+1,count=len(slides),portrait=height>width,headline_size=headline_size,body_size=body_size,website_image=image,width=width,height=height)
                page.set_content(html,wait_until='load')
                for attempt in range(12):
                    fits=page.evaluate('''() => {
                        const content=document.querySelector('.copy-content').getBoundingClientRect();
                        const top=document.querySelector('header').getBoundingClientRect().bottom+28;
                        const bottom=document.querySelector('footer').getBoundingClientRect().top-28;
                        return content.top>=top && content.bottom<=bottom;
                    }''')
                    if fits:
                        break
                    page.evaluate('''() => {
                        for(const selector of ['h1','.support']){
                            const el=document.querySelector(selector);
                            if(el)el.style.fontSize=(parseFloat(getComputedStyle(el).fontSize)*0.9)+'px';
                        }
                    }''')
                if not fits:
                    raise ValueError('Le texte de cette scène est trop long pour le format choisi. Raccourcissez-le avant le rendu.')
                page.screenshot(path=str(directory/f'slide-{index}.png'),animations='disabled',omit_background=True)
                # Export independent layers: camera movement never moves or blurs the typography.
                for layer,filename in (('scene-bg','background'),('scene-copy','copy'),('scene-chrome','chrome')):
                    for name in ('scene-bg','scene-copy','scene-chrome'):
                        page.locator('.'+name).evaluate('(el, visible) => el.style.visibility=visible?"visible":"hidden"',name==layer)
                    page.screenshot(path=str(directory/f'{filename}-{index}.png'),omit_background=True,animations='disabled')
                progress(round((index+1)/len(slides)*100))
        finally:
            browser.close()


def scene_timing(slides,duration,fps=30):
    boundaries=[0]
    for index in range(len(slides)):
        cumulative=sum(s['duration'] for s in slides[:index+1])
        boundaries.append(math.ceil(duration*fps) if index==len(slides)-1 else round(cumulative*fps))
    frames=[boundaries[i+1]-boundaries[i] for i in range(len(slides))]
    overlap=min(12,min(frames)//3) if len(slides)>1 else 0
    return frames,overlap


def encode_video(directory,audio_path,slides,duration,progress,options=None):
    options=options or {}
    fps=30
    frames,overlap=scene_timing(slides,duration,fps)
    width,height=None,None
    for index,slide in enumerate(slides):
        total_frames=frames[index]+(overlap if index<len(slides)-1 else 0)
        seconds=total_frames/fps
        # Frame dimensions come from the actual composed scene (all formats supported).
        if width is None:
            probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=width,height','-of','json',str(directory/f'background-{index}.png')],capture_output=True,check=True,timeout=15)
            stream=json.loads(probe.stdout)['streams'][0];width,height=stream['width'],stream['height']
        amplitude={'calm':.025,'balanced':.055,'dynamic':.09}.get(options.get('motion'),.055)
        zoom=f"1.025+{amplitude}*on/{max(1,total_frames-1)}" if index%2==0 else f"{1.025+amplitude}-{amplitude}*on/{max(1,total_frames-1)}"
        pan=f"(iw-iw/zoom)*on/{max(1,total_frames-1)}" if index%2==0 else f"(iw-iw/zoom)*(1-on/{max(1,total_frames-1)})"
        entrance=min({'calm':.8,'balanced':.55,'dynamic':.3}.get(options.get('motion'),.55),seconds/3)
        filters=(f"[0:v]scale={width*2}:{height*2},zoompan=z='{zoom}':x='{pan}':y='(ih-ih/zoom)/2':d=1:s={width}x{height}:fps={fps},format=yuv420p[bg];"
                 f"[1:v]format=rgba,fade=t=in:st=0:d={entrance}:alpha=1[copy];"
                 f"[bg][copy]overlay=x=0:y='max(0,48*(1-t/{entrance}))':eval=frame:shortest=1[motion];"
                 f"[motion][2:v]overlay=0:0:shortest=1,format=yuv420p[out]")
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-filter_complex_threads','1']
        for name in ('background','copy','chrome'):
            cmd+=['-loop','1','-framerate',str(fps),'-i',str(directory/f'{name}-{index}.png')]
        cmd+=['-filter_complex',filters,'-map','[out]','-frames:v',str(total_frames),'-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-an',str(directory/f'clip-{index}.mp4')]
        subprocess.run(cmd,capture_output=True,timeout=600,check=True)
        progress(round((index+1)/len(slides)*75))
    assemble_video(directory,audio_path,frames,overlap,duration,options)
    progress(100)
    for clip in directory.glob('clip-*.mp4'):
        clip.unlink()


def assemble_video(directory,audio_path,frames,overlap,duration,options=None):
    options=options or {}
    fps=30
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y','-filter_complex_threads','1']
    for index in range(len(frames)):
        cmd+=['-threads','1','-i',str(directory/f'clip-{index}.mp4')]
    cmd+=['-i',str(audio_path)]
    filters=';'.join(f'[{i}:v]setpts=PTS-STARTPTS,fps=30[v{i}]' for i in range(len(frames)))+';'
    previous='v0';offset=0
    for index in range(1,len(frames)):
        offset+=frames[index-1]/fps
        transition=options.get('transition') or ('fade' if index%2 else 'smoothleft')
        filters+=f'[{previous}][v{index}]xfade=transition={transition}:duration={overlap/fps}:offset={offset},fps=30[x{index}];'
        previous=f'x{index}'
    filters+=f'[{previous}]fade=t=in:d=0.15,fade=t=out:st={max(0,duration-.2)}:d=0.2,format=yuv420p[out]'
    output=directory/'output.tmp.mp4'
    cmd+=['-filter_complex',filters,'-map','[out]','-map',f'{len(frames)}:a:0','-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-c:a','aac','-b:a','192k','-t',str(duration),'-movflags','+faststart',str(output)]
    subprocess.run(cmd,capture_output=True,timeout=900,check=True)
    output.replace(directory/'spot.mp4')
