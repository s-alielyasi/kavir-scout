"""Atomic nonsecret barrier; a crash never grants permission to create again."""
from datetime import date
import json
import os
from pathlib import Path
import re
import tempfile


class AttemptBlocked(RuntimeError):
    pass


class OrderAttemptStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            record = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(record, dict) or record.get('version') != 1
                    or not re.fullmatch(r'[a-f0-9]{32}', record.get('run_id', ''))
                    or record.get('status') not in ('prepared', 'handed_off', 'resolved')):
                raise ValueError
            date.fromisoformat(record['sale_date'])
            return record
        except (ValueError, KeyError, TypeError, OSError):
            raise AttemptBlocked('Order guard is unreadable; local reconciliation required.') from None

    def blocked(self) -> bool:
        try:
            record = self.read()
            return record is not None and record['status'] != 'resolved'
        except AttemptBlocked:
            return True

    def _write(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.attempt-')
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                json.dump(record, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            if os.name != 'nt':
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def begin(self, run_id: str, sale_date: date) -> None:
        if self.blocked() or not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise AttemptBlocked('Unresolved order attempt; inspect retailer orders locally.')
        self._write({'version': 1, 'run_id': run_id, 'sale_date': sale_date.isoformat(), 'status': 'prepared'})

    def handed_off(self, run_id: str) -> None:
        record = self.read()
        if record is None or record['run_id'] != run_id or record['status'] != 'prepared':
            raise AttemptBlocked('Order guard does not match the active run.')
        self._write(record | {'status': 'handed_off'})

    def resolve(self, run_id: str, disposition: str) -> None:
        record = self.read()
        if (record is None or record['run_id'] != run_id
                or disposition not in ('no_order', 'order_exists')):
            raise AttemptBlocked('Resolution must match the recorded run and a supported disposition.')
        self._write(record | {'status': 'resolved', 'disposition': disposition})
