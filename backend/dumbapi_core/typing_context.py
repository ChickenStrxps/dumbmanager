"""Bounded, on-demand thread context and source-grounded sentence continuations.

No thread discovery, background polling, conversation database or text generator.
Only the selected exact thread is read; a small memory cache avoids per-key reads.
"""
import re
import threading
import time
from collections import OrderedDict

from .common import APIError
from .t3 import T3

_cache = OrderedDict()
_lock = threading.Lock()
TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]*")
STOP = set('the and for with from into this that there here more make help please can could would should have has was are'.split())


def recent(config, thread_id):
    """Read at most four compact messages, once per 15s while actively requested."""
    try:
        T3.thread_id(thread_id)
    except APIError:
        return {"source": "unavailable", "messages": []}
    from .t3_distributions import target
    key = (str(config.data.resolve()), target(config), thread_id)
    clock = time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if entry and entry[0] > clock:
            return entry[1]
        # Reserve before I/O. Other requests stay local instead of queueing reads.
        _cache[key] = (clock + 15, {"source": "unavailable", "messages": []})
        _cache.move_to_end(key)
        while len(_cache) > 16:
            _cache.popitem(last=False)
    try:
        client = T3(config)
        client.read_timeout = 2
        row = client.read(thread_id)
        messages = [{"role": m["role"], "text": m.get("text", "")[-1000:], "at": m.get("at")}
                    for m in row.get("messages", [])[-4:] if m.get("role") in ("user", "assistant")]
        result = {"source": "live_thread", "title": row.get("thread", {}).get("title", "")[:160],
                  "messages": messages, "at": messages[-1].get("at") if messages else None}
    except APIError:
        result = {"source": "unavailable", "messages": []}
    with _lock:
        _cache[key] = (time.monotonic() + (15 if result['source'] == 'live_thread' else 5), result)
        _cache.move_to_end(key)
        while len(_cache) > 16:
            _cache.popitem(last=False)
    return result


def passages(values):
    """Keep short prose clauses, excluding fenced code and raw URLs/paths."""
    seen = set()
    for value in values:
        value = re.sub(r'```[\s\S]*?```', '', value[:4000])
        value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
        value = re.sub(r'[*`_#]', '', value)
        for phrase in re.split(r'[\r\n]+|(?<=[.!?;])\s+', value):
            phrase = re.sub(r'^\s*(?:[-•]+|\d+[.)])\s*', '', phrase).strip()
            if len(phrase) < 12 or re.search(r'https?://|[A-Z]:\\|</?\w+[ >]', phrase):
                continue
            phrase = phrase[:300]
            if phrase.casefold() not in seen:
                seen.add(phrase.casefold())
                yield phrase


def continuations(typed, values, limit=6):
    """Append source text matching a trailing phrase, preserving every typed byte.

    Matching the end rather than the whole input allows a new sentence such as
    'Can you make the fish flo' to borrow 'fish flopping smoothly on landing'.
    The suffix is a suggestion, never a reported fact or an automatic action.
    """
    tokens = list(TOKEN.finditer(typed))
    if not tokens or len(typed.strip()) < 4:
        return []
    last = tokens[-1]
    tail = typed[last.end():]
    if tail and not tail.isspace():
        return []
    if last.start() and typed[last.start()-1] in './:@-':
        return []
    partial = not tail
    ranked, seen = [], set()
    for order, phrase in enumerate(passages(values)):
        words = list(TOKEN.finditer(phrase))
        for count in range(min(6, len(tokens)), 0, -1):
            query = [m[0].casefold() for m in tokens[-count:]]
            if count == 1 and (len(query[0]) < 3 or query[0] in STOP):
                continue
            for start in range(len(words)-count+1):
                group = words[start:start+count]
                if count == 1 and len(words) - start - count < 3:
                    continue
                text = [m[0].casefold() for m in group]
                if text[:-1] != query[:-1] or not (text[-1].startswith(query[-1]) if partial else text[-1] == query[-1]):
                    continue
                end = group[-1].end() - (len(group[-1][0])-len(query[-1]) if partial else 0)
                stop = min(len(words), start+count+18)
                suffix = phrase[end:words[stop-1].end()]
                if tail:
                    suffix = suffix.lstrip()
                # Require multiple added words; ordinary word completion handles one.
                if len(TOKEN.findall(suffix)) < 2:
                    continue
                value = typed + suffix
                if len(value) > 500 or value.casefold() in seen:
                    continue
                seen.add(value.casefold())
                ranked.append((count, -order, value))
    ranked.sort(key=lambda row: (-row[0], -row[1]))
    return [value for _, _, value in ranked[:limit]]
