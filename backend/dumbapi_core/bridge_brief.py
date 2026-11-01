"""Deterministic, explicitly selected portable reproduction briefs."""
import re
from .common import APIError

FIELDS = (('title', 'Title'), ('environment', 'Environment'), ('expected', 'Expected'),
          ('observed', 'Observed / error or log'), ('steps', 'Steps'))

def clean_fields(values):
    if not isinstance(values, dict) or set(values) - {key for key, _ in FIELDS}:
        raise APIError('Invalid brief fields.')
    result = {}
    for key, value in values.items():
        limit = 200 if key == 'title' else 1500
        if not isinstance(value, str) or len(value.encode('utf-16-le')) // 2 > limit:
            raise APIError('A brief field exceeds its displayed limit.')
        result[key] = value
    return result

def render(row):
    brief = row.get('repro_brief') or {}
    # Indented blocks make arbitrary Markdown, fences and mentions literal.
    def block(value):
        return '\n'.join('    ' + line for line in value.replace('\r\n', '\n').replace('\r', '\n').split('\n'))
    parts = ['# Reproduction brief', '', 'User-authored fields; unknown means not provided.']
    for key, label in FIELDS:
        value=brief.get(key,'')
        parts += ['', '## ' + label, '', block(value if value.strip() else 'Unknown')]
    parts += ['', '## Selected source snapshot', '']
    if brief.get('include_source'):
        parts += ['Explicitly included Discord message text (captured snapshot, not live):', '',
                  block(row.get('source', {}).get('text', '') or '[No text supplied]')]
        files=row.get('source',{}).get('attachments',[])
        if files:
            parts += ['', 'Selected attachment metadata (no media or download URLs):', '']
            for item in files[:8]:
                name=item.get('filename','attachment').replace('\\','/').rsplit('/',1)[-1]
                name=''.join(c for c in name if c.isprintable())[:100] or 'attachment'
                kind=''.join(c for c in item.get('content_type','unknown') if c.isprintable())[:100] or 'unknown'
                parts.append(block(name+' | '+kind))
    else:
        parts += ['Source text and automatic source metadata are omitted by choice.']
    parts += ['', 'No automatic source IDs, source link or attachment download URLs are added. Authored fields and included text may still contain private information; review the entire file before sharing.', '']
    result = '\n'.join(parts)
    return re.sub(r'https?://(?:cdn\.discordapp\.com|media\.discordapp\.net)/[^\s<>]*', '[Discord attachment URL omitted]', result, flags=re.IGNORECASE)
