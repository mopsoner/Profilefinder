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
    return [{'page_index': i % len(pages), 'caption': ' '.join(group),
             'duration': duration * weights[i] / sum(weights)} for i, group in enumerate(groups)]


def validate_slides(slides, page_count, duration):
    if not isinstance(slides, list) or not 1 <= len(slides) <= 8:
        raise ValueError('Choisissez entre 1 et 8 slides.')
    if len(slides) * .5 > duration:
        raise ValueError('L’audio est trop court pour autant de slides (0,5 seconde minimum par slide).')
    result = []
    for slide in slides:
        if not isinstance(slide, dict):
            raise ValueError('Slide invalide.')
        index, caption, seconds = slide.get('page_index'), slide.get('caption'), slide.get('duration')
        if type(index) is not int or not 0 <= index < page_count:
            raise ValueError('Page de site invalide.')
        if not isinstance(caption, str) or not caption.strip() or len(caption) > 700:
            raise ValueError('Chaque slide doit contenir entre 1 et 700 caractères.')
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not .5 <= seconds <= 300:
            raise ValueError('Durée de slide invalide (0,5 à 300 secondes).')
        result.append({'page_index': index, 'caption': caption.strip(), 'duration': seconds})
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


def compose_slides(directory, slides, lead, format_name):
    from playwright.sync_api import sync_playwright
    width, height = FORMATS[format_name]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('chromium-browser'), args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            page = browser.new_page(viewport={'width': width, 'height': height}, java_script_enabled=False)
            page.route('**/*', lambda route: route.abort())
            for index, slide in enumerate(slides):
                image = base64.b64encode((directory / f'page-{slide["page_index"]}.png').read_bytes()).decode()
                font_size = max(28, round((64 if height > width else 58) * min(1, math.sqrt(160 / max(160, len(slide['caption']))))))
                html = templates.get_template('video_slide.html').render(image=image, lead=lead, caption=slide['caption'], index=index+1, count=len(slides), portrait=height>width, font_size=font_size)
                page.set_content(html, wait_until='load')
                page.screenshot(path=str(directory / f'slide-{index}.png'), animations='disabled')
        finally:
            browser.close()


def encode_video(directory, audio_path, slides, duration, progress):
    for index, slide in enumerate(slides):
        # Round upward so that the joined video always covers the complete audio.
        seconds = math.ceil(slide['duration'] * 30) / 30
        fade = min(.22, seconds / 4)
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '30', '-i', str(directory / f'slide-{index}.png'), '-t', str(seconds), '-vf', f'fade=t=in:d={fade},fade=t=out:st={seconds-fade}:d={fade},format=yuv420p', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-threads', '2', '-an', str(directory / f'clip-{index}.mp4')], capture_output=True, timeout=600, check=True)
        progress(round((index+1)/len(slides)*90))
    (directory / 'concat.txt').write_text(''.join(f"file 'clip-{i}.mp4'\n" for i in range(len(slides))))
    output = directory / 'output.tmp.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', str(directory / 'concat.txt'), '-i', str(audio_path), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', str(duration), '-movflags', '+faststart', str(output)], capture_output=True, timeout=120, check=True)
    output.replace(directory / 'spot.mp4')
    for clip in directory.glob('clip-*.mp4'):
        clip.unlink()
