"""Small bounded RFC6455 transport for our own loopback CDP endpoint only."""
import base64
import hashlib
import json
import os
import socket
import struct
import time
from urllib.parse import urlsplit

from .common import APIError


class CDP:
    def __init__(self, url):
        url = urlsplit(url)
        if url.scheme != 'ws' or url.hostname != '127.0.0.1' or not url.port or not url.path.startswith('/devtools/'):
            raise APIError('Invalid owned-browser connection.')
        self.sock = socket.create_connection(('127.0.0.1', url.port), timeout=8)
        self.sock.settimeout(8)
        self.reader = self.sock.makefile('rb')
        self.sequence = 0
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall((f'GET {url.path} HTTP/1.1\r\nHost: {url.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                               f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            status, headers, size = self.reader.readline(4096), {}, 0
            while True:
                line = self.reader.readline(4096); size += len(line)
                if not line or size > 16384:
                    raise ConnectionError('Invalid browser handshake')
                if line == b'\r\n':
                    break
                k, _, v = line.decode('latin1').partition(':'); headers[k.lower()] = v.strip()
            expected = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if status.split()[1:2] != [b'101'] or headers.get('sec-websocket-accept') != expected:
                raise ConnectionError('Browser rejected connection')
        except BaseException:
            self.close(); raise

    def close(self):
        self.reader.close(); self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, value, opcode=1):
        raw = json.dumps(value).encode() if opcode == 1 else value
        mask, n = os.urandom(4), len(raw)
        length = bytes([128 | n]) if n < 126 else bytes([254])+struct.pack('!H', n) if n <= 65535 else bytes([255])+struct.pack('!Q', n)
        self.sock.sendall(bytes([128 | opcode])+length+mask+bytes(b ^ mask[i % 4] for i, b in enumerate(raw)))

    def exact(self, n):
        raw = self.reader.read(n)
        if len(raw) != n:
            raise ConnectionError('Browser disconnected')
        return raw

    def call(self, method, params=None):
        self.sequence += 1; target = self.sequence
        self.send({'id': target, 'method': method, 'params': params or {}})
        deadline, fragments, total = time.monotonic()+12, bytearray(), 0
        for _ in range(2048):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Browser took too long')
            self.sock.settimeout(min(8, remaining))
            a, b = self.exact(2); n, opcode = b & 127, a & 15
            if n == 126: n = struct.unpack('!H', self.exact(2))[0]
            elif n == 127: n = struct.unpack('!Q', self.exact(8))[0]
            total += n
            if b & 128 or a & 112 or total > 6*1024*1024:
                raise ConnectionError('Browser reply exceeded protocol limits')
            raw = self.exact(n)
            if opcode == 9: self.send(raw, 10); continue
            if opcode == 10: continue
            if opcode == 8: raise ConnectionError('Browser closed')
            if opcode not in (0, 1): raise ConnectionError('Unsupported browser frame')
            fragments.extend(raw)
            if not a & 128: continue
            value = json.loads(fragments); fragments.clear()
            if value.get('method') == 'Page.javascriptDialogOpening':
                # Never approve a website confirm/prompt automatically.
                self.sequence += 1
                self.send({'id': self.sequence, 'method': 'Page.handleJavaScriptDialog', 'params': {'accept': False}})
            if value.get('id') == target:
                if 'error' in value:
                    raise APIError('The page changed or refused that action. Refresh the preview.', 'browser_changed', 409)
                return value.get('result', {})
        raise ConnectionError('Too many browser events')
