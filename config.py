"""Validated environment settings; importing this module has no side effects."""
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re
from typing import Mapping

ROOT = Path(__file__).resolve().parent
STORE_URL = 'https://kavirtire.ir/esale'
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


@dataclass(frozen=True)
class Config:
    national_id: str = field(repr=False)
    poll_interval: float
    target_product: str
    target_size: str
    target_quantity: int
    headless: bool
    user_data_dir: Path
    max_retries: int
    timeout_ms: int
    gateway_hosts: tuple[str, ...]
    root: Path = ROOT
    store_url: str = STORE_URL

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> 'Config':
        """Read and validate settings without requiring an ID for a valid session."""
        e = os.environ if env is None else env
        interval = float(e.get('POLL_INTERVAL', '5'))
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError('POLL_INTERVAL must be a finite positive number.')
        quantity = int(e.get('TARGET_QUANTITY', '4'))
        retries = int(e.get('MAX_RETRIES', '3'))
        timeout = int(e.get('TIMEOUT_MS', '15000'))
        if quantity < 1 or retries < 1 or timeout < 1000:
            raise ValueError('Quantity/retries must be positive; TIMEOUT_MS >= 1000.')
        headless = e.get('HEADLESS', 'false').strip().lower()
        if headless not in ('true', 'false'):
            raise ValueError('HEADLESS must be true or false.')
        national_id = e.get('NATIONAL_ID', '').strip().translate(DIGITS)
        if national_id and not re.fullmatch(r'[0-9]{10}', national_id):
            raise ValueError('NATIONAL_ID must contain exactly ten digits.')
        product = e.get('TARGET_PRODUCT', 'Perfect (R14) KB27').strip()
        size = e.get('TARGET_SIZE', '185/65R14').strip()
        if not product or not size:
            raise ValueError('TARGET_PRODUCT and TARGET_SIZE cannot be empty.')
        hosts = tuple(h.strip().lower().rstrip('.') for h in
                      e.get('GATEWAY_HOSTS', 'shaparak.ir').split(',') if h.strip())
        if not hosts or any(not re.fullmatch(r'(?:[a-z0-9-]+\.)+[a-z]{2,}', h)
                            or h == 'kavirtire.ir' for h in hosts):
            raise ValueError('GATEWAY_HOSTS must list explicit external DNS hosts.')
        profile = Path(e.get('USER_DATA_DIR', './data/browser_profile')).expanduser()
        if not profile.is_absolute():
            profile = ROOT / profile
        return cls(national_id, interval, product, size, quantity, headless == 'true',
                   profile.resolve(), retries, timeout, hosts)


def load_config() -> Config:
    """Load the project's .env; explicitly exported environment values win."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    return Config.from_env()
