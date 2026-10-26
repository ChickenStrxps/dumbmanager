"""Local integration records and DPAPI-encrypted credentials. No secrets in JSON views."""
import sqlite3
from contextlib import contextmanager

from ..common import APIError


def crypt(value, decrypt=False):
    from ..browser_credentials import _crypt
    try:
        return _crypt(value, decrypt=decrypt)
    except APIError:
        raise APIError('Windows could not unlock or save this integration credential. Enter it again in AI integrations.',
                       'credential_storage', 503) from None


class Store:
    def __init__(self, config):
        self.path = config.data / 'ai-integrations.sqlite'
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS integrations(id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                    config TEXT NOT NULL, credential BLOB, token_hash TEXT, probe TEXT);
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                    version INTEGER NOT NULL, expires REAL NOT NULL, seen REAL NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                    version INTEGER NOT NULL, session TEXT NOT NULL, request_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, capability TEXT NOT NULL, arguments TEXT NOT NULL,
                    expires REAL NOT NULL, state TEXT NOT NULL, result TEXT, created TEXT NOT NULL,
                    UNIQUE(provider,request_key));
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=8)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
