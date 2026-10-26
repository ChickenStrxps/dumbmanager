"""Append-only quality and sentence completions, without a prepared vocabulary."""
import re

PROMPT = re.compile(r'\b(?:with|featuring|that has|that have)\s+(?P<fragment>[^\n.!?;]{0,100})$', re.I)


def opening(typed):
    if len(typed)>500 or re.search(r'https?://|[\n\r]',typed) or typed.lstrip().startswith(('/', '.', ':', '@', '`')):
        return None
    match = PROMPT.search(typed)
    if match and typed[:match.start()].strip():
        return {'prefix':typed[:match.start('fragment')], 'fragment':match['fragment'], 'mode':'quality'}
    if len(typed.strip())<10 or len(typed.split())<3 or re.search(r'[.!?;]\s*$',typed):
        return None
    return {'prefix':'', 'fragment':typed, 'mode':'sentence'}


def qualities(typed, generated=(), limit=5):
    """Validate fresh model qualities; preserve all user input byte for byte."""
    prompt = opening(typed)
    if not prompt:
        return []
    rows, seen = [], set()
    for quality in generated:
        if not isinstance(quality,str) or not 1 <= len(quality) <= (140 if prompt['mode']=='quality' else 500):
            continue
        quality = quality.strip()
        if any(ord(c)<32 for c in quality) or not quality.casefold().startswith(prompt['fragment'].casefold()):
            continue
        value = typed + quality[len(prompt['fragment']):]
        if value == typed or len(value)>500 or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        rows.append({'text':value, 'quality':quality, 'kind':'idea' if prompt['mode']=='quality' else 'continuation', 'score':2.1, 'source':'mercury'})
        if len(rows)>=limit:
            break
    return rows
