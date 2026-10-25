"""Optional, time-limited phone gateway. The app and API remain loopback-only."""
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'DumbManagerCommunity'
LIMIT = 51 * 1024 * 1024


def make_gateway(key, expires, upstream_port=8783, port=8784, secure=True):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass  # Never log invitation URLs or cookies.

        def reply(self, status, message, extra=()):
            raw = json.dumps({'error': message}).encode()
            self.send_response(status)
            for name, value in extra:
                self.send_header(name, value)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            self.wfile.write(raw)

        def handle_request(self):
            host = self.headers.get('Host', '')
            local = host == f'127.0.0.1:{self.server.server_port}'
            if local and self.path == '/_phone-health' and self.command == 'GET':
                return self.reply(200, 'Phone gateway is running.')
            public = self.server.origin
            if not public or host != urlsplit(public).netloc:
                return self.reply(403, 'Open your private phone link.')
            if time.time() >= expires:
                return self.reply(410, 'This phone link expired. Ask for a new link on your PC.')
            origin = self.headers.get('Origin')
            if origin and origin != public:
                return self.reply(403, 'Use the app on its own page.')
            route = urlsplit(self.path)
            if self.command == 'GET' and route.path == '/connect':
                offered = parse_qs(route.query).get('key', [''])[0]
                if not hmac.compare_digest(offered.encode(), key.encode()):
                    return self.reply(403, 'Open the complete private phone link.')
                cookie = f'dm_phone={key}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max(1,int(expires-time.time()))}'
                if secure:
                    cookie += '; Secure'
                return self.reply(303, 'Connected.', [('Set-Cookie', cookie), ('Location', '/')])
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get('Cookie', ''))
                paired = cookies.get('dm_phone')
                paired = paired and hmac.compare_digest(paired.value, key)
            except Exception:
                paired = False
            if not paired:
                return self.reply(403, 'Open the complete private phone link to connect this browser.')
            if self.path.startswith('//') or route.scheme or route.netloc or route.path == '/api/shutdown':
                return self.reply(403, 'This action is available on your PC only.')
            if self.command == 'POST' and self.headers.get('X-DumbManager') != '1':
                return self.reply(403, 'Use the app controls to send requests.')
            if self.headers.get('Transfer-Encoding'):
                return self.reply(411, 'Send a fixed-size upload.')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                return self.reply(400, 'Invalid upload size.')
            if not 0 <= length <= LIMIT:
                return self.reply(413, 'This file is too large.')
            connection = http.client.HTTPConnection('127.0.0.1', upstream_port, timeout=180)
            try:
                connection.putrequest(self.command, self.path)
                for name in ('Content-Type', 'X-DumbManager', 'X-Thread-Id', 'X-T3-Target', 'X-File-Name', 'X-File-Type', 'X-Video-Mode'):
                    if self.headers.get(name):
                        connection.putheader(name, self.headers[name])
                # Pass only the app's scoped browser session. Never the desktop token.
                session = cookies.get(f'dm_session_{upstream_port}')
                if session:
                    connection.putheader('Cookie', f'dm_session_{upstream_port}={session.value}')
                if origin:
                    connection.putheader('Origin', f'http://127.0.0.1:{upstream_port}')
                connection.putheader('Content-Length', str(length))
                connection.endheaders()
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ConnectionError('Upload interrupted')
                    connection.send(chunk)
                    remaining -= len(chunk)
                response = connection.getresponse()
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() not in ('connection', 'transfer-encoding', 'server', 'date'):
                        if name.lower() == 'set-cookie' and secure:
                            value += '; Secure'
                        self.send_header(name, value)
                self.send_header('Connection', 'close')
                self.close_connection = True
                self.end_headers()
                while chunk := response.read(65536):
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except OSError:
                self.reply(502, 'DumbManager is reconnecting. Try again in a moment.')
            finally:
                connection.close()

        do_GET = handle_request
        do_POST = handle_request

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.origin = None
    return server


def main():
    import launcher
    launcher.start(native=False)
    executable = DATA / 'tools' / 'cloudflared.exe'
    if not executable.is_file():
        raise RuntimeError('Install the optional cloudflared helper in the local data tools folder first.')
    key, expires = secrets.token_urlsafe(32), time.time() + 8*3600
    server = make_gateway(key, expires)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    log_path = DATA / 'phone-tunnel.log'
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    tunnel = None
    try:
        with log_path.open('wb') as log:
            tunnel = subprocess.Popen([str(executable), '--no-autoupdate', 'tunnel', '--url',
                                       f'http://127.0.0.1:{server.server_port}', '--protocol', 'http2'],
                                      stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags)
        for _ in range(200):
            found = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', log_path.read_text(errors='replace'))
            if found:
                break
            if tunnel.poll() is not None:
                raise RuntimeError('Phone tunnel stopped. See the local phone-tunnel.log.')
            time.sleep(.2)
        else:
            raise RuntimeError('Phone tunnel did not return an address.')
        server.origin = found.group()
        state = {'url': server.origin + '/connect?key=' + key, 'expires': expires,
                 'pid': os.getpid(), 'tunnel_pid': tunnel.pid}
        (DATA / 'phone-share.json').write_text(json.dumps(state), encoding='utf-8')
        while time.time() < expires and tunnel.poll() is None:
            time.sleep(1)
    finally:
        server.shutdown()
        server.server_close()
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            tunnel.wait(timeout=10)


if __name__ == '__main__':
    main()
