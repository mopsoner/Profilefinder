"""Read a public homepage's declared visual cues without executing its content."""
from collections import Counter
from functools import lru_cache
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
from time import monotonic
from urllib.parse import urljoin, urlsplit

HEX = re.compile(r'#[0-9a-fA-F]{6}(?![\w-])')


class Cues(HTMLParser):
    def __init__(self):
        super().__init__()
        self.theme = None
        self.colors = Counter()
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('name') == 'theme-color':
            color = values.get('content') or ''
            if HEX.fullmatch(color):
                self.theme = color.lower()
        self.in_style = self.in_style or tag == 'style'
        self.collect(values.get('style') or '')

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.collect(data)

    def collect(self, css):
        self.colors.update(color.lower() for color in HEX.findall(css))


def public_resource(url, media_types, max_bytes, *, truncate=False):
    accept = ', '.join(media_types)
    for _ in range(3):
        target = urlsplit(url)
        if (target.scheme not in ('http', 'https') or not target.hostname or target.username or
                target.password or target.port not in (None, 80 if target.scheme == 'http' else 443)):
            return b''
        host = target.hostname.encode('idna').decode()
        port = 443 if target.scheme == 'https' else 80
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
            return b''
        cls = http.client.HTTPSConnection if target.scheme == 'https' else http.client.HTTPConnection
        connection = cls(host, port, timeout=3)
        # Pin the verified IP while retaining the original Host and HTTPS certificate validation.
        ip = addresses[0][4][0]
        connection._create_connection = lambda address, timeout, source_address: socket.create_connection(
            (ip, port), timeout, source_address)
        try:
            path = (target.path or '/') + ('?' + target.query if target.query else '')
            connection.request('GET', path, headers={'Accept': accept, 'User-Agent': 'ProfileFinder'})
            response = connection.getresponse()
            if 300 <= response.status < 400 and response.getheader('Location'):
                url = urljoin(url, response.getheader('Location'))
                continue
            content_type = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            if response.status == 200 and content_type in media_types:
                data = response.read(max_bytes if truncate else max_bytes + 1)
                return data if len(data) <= max_bytes else b''
            return b''
        finally:
            connection.close()
    return b''



def public_homepage(url):
    return public_resource(url, ('text/html',), 128 * 1024, truncate=True).decode('utf-8', errors='replace')


@lru_cache(maxsize=128)
def cached_cues(url, hour):
    try:
        parser = Cues()
        parser.feed(public_homepage(url))
    except (OSError, ValueError, http.client.HTTPException):
        return {}
    palette = {f'color_{i}': color for i, (color, _) in enumerate(parser.colors.most_common(5), 1)}
    if parser.theme:
        palette = {'theme': parser.theme, **palette}
    return {'palette': palette, 'source': 'website'} if palette else {}


def homepage_identity(url):
    return cached_cues(url, int(monotonic() // 3600)) if url else {}
