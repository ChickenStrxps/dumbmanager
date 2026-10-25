"""Local, evidence-linked learning trails. No model, shell, source scan or acceptance."""
import hashlib
import json
import re

from .common import APIError, json_text, now
from .manager import text, unpack

VERSION = 1


def digest(value):
    return hashlib.sha256(json_text(value).encode()).hexdigest()[:24]


def private_text(value):
    """Saved records are data; do not re-display recognizable credentials in a guide."""
    value = str(value)
    value = re.sub(r'\b(?:sk|ghp|gho)[_-][\w-]{12,}', '[credential removed]', value, flags=re.I)
    value = re.sub(r'(?i)(bearer\s+)[\w.\-/+=]{8,}', r'\1[removed]', value)
    value = re.sub(r'''(?i)(["']?(?:api[_-]?key|access[_-]?token|token|authorization|cookie|password|secret)["']?\s*[=:]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''', r'\1[removed]', value)
    value = re.sub(r'''(?i)(--(?:api[_-]?key|token|password|secret)(?:=|\s+))(?:"[^"\n]*"|'[^'\n]*'|[^\s]+)''', r'\1[removed]', value)
    return ''.join(c for c in value if c in '\n\t' or ord(c) >= 32)


def private_value(value):
    # Redact strings before serialization; escaped JSON quotes are not shell quotes.
    if isinstance(value, dict):
        return {k: '[removed]' if re.fullmatch(r'(?i)api[_-]?key|access[_-]?token|token|authorization|cookie|password|secret', k)
                else private_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [private_value(v) for v in value]
    return private_text(value) if isinstance(value, str) else value


def eligible(row):
    return row['state'] not in ('archived', 'needs_description') and (
        row['state'] in ('ready', 'resolved') or row.get('run_state') == 'agent_reported_done')


def sources_for(row):
    sources = []

    def add(id, label, value, kind='report'):
        value = (private_text(value) if isinstance(value, str) else json_text(private_value(value))).strip()[:2400]
        if value:
            sources.append({'id': id, 'label': label, 'text': value, 'kind': kind})

    add('observation', 'Original request', row.get('original') or row['title'], 'request')
    add('goal', 'Saved desired outcome', row.get('desired_outcome', ''), 'request')
    ctx = row.get('context') or {}
    for key in ('workspace', 'task', 'testing'):
        add('context:' + key, 'Context at capture · ' + key, ctx.get(key, ''), 'context')
    for i, step in enumerate(row.get('plan', [])):
        if step.get('done'):
            add('plan:' + step['id'], 'Reported completed step · ' + step['id'], step['text'])
    for i, evidence in enumerate(row.get('evidence', [])):
        add('evidence:' + str(i), 'Saved evidence · ' + str(i + 1), evidence)
        if isinstance(evidence, dict):
            if isinstance(evidence.get('workspace'), str):
                add(f'evidence:{i}:workspace', 'Workspace reported for this work', evidence['workspace'], 'environment')
            if isinstance(evidence.get('environment'), str):
                add(f'evidence:{i}:environment', 'Environment reported for this work', evidence['environment'], 'environment')
            if isinstance(evidence.get('summary'), str):
                add(f'evidence:{i}:summary', 'Saved result summary · ' + str(i + 1), evidence['summary'])
            # Explicit command logs retain the real string rather than JSON escaping.
            command_log = evidence.get('commands', [])
            for j, command in enumerate(command_log[:8] if isinstance(command_log, list) else []):
                if isinstance(command, str):
                    add(f'evidence:{i}:command:{j}', 'Recorded command · ' + str(j + 1), command, 'command')
    for i, outcome in enumerate(row.get('outcomes', [])):
        add('outcome:' + str(i), 'Accepted outcome · ' + str(i + 1), outcome.get('summary', ''))
        if outcome.get('evidence'):
            add('outcome:' + str(i) + ':evidence', 'Accepted outcome evidence', outcome['evidence'])
    # Keep the original/goal/environment and the most recent reported work.
    head = [s for s in sources if s['kind'] in ('request', 'context')]
    reports = [s for s in sources if s['kind'] not in ('request', 'context')]
    work = [s for s in reports if not s['id'].startswith('outcome:')]
    outcomes = [s for s in reports if s['id'].startswith('outcome:')]
    # Acceptance must not evict a command/lesson's work source from the window.
    return head + work[-24:] + outcomes[-4:]


def source_revision(row, sources):
    return digest([VERSION, row['id'], sources, row['state'] == 'resolved', eligible(row),
                   row.get('occurrences', [])[-1:], row.get('feedback', [])[-1:]])


def work_revision(row, sources):
    # User acceptance adds an outcome, but does not invalidate the agent's
    # explanations of the same completed work. A new pass/report still does.
    return digest([VERSION, row['id'], [s for s in sources if not s['id'].startswith('outcome:')],
                   row.get('occurrences', [])[-1:], row.get('feedback', [])[-1:]])


# These are explanations, not a dependency detector. They are shown only beside a
# literal mention in reported work (never from a request or old capture context).
TOPICS = (
    ('unittest', r'\bunittest\b', 'Python unittest',
     'Discovery collects test modules from a directory. A passing suite covers those checks; it does not prove every user flow works.',
     'Find one test for this change. Read its setup, action and assertion before changing anything.',
     'Why might the tests pass while a button still feels broken?',
     'The test may cover the domain logic without exercising the browser interaction.',
     'https://docs.python.org/3/library/unittest.html'),
    ('node', r'\bnode(?:\.js)?\b|node --check', 'Node syntax checks',
     'node --check parses a script without executing it. Syntax success does not exercise events, layout or network requests.',
     'Compare the saved syntax check with the separate browser evidence for this itch.',
     'Does a syntax check prove a click handler works?',
     'No. It checks parsing; an interaction needs its own check.',
     'https://nodejs.org/api/cli.html#-c---check'),
    ('playwright', r'\bplaywright\b', 'Playwright',
     'Locators find controls and can wait for them to become actionable. Prefer a visible role or label over a fragile screen coordinate.',
     'Find the control this itch changed and describe it by its visible label.',
     'What tends to survive a layout change: a button label or a screen coordinate?',
     'The label usually survives. A coordinate can point somewhere else after a resize.',
     'https://playwright.dev/docs/locators'),
    ('sqlite', r'\bsqlite\b', 'SQLite transactions',
     'A transaction groups related writes so they commit together. A saved UI response and a durable database write are different things.',
     'Identify which part of this result should still be true after reload.',
     'What does a reload check add to a successful save response?',
     'It checks that the application can read the persisted result again.',
     'https://www.sqlite.org/lang_transaction.html'),
    ('gif', r'\bgifs?\b', 'Looping GIFs',
     'A GIF contains timed frames. A seamless loop needs the last-to-first transition to fit the motion, as well as a smooth sequence within the file.',
     'Watch the recorded animation through two loops. Look at the seam and any text that should remain still.',
     'Where can a loop jump even when all the middle frames look smooth?',
     'At the transition from the final frame back to the first.',
     'https://www.w3.org/Graphics/GIF/spec-gif89a.txt'),
    ('idempotency', r'\bidempotenc(?:y|e|t)\b', 'Retry identity',
     'A stable request key lets a retry refer to the same action. Reusing it with different content should be rejected rather than silently doing new work.',
     'Trace the saved retry evidence: what stayed the same, and what happened only once?',
     'Should a lost response automatically mean repeating the external action?',
     'No. First recover the receipt for that request; the original action may already have succeeded.',
     ''),
)


def lesson(key, title, explanation, try_this, question, answer, source_ids):
    value = dict(title=title, explanation=explanation, try_this=try_this,
                 question=question, answer=answer, source_ids=source_ids)
    return dict(id=key + '-' + digest(value)[:12], **value)


def build(manager, db, row):
    sources = sources_for(row)
    basis = source_revision(row, sources)
    work_basis = work_revision(row, sources)
    saved = manager.setting(db, 'learning-notes:' + row['id'], {})
    stale = bool(saved) and saved.get('basis') != work_basis
    notes = saved.get('notes', {}) if not stale else {}
    lookup = {s['id']: s for s in sources}
    reports = [s for s in sources if s['kind'] == 'report']
    steps = [s for s in reports if s['id'].startswith('plan:')]
    results = [s for s in reports if not s['id'].startswith('plan:')]
    lessons, commands, packages = [], [], []
    if eligible(row):
        implementation = [s for s in steps if not re.match(r'^(recheck|verify|test|review|inspect|research)\b', s['text'], re.I)]
        target = implementation[:1] or steps[-1:] or results[-1:]
        if target:
            item = target[0]
            lessons.append(lesson('change', 'Map the change',
                'Start with the request, then connect it to this reported result:\n\n' + item['text'][:1000],
                'Explain the before and after in one sentence. Point to the completed step or saved result that supports it.',
                'Does the original request show what was actually implemented?',
                'It describes the intent. Use completed steps and result evidence to explain what was reported as implemented.',
                ['observation', item['id']]))
        if results:
            item = results[-1]
            lessons.append(lesson('evidence', 'Read the evidence',
                'The record reports:\n\n' + item['text'][:1200] + '\n\nA report is a starting point for review, not a new verification run.',
                'Choose one reported check. Say what it covers and one thing you would still check by hand in this environment.',
                'Does opening this learning trail rerun the checks?',
                'No. These are saved reports. No commands or tests run when you open a lesson.', [item['id']]))
        for entry in notes.get('lessons', []):
            lessons.append(lesson('note', entry['title'], entry['explanation'], entry['try_this'],
                                  entry['question'], entry['answer'], [entry['source_id']]))
        for key, pattern, title, tip, exercise, question, answer, docs in TOPICS:
            match = next((s for s in reversed(reports) if re.search(pattern, s['text'], re.I)), None)
            if match:
                packages.append({'name': title, 'tip': tip, 'docs': docs, 'source_ids': [match['id']],
                                 'kind': 'Mentioned in saved work'})
                lessons.append(lesson(key, title, tip, exercise, question, answer, [match['id']]))
        if not lessons:
            # Never turn the original wish into a claim that it was built.
            lessons.append(lesson('review', 'Start with the original itch',
                'This itch is marked ready or accepted, but no completed steps or result notes were saved. There is not enough history to explain the implementation.',
                'Compare the current result with the original request. Ask the working agent to save what changed, the checks, and the commands actually used.',
                'Can a title alone tell you which package or command was used?',
                'No. That needs recorded work. This trail leaves those gaps visible.', ['observation']))
        for entry in notes.get('commands', []):
            commands.append({**entry, 'source_ids': [entry['source_id']], 'kind': 'Recorded command'})
        seen = {c['command'] for c in commands}
        for src in sources:
            # Only an explicit command-log field counts as an exact command.
            # A phrase such as "Python checks passed" is not a command log.
            if src['kind'] == 'command' and src['text'] not in seen and '[removed]' not in src['text'] and '[credential removed]' not in src['text']:
                seen.add(src['text'])
                commands.append({'command': src['text'], 'explanation': 'Saved in the agent\'s command report. Read the arguments and working directory before reusing it.',
                                 'caution': 'Reported history; this view does not run or verify it.',
                                 'source_ids': [src['id']], 'kind': 'Recorded command'})
        for entry in notes.get('packages', []):
            packages.append({'name': entry['name'], 'tip': entry['tip'], 'docs': '',
                             'source_ids': [entry['source_id']], 'kind': 'Agent-written package tip'})
    for item in lessons:
        # Invalidate reading progress if the supporting work changes.
        item['id'] = row['id'][:12] + '-' + item['id'] + '-' + digest([lookup[s] for s in item['source_ids']])[:8]
    lessons = list({item['id']: item for item in lessons}.values())
    revision = digest([basis, notes, VERSION])
    progress = manager.setting(db, 'learning-progress:' + row['id'], {'version': 0, 'read': []})
    ids = {l['id'] for l in lessons}
    read = [id for id in progress['read'] if id in ids]
    workspace = next((s for s in reversed(sources) if s['id'].startswith('evidence:') and s['id'].endswith(':workspace')), None)
    actual_workspace = bool(workspace)
    workspace = workspace or lookup.get('context:workspace')
    environment = next((s for s in reversed(sources) if s['id'].endswith(':environment')), None)
    return {'id': row['id'], 'title': private_text(row['title']), 'project': row['project'],
            'eligible': eligible(row), 'stage': 'Accepted by you' if row['state'] == 'resolved' else 'Ready to test' if eligible(row) else 'Work not finished',
            'revision': revision, 'source_revision': basis, 'work_revision': work_basis, 'itch_version': row['version'],
            'workspace': workspace['text'] if workspace else '',
            'environment': environment['text'] if environment else '',
            'workspace_note': 'Agent-reported workspace for this work; not a live environment scan.' if actual_workspace else 'Snapshot saved when this itch was captured; not a live environment scan.' if workspace else 'No workspace was saved with this itch.',
            'lessons': lessons[:16], 'commands': commands[:8], 'packages': packages[:12], 'sources': sources,
            'notes_stale': stale, 'notes_version': saved.get('version', 0),
            'progress': {'version': progress['version'], 'read': read, 'total': min(len(lessons), 16)},
            'coverage': 'Built locally from this itch’s recent saved work only. Reports are not rerun. Tool explanations are general guidance; package installation and versions are not inferred.'}


def get(manager, db, id):
    return build(manager, db, manager.get(db, id, 'itch'))


def record(manager, db, id, revision, notes='{}'):
    pack = get(manager, db, id)
    if pack['revision'] != revision:
        raise APIError('The saved work changed. Read the learning trail again before saving notes.', 'conflict', 409)
    if not pack['eligible']:
        raise APIError('Learning notes belong to ready-for-review or accepted work.')
    notes = unpack(notes, dict, {})
    if set(notes) - {'lessons', 'commands', 'packages'} or len(json_text(notes)) > 18000:
        raise APIError('Use bounded lessons, commands and packages only.')
    sources = {s['id']: s['text'] for s in pack['sources'] if s['kind'] in ('report', 'command')}
    clean = {}
    fields = {'lessons': ('title', 'explanation', 'try_this', 'question', 'answer'),
              'commands': ('command', 'explanation', 'caution'), 'packages': ('name', 'tip')}
    for kind, names in fields.items():
        entries = notes.get(kind, [])
        if not isinstance(entries, list) or len(entries) > 6:
            raise APIError('Use at most six entries per learning section.')
        clean[kind] = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != set(names) | {'source_id', 'quote'}:
                raise APIError('Each learning entry needs its documented fields, source_id and exact quote.')
            value = {k: text(v, 1400 if k in ('explanation', 'tip') else 900) for k, v in entry.items()}
            source = sources.get(value['source_id'], '')
            if not value['quote'] or value['quote'] not in source or '[removed]' in value['quote'] or '[credential removed]' in value['quote']:
                raise APIError('Cite an exact quote from this itch\'s completed work or evidence.')
            if any(private_text(v) != v for v in value.values()):
                raise APIError('Remove credentials from learning notes.')
            if any(not value[k] for k in names if k != 'caution'):
                raise APIError('Learning fields cannot be empty.')
            if kind == 'commands' and value['command'] not in value['quote']:
                raise APIError('A recorded command must appear exactly in its cited quote.')
            if kind == 'packages' and value['name'].casefold() not in value['quote'].casefold():
                raise APIError('A package name must appear in its cited quote; do not infer installed dependencies.')
            clean[kind].append(value)
    manager.set_setting(db, 'learning-notes:' + id, {'version': pack['notes_version'] + 1,
                        'basis': pack['work_revision'], 'notes': clean, 'at': now()})
    return get(manager, db, id)


def progress(manager, db, id, revision, lesson_id, done=True, expected_version=0):
    pack = get(manager, db, id)
    if revision != pack['revision'] or expected_version != pack['progress']['version']:
        raise APIError('This learning trail changed. Refresh it before saving progress.', 'conflict', 409)
    if not pack['eligible'] or lesson_id not in {l['id'] for l in pack['lessons']}:
        raise APIError('Choose a lesson in the current learning trail.')
    read = set(pack['progress']['read'])
    if done:
        read.add(lesson_id)
    else:
        read.discard(lesson_id)
    manager.set_setting(db, 'learning-progress:' + id, {'version': expected_version + 1,
                        'read': sorted(read), 'at': now()})
    return get(manager, db, id)


def definitions():
    from .registry import boolean, capability, integer, string
    def cap(name, description, props, required, write=False):
        item = capability('manager.learning.' + name, 'dumbmanager', description, props, required, tags=('learning', 'itches'))
        if write:
            item['mode'] = 'action'
            item['input_schema']['properties']['request_key'] = string(default='', maxLength=100)
        return item
    return [
        cap('get', 'Read an evidence-linked learning trail for one finished itch. Local only; no model, commands, acceptance or environment scan.', {'id': string()}, ('id',)),
        cap('record', 'Save agent-written lessons, exact recorded commands and package tips citing a source_id and exact quote from this itch. Read get first; never invent execution history.',
            {'id': string(), 'revision': string(), 'notes': string('JSON: lessons [{title,explanation,try_this,question,answer,source_id,quote}], commands [{command,explanation,caution,source_id,quote}], packages [{name,tip,source_id,quote}]. Up to 6 each. Replaces earlier learning notes; does not change the itch or accept it.', default='{}', maxLength=18000)}, ('id', 'revision'), True),
        cap('progress', 'Mark one learning lesson read/unread. Does not complete a plan step or accept an itch.',
            {'id': string(), 'revision': string(), 'lesson_id': string(), 'done': boolean(True),
             'expected_version': integer(0, 0, 1000000)}, ('id', 'revision', 'lesson_id'), True),
    ]
