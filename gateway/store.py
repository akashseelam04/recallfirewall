"""Transactional control journal, not a replacement for sponsor analytics.

Only trusted application code can register/revoke tasks or change input state.
No method here is exposed as an agent administration tool.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from gateway.hotdata import TaskBinding


class StaleTask(Exception):
    pass


class ControlStore:
    def __init__(self, path: str | Path = ':memory:'):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                input_epoch INTEGER NOT NULL,
                knowledge_revision INTEGER NOT NULL,
                input_state TEXT NOT NULL CHECK(input_state IN ('READY', 'DIRTY'))
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
                token_sha256 TEXT NOT NULL UNIQUE,
                binding_json TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS active_tasks (
                incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
                facility_id TEXT NOT NULL,
                role TEXT NOT NULL,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                PRIMARY KEY(incident_id, facility_id, role)
            );
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                result_json TEXT NOT NULL
            );
        ''')

    @contextmanager
    def transaction(self):
        with self._lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def close(self):
        with self._lock:
            self.db.close()

    def register(self, binding: TaskBinding):
        """Immutable registration; replaying startup never clears revocation."""
        encoded = json.dumps(asdict(binding), sort_keys=True)
        with self.transaction() as db:
            existing = db.execute('SELECT binding_json FROM tasks WHERE task_id=?',
                                  (binding.task_id,)).fetchone()
            if existing:
                if existing['binding_json'] != encoded:
                    raise ValueError('Task binding cannot be changed; create a new task')
                return
            db.execute('INSERT OR IGNORE INTO incidents VALUES (?, ?, ?, ?)',
                       (binding.incident_id, binding.input_epoch, binding.knowledge_revision, 'READY'))
            incident = db.execute('SELECT * FROM incidents WHERE incident_id=?',
                                  (binding.incident_id,)).fetchone()
            if (incident['input_state'] != 'READY' or incident['input_epoch'] != binding.input_epoch
                    or incident['knowledge_revision'] != binding.knowledge_revision):
                raise StaleTask('Cannot register against an obsolete or unpublished input basis')
            db.execute('INSERT INTO tasks(task_id, incident_id, token_sha256, binding_json) VALUES (?, ?, ?, ?)',
                       (binding.task_id, binding.incident_id, binding.token_sha256, encoded))
            db.execute('INSERT INTO active_tasks VALUES (?, ?, ?, ?) '
                       'ON CONFLICT(incident_id, facility_id, role) DO UPDATE SET task_id=excluded.task_id',
                       (binding.incident_id, binding.facility_id, binding.role, binding.task_id))

    def credential_binding(self, task_id: str) -> TaskBinding | None:
        with self.transaction() as db:
            row = db.execute('SELECT binding_json, revoked FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            if row is None or row['revoked']:
                return None
            return TaskBinding(**json.loads(row['binding_json']))

    def revoke(self, task_id: str):
        with self.transaction() as db:
            if db.execute('UPDATE tasks SET revoked=1 WHERE task_id=?', (task_id,)).rowcount != 1:
                raise KeyError('Unknown task')

    def invalidate_inputs(self, incident_id: str, expected_epoch: int) -> int:
        """Trusted caller has accepted new input; stop old tasks before ingestion.

        Source deduplication and approval invalidation must join this transaction
        when those registries exist. This method is not a complete ingestion API.
        """
        with self.transaction() as db:
            changed = db.execute('UPDATE incidents SET input_epoch=input_epoch+1, input_state=? '
                                 'WHERE incident_id=? AND input_epoch=?',
                                 ('DIRTY', incident_id, expected_epoch)).rowcount
            if changed != 1:
                raise StaleTask('Input epoch changed')
            return expected_epoch + 1

    def publish_inputs(self, incident_id: str, expected_epoch: int, knowledge_revision: int):
        """Trusted publisher calls only after required sponsor writes succeed."""
        if type(knowledge_revision) is not int or knowledge_revision < 0:
            raise ValueError('Invalid knowledge revision')
        with self.transaction() as db:
            changed = db.execute('UPDATE incidents SET input_state=?, knowledge_revision=? '
                                 'WHERE incident_id=? AND input_epoch=? AND input_state=? '
                                 'AND knowledge_revision<=?',
                                 ('READY', knowledge_revision, incident_id, expected_epoch, 'DIRTY',
                                  knowledge_revision)).rowcount
            if changed != 1:
                raise StaleTask('Cannot publish an obsolete input epoch or revision')

    @staticmethod
    def _current(db, binding: TaskBinding) -> bool:
        row = db.execute('''SELECT i.input_epoch, i.knowledge_revision, i.input_state,
                                   t.revoked, a.task_id AS active_task_id
                            FROM tasks t JOIN incidents i ON i.incident_id=t.incident_id
                            JOIN active_tasks a ON a.incident_id=i.incident_id
                            WHERE t.task_id=? AND a.facility_id=? AND a.role=?''',
                         (binding.task_id, binding.facility_id, binding.role)).fetchone()
        return bool(row and not row['revoked'] and binding.expires_at > time.time()
                    and row['input_state'] == 'READY'
                    and row['input_epoch'] == binding.input_epoch
                    and row['knowledge_revision'] == binding.knowledge_revision
                    and row['active_task_id'] == binding.task_id)

    def require_current(self, binding: TaskBinding):
        with self.transaction() as db:
            if not self._current(db, binding):
                raise StaleTask('Task input basis is no longer current')

    def save_receipt(self, binding: TaskBinding, result: dict) -> dict:
        # Freshness and insertion share a write transaction, including updates
        # made by another process while the sponsor query was running.
        with self.transaction() as db:
            saved = dict(result)
            saved['admission_status'] = 'CURRENT' if self._current(db, binding) else 'STALE'
            if saved['admission_status'] == 'STALE':
                saved['status'] = 'STALE'
            db.execute('INSERT INTO receipts VALUES (?, ?, ?)',
                       (saved['receipt_id'], binding.task_id, json.dumps(saved, sort_keys=True)))
            return saved

    def receipt(self, binding: TaskBinding, receipt_id: str) -> dict | None:
        with self.transaction() as db:
            row = db.execute('SELECT result_json FROM receipts WHERE receipt_id=? AND task_id=?',
                             (receipt_id, binding.task_id)).fetchone()
            if row is None:
                return None
            result = json.loads(row['result_json'])
            # Preserve the original receipt; annotate its current usability.
            result['current_status'] = ('CURRENT' if result['admission_status'] == 'CURRENT'
                                        and self._current(db, binding) else 'STALE')
            return result
