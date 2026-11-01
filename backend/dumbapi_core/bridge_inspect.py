"""Bounded, transient inspection of explicitly supplied Unicode text."""
from .common import APIError

# Fixed Unicode format ranges keep results independent of host Unicode tables.
def _kind(n):
    if n == 9: return "Tab"
    if n == 13: return "CR"
    if n == 10: return "LF"
    if n <= 0x1f or 0x7f <= n <= 0x9f: return "Control"
    if n in (0xa0, 0x2007, 0x202f): return "Nonbreaking space"
    if 0xfe00 <= n <= 0xfe0f or 0xe0100 <= n <= 0xe01ef: return "Variation selector"
    if (n in (0xad, 0x61c, 0x6dd, 0x70f, 0x8e2, 0x180e, 0xfeff, 0x110bd, 0x110cd, 0xe0001)
        or 0x600 <= n <= 0x605 or 0x890 <= n <= 0x891 or 0x200b <= n <= 0x200f
        or 0x202a <= n <= 0x202e or 0x2060 <= n <= 0x2064 or 0x2066 <= n <= 0x206f
        or 0xfff9 <= n <= 0xfffb or 0x13430 <= n <= 0x1343f or 0x1bca0 <= n <= 0x1bca3
        or 0x1d173 <= n <= 0x1d17a or 0xe0020 <= n <= 0xe007f): return "Format"
    return None

def inspect(text):
    if not isinstance(text, str) or not text:
        raise APIError("Supply nonempty text to inspect.")
    try:
        encoded = text.encode("utf-8")
        units = len(text.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        raise APIError("Text must contain valid Unicode scalar values.")
    if units > 4000 or len(encoded) > 16000:
        raise APIError("Text exceeds 4000 UTF-16 units or 16000 UTF-8 bytes.")
    counts = {k: 0 for k in ("Tab", "CRLF", "CR", "LF", "Control", "Format", "Nonbreaking space", "Variation selector")}
    details = []
    total = 0
    line = col = 1
    previous_cr = False
    for i, char in enumerate(text):
        n = ord(char)
        kind = _kind(n)
        if kind:
            total += 1
            if len(details) < 16:
                details.append(f"U+{n:04X} {kind} at line {line}, column {col}")
            if kind == "CR":
                counts["CRLF" if i + 1 < len(text) and text[i + 1] == "\n" else "CR"] += 1
            elif kind == "LF":
                if not previous_cr: counts["LF"] += 1
            else: counts[kind] += 1
        if char == "\r":
            if i + 1 < len(text) and text[i + 1] == "\n": col += 1
            else: line, col = line + 1, 1
        elif char == "\n": line, col = line + 1, 1
        else: col += 1
        previous_cr = char == "\r"
    summary = ", ".join(f"{k}: {v}" for k, v in counts.items() if v) or "none"
    content = (f"Invisible character inspection\nDetected: {summary}.\n"
               f"Occurrences shown: {len(details)} of {total} code points. Positions are 1-based Unicode scalar columns, not bytes or display columns. CRLF counts as one line break; its code points are counted separately. No automatic repair.\n"
               + "\n".join(details))
    return {"type": 4, "data": {"flags": 64, "content": content, "allowed_mentions": {"parse": []}}}
