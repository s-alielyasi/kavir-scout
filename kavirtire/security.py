"""Secret redaction, payment origin checks and OS-held instance locks."""
import logging
from pathlib import Path
import re
from types import TracebackType
from urllib.parse import urlsplit


def gateway_url(url: str, hosts: tuple[str, ...]) -> bool:
    """Only explicit HTTPS payment hosts or their DNS subdomains are trusted."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443)
                and host != 'kavirtire.ir' and not host.endswith('.kavirtire.ir')
                and any(host == h or host.endswith('.' + h) for h in hosts))
    except ValueError:
        return False


def merchant_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        host = (p.hostname or '').lower().rstrip('.')
        return p.scheme == 'https' and (host == 'kavirtire.ir' or host.endswith('.kavirtire.ir'))
    except ValueError:
        return False


def safe_url(url: str) -> str:
    """Do not log tokens in URL paths, queries or fragments."""
    p = urlsplit(url)
    return f'{p.scheme}://{p.hostname or "unknown"}/[path redacted]'


class SecretFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self.secrets = list(secrets or [])

    def redact(self, message: str) -> str:
        for secret in sorted(filter(None, self.secrets), key=len, reverse=True):
            message = message.replace(secret, '[REDACTED]')
        return re.sub(r'\d{10,}', '[REDACTED]', message)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        return True


class InstanceLock:
    """Kernel-held lock: automatically released even after a process crash."""
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def __enter__(self) -> 'InstanceLock':
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if __import__('os').name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            self.file = None
            raise RuntimeError('Another bot instance is using this project/profile.') from error
        return self

    def __exit__(self, kind: type | None, value: BaseException | None,
                 traceback: TracebackType | None) -> None:
        if self.file:
            if __import__('os').name == 'nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None
