"""Small offline vocabulary for partial-word completion, augmented by published context.

No corpus download, source crawl or model runtime. These are candidate words, not
claims about the project; Jev can rank the composed continuations when connected.
"""
import re
from collections import Counter

COMMON = """background batch back balance base bar button buttons border browser build builds bug bugs
animation animated animations animate attachment attachments analytics account action actions address
add adding allow already also always approve approved archive archived array arrow audio automatically
backend backup bigger blank bottom broken buffering cache capture card cards change character chat check
checkbox clean clear click clickable close code color colors column columns command commands comment
comments complete completion completions component config connect connection console content context
continue control controls cook cooking copy correct crash create current cursor custom dark data database
default delete description design desktop detail details different disable disabled display document done
down download drag dropdown duplicate duplicates edit editor effect effects element enable enabled enter
error evidence example export fast faster feedback field file files filter finish fix fixed fixing flag
flow focus folder font fonts foreground format formatting frame frames frameboard frequency fullscreen
function gallery game generate global glitch glow graph handle height help hide highlight history home
hover icon image images import improve input inside install integration interface issue items job jobs
keyboard keybind label labels lag landing larger latest layout left less lighter light like likes limit
line link list live load loaded loading local lock log logs login long loop lower main make manage
margin menu merge message messages metric missing mobile modal model more motion move moving multiple
name native navigate navigation need needs network new next note notification number object off offline
offset older opacity open option options original outcome outside overflow overlap page panel paragraph
particle particles pass paste pause performance phone photo picker pixel pixels placeholder play playback
player pointer popup position post posts prefix preserve preview previous progress project prompt publish
queue quick range read ready receipt receipts reconnect record refresh reload remove render repeat reply
report request reset resize response restart result retry return review right rotate rotation row run
running save saved scale scanner screenshot scroll search second seconds select selected selection send
sentence separate server session settings share shortcut show sidebar simple size skip slow slower small
smaller smooth smoothly snapshot source space spacing speed split start state stats status step sticky
stop storage style submit suggest suggested suggestion suggestions support switch sync tab table task
terminal test testing text theme thread thumbnail time timestamp title toast token tools top total touch
transparent type typing undo update upload url user value version video view visible visual volume wait
width window word words work working workspace wrap wrong zoom fish fishing flopping flop sharks shark
water camera movement recovery stiffness floating swimming falling sprites sprite canvas dithering ascii
please could would should want this that these those their there then than with without when while into
from after before because between through correctly incorrectly everything anything something another
""".split()
TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]{1,39}")
ENDING = re.compile(r"(?<![\w./:@-])([a-zA-Z][a-zA-Z0-9'-]*)$")


def vocabulary(context=None, candidates=()):
    context = context or {}
    values = [context.get(k, "") for k in ("task", "testing", "entities")]
    values.extend(c for c in candidates if isinstance(c, str))
    terms = Counter(w.lower() for v in values for w in TOKEN.findall(v[:2000]) if len(w) > 1)
    # Stable priority: terms grounded in this project/thread, then a small default list.
    return list(dict.fromkeys([w for w, _ in terms.most_common(512)] + COMMON))


def complete(typed, terms, limit=8):
    """Append only the missing letters of the word at the end, keeping input verbatim."""
    match = ENDING.search(typed)
    if not match or len(match[1]) < 2:
        return []
    fragment = match[1]
    found, seen = [], set()
    for word in terms:
        lower = word.lower()
        if len(lower) <= len(fragment) or not lower.startswith(fragment.lower()) or lower in seen:
            continue
        seen.add(lower)
        ending = lower[len(fragment):]
        value = typed + (ending.upper() if fragment.isupper() else ending)
        if len(value) <= 500:
            found.append(value)
        if len(found) >= limit:
            break
    return found
