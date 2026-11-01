"""Ads Studio: static UI, OpenAI-first voice generation, local FFmpeg mixing."""
import base64
import binascii
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error

ROOT = Path(__file__).resolve().parent
MAX_AUDIO = 20 * 1024 * 1024


def decode_audio(value):
    if not isinstance(value, str) or len(value) > (MAX_AUDIO * 4 // 3 + 8):
        raise ValueError('Fichier audio absent ou supérieur à 20 Mo.')
    try:
        audio = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Encodage du fichier audio invalide.')
    if not audio or len(audio) > MAX_AUDIO:
        raise ValueError('Le fichier audio est vide ou dépasse 20 Mo.')
    return audio


def volume(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError('Volume audio invalide.')
    return value


def mix_audio(data):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg et ffprobe doivent être installés sur le serveur.')
    voice = decode_audio(data.get('voice'))
    music = decode_audio(data['music']) if data.get('music') else None
    voice_volume = volume(data.get('voice_volume', 1), 1.5)
    music_volume = volume(data.get('music_volume', .18), 1)
    with tempfile.TemporaryDirectory(prefix='ads-') as directory:
        root = Path(directory)
        (root / 'voice').write_bytes(voice)
        try:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries', 'format=duration', '-of', 'json', str(root / 'voice')], capture_output=True, timeout=15, check=True)
            duration = float(json.loads(probe.stdout)['format']['duration'])
            if not math.isfinite(duration) or not 0 < duration <= 300:
                raise ValueError('La voix off doit durer entre 0 et 300 secondes.')
            cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-i', str(root / 'voice')]
            filters = f'[0:a]aresample=44100,aformat=channel_layouts=stereo,volume={voice_volume}[voice];'
            if music:
                (root / 'music').write_bytes(music)
                cmd += ['-stream_loop', '-1', '-protocol_whitelist', 'file,pipe', '-i', str(root / 'music')]
                filters += f'[1:a]aresample=44100,aformat=channel_layouts=stereo,volume={music_volume},afade=t=in:d=0.5,afade=t=out:st={max(0, duration-1)}:d=1[music];'
                if data.get('duck', True):
                    filters += '[voice]asplit=2[spoken][side];[music][side]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[bed];[spoken][bed]amix=inputs=2:duration=first:normalize=0[sum];'
                else:
                    filters += '[voice][music]amix=inputs=2:duration=first:normalize=0[sum];'
                filters += '[sum]alimiter=limit=0.95:level=0[out]'
            else:
                filters += '[voice]alimiter=limit=0.95:level=0[out]'
            cmd += ['-filter_complex', filters, '-map', '[out]', '-t', str(duration), '-c:a', 'libmp3lame', '-b:a', '192k', str(root / 'spot.mp3')]
            subprocess.run(cmd, capture_output=True, timeout=90, check=True)
            return (root / 'spot.mp3').read_bytes()
        except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError):
            raise ValueError('Fichier audio illisible. Importez une voix et une musique valides.')
        except subprocess.TimeoutExpired:
            raise ValueError('Le traitement audio a dépassé le délai autorisé.')


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, content_type='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/static/light-theme.css':
            self.send(200, (ROOT.parent / 'app/static/light-theme.css').read_bytes(), 'text/css')
            return
        if path in ('/favicon.ico', '/static/favicon.svg'):
            self.send(200, (ROOT.parent / 'app/static/favicon.svg').read_bytes(), 'image/svg+xml')
            return
        if path == '/api/status':
            from app.voice import voice_status
            self.send(200, voice_status())
            return
        shared = {'/theme.css': ('theme.css', 'text/css'), '/layout.js': ('layout.js', 'text/javascript')}
        if path in shared:
            name, mime = shared[path]
            self.send(200, (ROOT.parent / 'shared' / name).read_bytes(), mime)
            return
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/ads': ('index.html', 'text/html; charset=utf-8'), '/ads/': ('index.html', 'text/html; charset=utf-8'), '/style.css': ('style.css', 'text/css'), '/app.js': ('app.js', 'text/javascript')}
        if path not in files:
            self.send(404, {'error': 'Page introuvable.'})
            return
        name, mime = files[path]
        self.send(200, (ROOT / name).read_bytes(), mime)

    def do_POST(self):
        # Local development service: prevent cross-origin requests from spending API credits.
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://' + self.headers.get('Host', ''), 'https://' + self.headers.get('Host', '')):
            self.send(403, {'error': 'Origine non autorisée.'})
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.send(415, {'error': 'Une requête JSON est requise.'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 57 * 1024 * 1024:
                raise ValueError('Requête absente ou trop volumineuse.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Objet JSON attendu.')
            if self.path == '/api/mix':
                self.send(200, mix_audio(data), 'audio/mpeg')
            elif self.path == '/api/voice':
                from app.voice import synthesize, VoiceUnavailable
                try:
                    self.send(200, synthesize(data), 'audio/mpeg')
                except VoiceUnavailable as error:
                    self.send(503, {'error': str(error)})
            else:
                self.send(404, {'error': 'Route introuvable.'})
        except (ValueError, UnicodeDecodeError):
            self.send(400, {'error': 'Données invalides. Vérifiez vos fichiers audio, leur durée (5 min max.) et les champs saisis.'})
        except urllib.error.HTTPError as error:
            self.send(502, {'error': f'Le moteur vocal a refusé la génération (HTTP {error.code}). Vérifiez la clé, la voix et vos crédits.'})
        except (urllib.error.URLError, TimeoutError):
            self.send(502, {'error': 'Le moteur vocal est injoignable. Vérifiez la connexion réseau du serveur.'})
        except Exception:
            self.send(500, {'error': 'Le traitement a échoué. Réessayez avec un autre fichier audio.'})


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT.parent))
    host = os.environ.get('ADS_HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))
    print(f'Ads Studio démarré sur {host}:{port}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
