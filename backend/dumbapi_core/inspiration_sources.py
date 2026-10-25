"""Fixed, public discovery readers. No browser, account scan or arbitrary URL fetch."""
import gzip
import hashlib
import ipaddress
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .common import APIError

MAX_BYTES, MAX_ITEMS = 900_000, 18
CATEGORIES = {'showcases': 'Showcases', 'models': 'Models', 'cad': 'CAD & making',
              'science': 'Research', 'docs': 'Docs'}
SOURCES = [{'id': 'show-hn', 'name': 'Show HN', 'category': 'showcases', 'kind': 'hn', 'url': 'https://hn.algolia.com/api/v1/search_by_date?tags=show_hn&hitsPerPage=18', 'home': 'https://news.ycombinator.com/show', 'note': 'Creator submissions; projects are not independently tested.'}, {'id': 'typesafe', 'name': 'TypeSafe', 'category': 'models', 'kind': 'blog', 'url': 'https://typesafe.ai/blog', 'home': 'https://typesafe.ai/blog', 'note': 'System One news from TypeSafe.'}, {'id': 'huggingface', 'name': 'Hugging Face', 'category': 'models', 'kind': 'rss', 'url': 'https://huggingface.co/blog/feed.xml', 'home': 'https://huggingface.co/blog', 'note': 'Open models and tooling; performance claims belong to the authors.'}, {'id': 'openai', 'name': 'OpenAI', 'category': 'models', 'kind': 'rss', 'url': 'https://openai.com/news/rss.xml', 'home': 'https://openai.com/news/', 'note': 'Official release and research news.'}, {'id': 'deepmind', 'name': 'Google DeepMind', 'category': 'science', 'kind': 'rss', 'url': 'https://deepmind.google/blog/rss.xml', 'home': 'https://deepmind.google/blog/', 'note': 'Official AI and science research reports.'}, {'id': 'freecad', 'name': 'FreeCAD', 'category': 'cad', 'kind': 'rss', 'url': 'https://blog.freecad.org/feed/', 'home': 'https://blog.freecad.org/', 'note': 'CAD project updates, examples and releases.'}, {'id': 'hackaday', 'name': 'Hackaday · CAD', 'category': 'cad', 'kind': 'rss', 'url': 'https://hackaday.com/tag/cad/feed/', 'home': 'https://hackaday.com/tag/cad/', 'note': 'Editorial coverage of maker projects, with original links in the articles.'}, {'id': 'mit-health', 'name': 'MIT · Health', 'category': 'science', 'kind': 'rss', 'url': 'https://news.mit.edu/rss/topic/health', 'home': 'https://news.mit.edu/topic/health', 'note': 'Institutional research reports; not evidence of clinical availability.'}, {'id': 'docs', 'name': 'Field guide', 'category': 'docs', 'kind': 'reference', 'home': 'https://docs.typesafe.ai/', 'note': 'A curated reference shelf, not newly discovered releases.'}]
BY_ID = {s['id']: s for s in SOURCES}
REFERENCES = [
    ('System One building patterns', 'https://docs.typesafe.ai/concepts/how-to-build-with-system-one', 'TypeSafe’s guide to composing small judgments with application code.'),
    ('TypeSafe models & aliases', 'https://docs.typesafe.ai/models', 'Check the provider’s current model names, aliases and capabilities.'),
    ('Open model tooling', 'https://huggingface.co/docs/transformers/index', 'The Transformers documentation for loading and working with supported models.'),
    ('FreeCAD manual', 'https://www.freecad.org/manual/', 'A starting point for parametric modeling and FreeCAD workflows.'),
    ('Canvas experiments', 'https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API/Tutorial', 'A practical reference for drawing, animation and interactive visual experiments.'),
    ('OpenAI developer documentation', 'https://platform.openai.com/docs/overview', 'Official documentation for the provider’s supported APIs and tools.'),
]


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.skip += 1
        elif tag in ('p', 'br', 'div', 'li'): self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
        elif tag in ('p', 'div', 'li'): self.parts.append(' ')

    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def plain(value, limit=300):
    parser = Plain()
    parser.feed(str(value or '')[:20000])
    value = ' '.join(''.join(parser.parts).split())
    value = ''.join(c for c in value if ord(c) >= 32 and ord(c) != 127)
    if len(value) <= limit: return value
    return value[:limit - 1].rsplit(' ', 1)[0].rstrip(' ,;:') + '…'


def safe_url(value):
    try:
        u = urlsplit(str(value).strip())
        host = (u.hostname or '').lower().rstrip('.')
        if u.scheme not in ('http', 'https') or not host or u.username or u.password or u.port not in (None, 80, 443): return ''
        if '.' not in host or host in ('localhost', 'localhost.localdomain') or host.endswith(('.local', '.internal', '.localhost')): return ''
        try:
            if not ipaddress.ip_address(host.strip('[]')).is_global: return ''
        except ValueError: pass
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or len(value) > 1800: return ''
        if host in ('twitter.com', 'www.twitter.com', 'www.x.com'): host = 'x.com'
        query = [(k, v) for k, v in parse_qsl(u.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
        path = u.path or '/'
        if host == 'x.com' and re.fullmatch(r'/[A-Za-z0-9_]+/status/\d+/?', path): query = []
        return urlunsplit((u.scheme, host, path.rstrip('/') or '/', urlencode(query), ''))
    except (ValueError, TypeError): return ''


def stamp(value):
    try:
        try: d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError: d = parsedate_to_datetime(value)
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        # Bad/future dates must not dominate the feed.
        if not 0 < d.timestamp() <= time.time() + 86400: return None
        return d.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError, OverflowError): return None


def item(source, title, url, excerpt='', published=None, **extra):
    url, title = safe_url(url), plain(title, 220)
    if not url or not title: return None
    return {'id': 'inspiration-' + hashlib.sha256(url.encode()).hexdigest()[:28],
            'url': url, 'title': title, 'excerpt': plain(excerpt, 300),
            'published_at': stamp(published), 'source_id': source['id'], 'source_name': source['name'],
            'category': source['category'], 'provenance': 'Reference' if source['kind'] == 'reference' else 'Source preview', **extra}


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme != 'https' or new.hostname != old.hostname or new.username or new.password or new.port not in (None, 443):
            raise APIError('Source redirected outside its approved host.', 'source_redirect', 502)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(source):
    deadline = time.monotonic() + 12
    req = Request(source['url'], headers={'User-Agent': 'DumbManager-Inspiration/0.1',
                  'Accept': 'application/rss+xml,application/atom+xml,application/json,text/html', 'Accept-Encoding': 'gzip'})
    with build_opener(ProxyHandler({}), Redirects()).open(req, timeout=5) as response:
        stream = gzip.GzipFile(fileobj=response) if response.headers.get('Content-Encoding', '').lower() == 'gzip' else response
        if source['kind'] == 'rss':
            return read_rss(stream, source, deadline)
        parts, total = [], 0
        while total <= MAX_BYTES:
            part = chunk(stream, min(16384, MAX_BYTES + 1 - total), deadline)
            if not part: break
            parts.append(part); total += len(part)
        raw = b''.join(parts)
        if len(raw) > MAX_BYTES: raise APIError('Source exceeds the bounded read size.', 'source_too_large', 502)
    if source['kind'] == 'hn':
        data = json.loads(raw)
        rows = []
        for r in data.get('hits', [])[:MAX_ITEMS]:
            discussion = 'https://news.ycombinator.com/item?id=' + str(r.get('objectID', ''))
            row = item(source, re.sub(r'^Show HN:\s*', '', str(r.get('title') or '')), r.get('url') or discussion,
                       r.get('story_text') or '', r.get('created_at'), discussion_url=discussion)
            if row: rows.append(row)
        return rows
    parser = Blog(source); parser.feed(raw.decode('utf-8', errors='replace'))
    return parser.rows[:MAX_ITEMS]


def chunk(stream, size, deadline):
    if time.monotonic() > deadline:
        raise APIError('Source took too long to read.', 'source_timeout', 502)
    # read1 returns available bytes instead of waiting for an entire large block.
    return getattr(stream, 'read1', stream.read)(size)


def read_rss(stream, source, deadline=None):
    deadline = deadline or time.monotonic() + 12
    parser, rows, total, tail = ET.XMLPullParser(events=('end',)), [], 0, b''
    while total <= MAX_BYTES and len(rows) < MAX_ITEMS:
        part = chunk(stream, min(16384, MAX_BYTES + 1 - total), deadline)
        if not part: break
        total += len(part)
        if total > MAX_BYTES: break
        scanned = (tail + part).upper()
        if b'<!DOCTYPE' in scanned or b'<!ENTITY' in scanned or b'\x00' in scanned:
            raise APIError('Source XML declarations or encoding are unsupported.', 'source_format', 502)
        tail = scanned[-16:]
        parser.feed(part)
        for _, node in parser.read_events():
            tag = node.tag.rsplit('}', 1)[-1]
            if tag not in ('item', 'entry'): continue
            fields = {}
            for child in node:
                key = child.tag.rsplit('}', 1)[-1]
                if key == 'link' and child.get('href') and child.get('rel', 'alternate') == 'alternate':
                    fields['link'] = child.get('href')
                elif key not in fields: fields[key] = ''.join(child.itertext())
            link = fields.get('link')
            if not link:
                node.clear(); continue
            row = item(source, fields.get('title'), urljoin(source['home'], link),
                       fields.get('description') or fields.get('summary') or fields.get('encoded') or '',
                       fields.get('pubDate') or fields.get('published') or fields.get('updated'))
            if row: rows.append(row)
            node.clear()
            if len(rows) == MAX_ITEMS: break
    if not rows:
        if total > MAX_BYTES: raise APIError('Source exceeded the read limit before any items.', 'source_too_large', 502)
        parser.close()  # Malformed/empty sources must not look like a successful empty feed.
    return rows


class Blog(HTMLParser):
    """TypeSafe's link cards repeat for animation; deduplicate and retain headings."""
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source, self.current, self.rows, self.seen = source, None, [], set()
        self.depth, self.heading, self.paragraph = 0, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a':
            url = urljoin(self.source['url'], a.get('href', ''))
            if urlsplit(url).hostname == 'typesafe.ai' and re.fullmatch(r'/blog/[^/]+/?', urlsplit(url).path):
                self.current = {'url': url, 'title': '', 'blocks': []}
                self.depth, self.heading, self.paragraph = 1, None, None
                return
        if not self.current or tag in ('area', 'base', 'br', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'wbr'): return
        self.depth += 1
        if not self.current['title'] and (tag in ('h1', 'h2', 'h3', 'h4') or a.get('data-framer-name') in ('H', 'Title', 'Heading')):
            self.heading = self.depth
        if tag == 'p': self.paragraph = (self.depth, [])

    def handle_data(self, value):
        if self.current:
            if self.heading: self.current['title'] += value + ' '
            if self.paragraph: self.paragraph[1].append(value)

    def handle_endtag(self, tag):
        if not self.current: return
        if self.paragraph and self.depth == self.paragraph[0]:
            block = plain(''.join(self.paragraph[1]), 1000)
            if block and block not in self.current['blocks'] and len(self.current['blocks']) < 30: self.current['blocks'].append(block)
            self.paragraph = None
        if self.heading == self.depth: self.heading = None
        self.depth = max(0, self.depth - 1)
        if tag == 'a' and self.current:
            r, self.current = self.current, None
            if r['url'] in self.seen: return
            self.seen.add(r['url'])
            blocks = [b for b in r['blocks'] if b not in ('Company News', 'Thoughts', 'Media')]
            title = plain(r['title']) or (blocks[0] if blocks else '')
            excerpt = next((b for b in blocks if b != title), '')
            excerpt = re.sub(r'^TL;DR:?\s*', '', excerpt)
            row = item(self.source, title, r['url'], excerpt)
            if row: self.rows.append(row)


def read(source, config):
    if source['kind'] == 'reference':
        return [item(source, title, url, excerpt) for title, url, excerpt in REFERENCES], 'Curated links; page bodies were not fetched.'
    return fetch(source), source['note']
