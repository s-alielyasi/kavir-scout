"""Private owner identity and durable daily admission; never part of settings/logs."""
from datetime import date
import json
import os
from pathlib import Path
import tempfile

from kavirtire.orchestration.input_broker import normalize_credential


def atomic_private_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.private-')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


class OwnerProfile:
    def __init__(self, root: Path, user_id: int, chat_id: int):
        self.path = root / 'data/owner_profile.json'
        self.user_id, self.chat_id = user_id, chat_id

    def national_id(self) -> str | None:
        try:
            record = json.loads(self.path.read_text(encoding='utf-8'))
            if (record['version'] != 1 or record['user_id'] != self.user_id
                    or record['chat_id'] != self.chat_id):
                raise ValueError
            return normalize_credential('national_id', record['national_id'])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise RuntimeError('Owner profile is invalid; register the identity again.') from None

    def save(self, value: str) -> None:
        identity = normalize_credential('national_id', value)
        atomic_private_json(self.path, {'version': 1, 'user_id': self.user_id,
            'chat_id': self.chat_id, 'national_id': identity})


class DailyAdmission:
    def __init__(self, root: Path):
        self.path = root / 'data/daily_start.json'

    def claim(self, day: date) -> bool:
        try:
            record = json.loads(self.path.read_text(encoding='utf-8'))
            previous = date.fromisoformat(record['date'])
            if record['version'] != 1:
                raise ValueError
            # Also reject a rollback to a previously consumed date.
            if previous >= day:
                return False
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError('Daily admission record requires local review.') from None
        atomic_private_json(self.path, {'version': 1, 'date': day.isoformat()})
        return True
