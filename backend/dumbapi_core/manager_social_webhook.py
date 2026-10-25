"""Explicit GIF deliveries. URLs stay encrypted; receipts never imply an X post."""
import base64
import hashlib
import json
import math
import re
import socket
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .common import APIError, now

SETTING = 'social_webhook'
PREFIX = b'DumbAPI-social-webhook-v1\0'
DEFAULTS = {'version': 0, 'format': 'discord', 'layout': 'embed', 'bullets': True, 'markdown': True}


def validate_url(value):
    try:
        parsed = urlsplit(value)
        valid = (value.isascii() and not any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value)
                 and parsed.hostname and parsed.port != 0 and not parsed.username and not parsed.password
                 and not parsed.fragment and (parsed.scheme == 'https' or
                     parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}))
    except ValueError:
        valid = False
    if not valid:
        raise APIError('Use an HTTPS webhook URL, or HTTP on localhost for a local receiver.')
    return value


def crypt(value, decrypt=False):
    from .browser_credentials import _crypt
    try:
        return _crypt(value, decrypt=decrypt)
    except APIError:
        raise APIError('Windows could not unlock or save the webhook URL. Set it again in Settings > Posting.', 'webhook_storage', 503) from None


def settings(social, db):
    saved = social.manager.setting(db, SETTING, DEFAULTS)
    return {**{k: saved.get(k, v) for k, v in DEFAULTS.items()},
            'configured': bool(saved.get('url_blob')), 'destination': saved.get('destination', '')}


def configure(social, db, expected_version, url='', clear_url=False, format='discord', layout='embed', bullets=True, markdown=True):
    db.execute('BEGIN IMMEDIATE')
    saved = social.manager.setting(db, SETTING, DEFAULTS)
    if saved['version'] != expected_version:
        raise APIError('Webhook settings changed in another window. Reload the settings.', 'conflict', 409)
    if url and clear_url:
        raise APIError('Choose a new webhook URL or forget the saved one.')
    updated = {**saved, 'version': saved['version'] + 1, 'format': format, 'layout': layout, 'bullets': bullets, 'markdown': markdown}
    if url:
        url = validate_url(url.strip())
        updated['url_blob'] = base64.b64encode(crypt(PREFIX + url.encode('ascii'))).decode('ascii')
        parsed = urlsplit(url)
        updated['destination'] = parsed.hostname + (':' + str(parsed.port) if parsed.port else '')
    if clear_url:
        updated.pop('url_blob', None)
        updated.pop('destination', None)
    social.manager.set_setting(db, SETTING, updated)
    return settings(social, db)


def endpoint(saved):
    try:
        clear = crypt(base64.b64decode(saved['url_blob'], validate=True), decrypt=True)
        if not clear.startswith(PREFIX):
            raise ValueError()
        return validate_url(clear[len(PREFIX):].decode('ascii'))
    except (KeyError, ValueError, UnicodeError):
        raise APIError('Set the webhook URL again in Settings > Posting.', 'webhook_storage', 503) from None


def plain(value):
    value = re.sub(r'!?\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', value)
    value = re.sub(r'(?m)^\s*(?:#{1,6}\s+|>\s*)', '', value)
    value = value.replace('```', '')
    for pattern in (r'\*\*(.+?)\*\*', r'__(.+?)__', r'~~(.+?)~~', r'`([^`]+)`', r'(?<!\w)\*([^*\n]+)\*(?!\w)', r'(?<!\w)_([^_\n]+)_(?!\w)'):
        value = re.sub(pattern, r'\1', value)
    return re.sub(r'\\([\\`*_{}\[\]()#+.!>~|\-])', r'\1', value)


def formatted(value, bullets, markdown):
    lines = []
    for line in value.splitlines():
        body = re.sub(r'^\s*(?:[•●▪◦*+-]|\d+[.)])\s+', '', line).strip()
        if not markdown:
            body = plain(body)
        if body:
            lines.append((('- ' if markdown else '• ') if bullets else '') + body)
    return '\n'.join(lines)


def message(row, options, filename):
    headline = row['headline'] if options['markdown'] else plain(row['headline'])
    summary = formatted(row['summary'], options['bullets'], options['markdown'])
    label = 'Build update' if row['stage'] == 'accepted' else 'Ready to test'
    # Use the edited caption in plain layout; only change existing list markers.
    caption = '\n'.join(formatted(line, options['bullets'], options['markdown'])
                        if re.match(r'^\s*(?:[•●▪◦*+-]|\d+[.)])\s+', line)
                        else line if options['markdown'] else plain(line) for line in row['caption'].splitlines())
    embed = {'title': headline, 'description': summary, 'footer': {'text': label},
             'image': {'url': 'attachment://' + filename}, 'color': 16735436}
    if options['format'] == 'discord':
        payload = {'allowed_mentions': {'parse': []}, 'attachments': [{'id': 0, 'filename': filename}]}
        payload.update({'embeds': [embed]} if options['layout'] == 'embed' else {'content': caption})
    else:
        payload = {'event': 'dumbmanager.completion', 'draft_id': row['id'], 'itch_id': row['itch_id'],
                   'stage': row['stage'], 'headline': headline, 'text': caption, 'changes': summary,
                   'format': {k: options[k] for k in ('layout', 'bullets', 'markdown')}, 'filename': filename}
        if options['layout'] == 'embed':
            payload['embed'] = embed
    return payload


def current(social, db, id, expected_version):
    original = social.manager.get(db, id, 'post_draft')
    row = social.refresh(db, original)
    if row['version'] != expected_version or row['source_changed'] or row['stage'] == 'changed':
        raise APIError('The itch or draft changed. Update the preview before sending.', 'conflict', 409)
    return row


def preview(social, db, id, expected_version):
    row = current(social, db, id, expected_version)
    options = settings(social, db)
    return {'settings': options, 'payload': message(row, options, 'dumbmanager-' + row['itch_id'][:8] + '.gif')}


def multipart(payload, filename, gif, discord):
    boundary = 'dm-' + uuid.uuid4().hex
    file_field = 'files[0]' if discord else 'file'
    data = (f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'.encode()
            + json.dumps(payload, ensure_ascii=False).encode('utf-8')
            + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\nContent-Type: image/gif\r\n\r\n'.encode()
            + gif + f'\r\n--{boundary}--\r\n'.encode())
    return data, 'multipart/form-data; boundary=' + boundary


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def retry_delay(headers, body=b''):
    try:
        value = headers.get('Retry-After')
        if value is None:
            value = json.loads(body).get('retry_after', 1)
        try:
            seconds = float(value)
        except ValueError:
            from email.utils import parsedate_to_datetime
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        return max(1, min(86400, math.ceil(seconds))) if math.isfinite(seconds) else 60
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 60


def deliver(url, payload, filename, data, discord, request_key):
    if discord:
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != 'wait'] + [('wait', 'true')]
        url = urlunsplit(parts._replace(query=urlencode(query)))
    body, content_type = multipart(payload, filename, data, discord)
    request = Request(url, data=body, headers={'Content-Type': content_type, 'User-Agent': 'DumbAPI/0.1', 'Idempotency-Key': request_key}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            status, raw = response.status, response.read(65536)
        try:
            parsed = json.loads(raw) if raw else {}
        except (ValueError, UnicodeError):
            parsed = {}
        if not 200 <= status < 300:
            raise OSError()
        # Discord wait=true must acknowledge a stored message, not just an HTTP 2xx.
        if discord and not (isinstance(parsed, dict) and str(parsed.get('id', '')).isdigit()):
            return {'state': 'unknown', 'http_status': status, 'note': 'The server replied without a message receipt. Check the destination before sending again.'}
        result = {'state': 'sent', 'http_status': status, 'note': 'Webhook accepted the GIF and text.'}
        if discord:
            result['message_id'] = str(parsed['id'])
            channel, guild = str(parsed.get('channel_id', '')), str(parsed.get('guild_id', ''))
            if channel.isdigit():
                result['message_url'] = 'https://discord.com/channels/' + (guild if guild.isdigit() else '@me') + '/' + channel + '/' + result['message_id']
        return result
    except HTTPError as exc:
        # Never expose response bodies or exception strings: either may contain the URL/token.
        try:
            if exc.code == 429:
                try: body = exc.read(4096)
                except OSError: body = b''
                return {'state': 'failed', 'http_status': 429, 'retry_after': retry_delay(exc.headers, body), 'note': 'Webhook is rate limited. Wait before trying again.'}
            return {'state': 'unknown' if exc.code >= 500 else 'failed', 'http_status': exc.code,
                    'note': 'Webhook response was uncertain. Check the destination before sending again.' if exc.code >= 500 else f'Webhook rejected the request (HTTP {exc.code}). Check the URL, format and file limit in Settings > Posting.'}
        finally:
            exc.close()
    except (URLError, OSError, TimeoutError, socket.timeout):
        return {'state': 'unknown', 'note': 'No delivery receipt came back. Check the destination before sending again.'}


def status(social, db, request_key='', id=''):
    if request_key:
        key = 'webhook-' + hashlib.sha256(request_key.encode()).hexdigest()[:40]
        found = db.execute("SELECT data FROM records WHERE id=? AND kind='webhook_delivery'", (key,)).fetchone()
    elif id:
        found = next((r for r in db.execute("SELECT data FROM records WHERE kind='webhook_delivery' ORDER BY updated DESC") if json.loads(r[0])['draft_id'] == id), None)
    else:
        found = None
    return public_receipt(json.loads(found[0])) if found else {'state': 'not_sent'}


def public_receipt(row):
    return {k: v for k, v in row.items() if k != 'fingerprint'}


def send(social, db, id, expected_version, settings_version, sha256, request_key, vibe=0, confirm=False, theme=''):
    if not confirm:
        raise APIError('Send only after the user chooses Send to webhook for this GIF.', 'confirmation_required', 409)
    if not re.fullmatch(r'[A-Za-z0-9_-]{12,100}', request_key) or not re.fullmatch('[a-f0-9]{64}', sha256):
        raise APIError('Use a delivery request key and the exact GIF SHA-256.')
    manager = social.manager
    key = 'webhook-' + hashlib.sha256(request_key.encode()).hexdigest()[:40]
    # Keep legacy random-style receipt identities stable across this upgrade.
    identity = [id, expected_version, settings_version, sha256, vibe]
    if theme: identity.append(theme)
    fingerprint = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    found = db.execute("SELECT data FROM records WHERE id=? AND kind='webhook_delivery'", (key,)).fetchone()
    if found:
        prior = json.loads(found[0])
        if prior['fingerprint'] != fingerprint:
            raise APIError('This delivery key belongs to another GIF or settings version.', 'conflict', 409)
        return public_receipt(prior)
    row = current(social, db, id, expected_version)
    options = manager.setting(db, SETTING, DEFAULTS)
    if options['version'] != settings_version:
        raise APIError('Webhook settings changed. Review the webhook preview again.', 'conflict', 409)
    if not options.get('url_blob'):
        raise APIError('Add a webhook URL in Settings > Posting first.')
    from .manager_social_gif import gif
    rendered = gif(social, db, id, vibe, theme)
    if rendered['sha256'] != sha256:
        raise APIError('The animated card changed. Refresh its preview before sending.', 'conflict', 409)
    url = endpoint(options)
    payload = message(row, options, rendered['filename'])
    db.execute('BEGIN IMMEDIATE')
    current(social, db, id, expected_version)
    if manager.setting(db, SETTING, DEFAULTS)['version'] != settings_version:
        raise APIError('Webhook settings changed. Review the preview again.', 'conflict', 409)
    found = db.execute("SELECT data FROM records WHERE id=? AND kind='webhook_delivery'", (key,)).fetchone()
    if found:
        prior = json.loads(found[0])
        if prior['fingerprint'] != fingerprint:
            raise APIError('This delivery key belongs to another GIF or settings version.', 'conflict', 409)
        return public_receipt(prior)
    cooldown = manager.setting(db, 'social_webhook_cooldown', {})
    if cooldown.get('version') == settings_version and cooldown.get('until', 0) > datetime.now(timezone.utc).timestamp():
        raise APIError('Webhook is rate limited. Wait before trying again.', 'webhook_rate_limited', 429)
    stamp = now()
    receipt = {'id': key, 'draft_id': id, 'project': row['project'], 'version': expected_version, 'source_version': row['source_version'],
               'settings_version': settings_version, 'sha256': sha256, 'vibe': vibe, 'theme': theme, 'destination': options['destination'], 'format': options['format'],
               'fingerprint': fingerprint, 'state': 'sending', 'created_at': stamp, 'updated_at': stamp,
               'note': 'Sending. If interrupted, check the destination before sending another copy.'}
    manager.put(db, 'webhook_delivery', receipt)
    db.commit()  # persist intent before network I/O; no lock during the upload
    answer = deliver(url, payload, rendered['filename'], base64.b64decode(rendered['gif']), options['format'] == 'discord', request_key)
    receipt.update(answer, updated_at=now())
    db.execute('BEGIN IMMEDIATE')
    manager.put(db, 'webhook_delivery', receipt)
    if answer.get('retry_after'):
        manager.set_setting(db, 'social_webhook_cooldown', {'version': settings_version, 'until': datetime.now(timezone.utc).timestamp() + answer['retry_after']})
    return public_receipt(receipt)
