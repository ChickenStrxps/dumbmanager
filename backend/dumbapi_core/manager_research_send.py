"""Research uses the existing durable media/T3 handoff, with separate receipts."""
import hashlib

from .common import APIError, now
from .manager import text
from .manager_send import Handoff
from .manager_research import get, selected, save, scope
from .t3 import T3


class ResearchHandoff(Handoff):
    def finish(self, id, request_key, result):
        with self.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = selected(self.manager, db, id, self.run_id)
            if not row['send'].get('receipt'):
                row['send']['receipt'] = result
                # A fast agent may have recorded a report before the receipt returned.
                if not row['reports']: row['state'] = 'awaiting_report'
                save(self.manager, db, row)
        return result

    def research_send(self, id, run_id, expected_version, thread_id, request_key):
        T3.thread_id(thread_id)
        request_key = text(request_key, 100)
        if not request_key: raise APIError('Use a stable research send key.')
        self.run_id = run_id
        with self.manager.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = selected(self.manager, db, id, run_id)
            itch = self.manager.get(db, id, 'itch')
            pending = row['send']
            if pending:
                if pending['request_key'] != request_key or pending['thread_id'] != thread_id:
                    raise APIError('This research pass has a frozen send. Recover its original destination and key.', 'conflict', 409)
            else:
                if row['version'] != expected_version or row['scope_revision'] != scope(itch):
                    raise APIError('The itch or research changed. Refresh before sending.', 'conflict', 409)
                if row['reports']: raise APIError('Prepare a new research pass to ask for further research.')
                row['send'] = {'request_key': request_key, 'thread_id': thread_id, 'at': now(), 'receipt': None}
                row['state'] = 'send_unconfirmed'
                self.manager.set_setting(db, 'research-thread', thread_id)
                save(self.manager, db, row)
        # Namespaced identities reuse Handoff's lost-response protection without
        # appending an implementation handoff or changing itch state/version.
        key = 'research-' + hashlib.sha256((run_id + ':' + request_key).encode()).hexdigest()[:64]
        self.send(id, thread_id, key, message=row['brief'])
        with self.manager.db() as db:
            return get(self.manager, db, id, run_id)
