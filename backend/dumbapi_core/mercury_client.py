"""Shared provider backoff for browser plans and inline completions."""
import hashlib
import math
import threading
import time
from collections import OrderedDict
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError

from .common import APIError

_lock = threading.Lock()
_cooldowns = OrderedDict()


def _retry_seconds(headers):
    value = headers.get('Retry-After', '') if headers else ''
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):seconds = 60
    return max(1, min(3600, math.ceil(seconds))) if math.isfinite(seconds) else 60


def _limited(seconds):
    error = APIError(f'Mercury is rate-limited. Try again in about {seconds}s. Your goal is kept.',
                     'mercury_rate_limited', 429)
    error.retry_after_ms = seconds * 1000
    return error


def request(transport, endpoint, payload, key, timeout):
    # One provider key can serve multiple contexts/tabs. Never store it in this map.
    identity = hashlib.sha256(key.encode()).digest()
    with _lock:
        remaining = _cooldowns.get(identity, 0) - time.monotonic()
        if remaining > 0:raise _limited(math.ceil(remaining))
        _cooldowns.pop(identity, None)
    try:
        return transport(endpoint, payload, key, timeout=timeout)
    except HTTPError as exc:
        exc.close()
        if exc.code == 429:
            seconds = _retry_seconds(exc.headers)
            with _lock:
                _cooldowns[identity] = max(_cooldowns.get(identity, 0), time.monotonic() + seconds)
                _cooldowns.move_to_end(identity)
                while len(_cooldowns) > 128:_cooldowns.popitem(last=False)
            raise _limited(seconds) from None
        if exc.code in (401, 403):
            raise APIError('Mercury refused this connection. Check Fresh ideas in Settings.',
                           'mercury_connection', 503) from None
        raise APIError('Mercury is unavailable right now. Your goal is kept; try again shortly.',
                       'mercury_unavailable', 503) from None
    except (TimeoutError, URLError):
        raise APIError('Mercury did not reply in time. Your goal is kept; try again.',
                       'mercury_unavailable', 503) from None
    # No request or browser action is automatically replayed.
