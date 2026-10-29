"""Validated environment settings; importing this module has no side effects."""
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STORE_URL = 'https://kavirtire.ir/esale'
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


@dataclass(frozen=True)
class Config:
    poll_interval: float
    target_product: str
    target_size: str
    target_quantity: int
    headless: bool
    user_data_dir: Path
    max_retries: int
    timeout_ms: int
    gateway_hosts: tuple[str, ...]
    debug_artifacts: bool = True
    session_backup: bool = True
    gateway_output: bool = True
    root: Path = ROOT
    store_url: str = STORE_URL
    browser_channel: str | None = None
    browser_direct_connection: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> 'Config':
        """Read and validate settings without requiring an ID for a valid session."""
        e = os.environ if env is None else env
        interval = float(e.get('POLL_INTERVAL', '5'))
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError('POLL_INTERVAL must be a finite positive number.')
        quantity = int(e.get('TARGET_QUANTITY', '2'))
        retries = int(e.get('MAX_RETRIES', '3'))
        timeout = int(e.get('TIMEOUT_MS', '15000'))
        if quantity < 1 or retries < 1 or timeout < 1000:
            raise ValueError('Quantity/retries must be positive; TIMEOUT_MS >= 1000.')
        headless = e.get('HEADLESS', 'false').strip().lower()
        if headless not in ('true', 'false'):
            raise ValueError('HEADLESS must be true or false.')
        channel = e.get('BROWSER_CHANNEL', '').strip().lower()
        if channel not in ('', 'chrome'):
            raise ValueError('BROWSER_CHANNEL must be empty or chrome.')
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
        return cls(interval, product, size, quantity, headless == 'true',
                   profile.resolve(), retries, timeout, hosts, browser_channel=channel or None,
                   browser_direct_connection=boolean(e, 'BROWSER_DIRECT_CONNECTION', 'true'))


def load_config() -> Config:
    """Load the project's .env; explicitly exported environment values win."""
    return Config.from_env(settings_environment())


def settings_environment() -> dict[str, str]:
    from dotenv import dotenv_values
    file_values = {k: v for k, v in dotenv_values(ROOT / '.env').items()
                   if k != 'NATIONAL_ID' and v is not None}
    return file_values | dict(os.environ)


def boolean(e: Mapping[str, str], key: str, default: str) -> bool:
    value = e.get(key, default).strip().lower()
    if value not in ('true', 'false'):
        raise ValueError(f'{key} must be true or false.')
    return value == 'true'


@dataclass(frozen=True)
class BotSettings:
    token: str = field(repr=False)
    allowed_user_id: int
    allowed_chat_id: int
    retailer: Config
    dry_run: bool
    schedule: object
    delete_sensitive_messages: bool = True
    otp_timeout: int = 180
    checkout_timeout: int = 180
    handoff_ttl: int = 180
    live_checkout_approved: bool = False
    proxy_url: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> 'BotSettings':
        from datetime import time
        from dataclasses import replace
        from kavirtire.orchestration.scheduling import Schedule, TEHRAN
        e = os.environ if env is None else env
        token = e.get('TELEGRAM_BOT_TOKEN', '').strip()
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', token):
            raise ValueError('A Telegram bot token is required.')
        ids = []
        for key in ('TELEGRAM_ALLOWED_USER_ID', 'TELEGRAM_ALLOWED_CHAT_ID'):
            value = e.get(key, '')
            if not re.fullmatch(r'[1-9][0-9]*', value):
                raise ValueError(f'{key} must be a positive numeric private-chat ID.')
            ids.append(int(value))
        if e.get('SALE_TIMEZONE', 'Asia/Tehran') != TEHRAN.key:
            raise ValueError('SALE_TIMEZONE must be Asia/Tehran.')
        schedule = Schedule(
            start=time.fromisoformat(e.get('SALE_START_TIME', '08:00:00')),
            ends=tuple(time.fromisoformat(e.get(f'POLL_WINDOW_{i}_END', default))
                       for i, default in enumerate(('08:05:00', '08:10:00', '08:15:00'), 1)),
            intervals=tuple(int(e.get(f'POLL_WINDOW_{i}_INTERVAL', str(default)))
                            for i, default in enumerate((5, 15, 30), 1)),
            reminder=time.fromisoformat(e.get('LOGIN_REMINDER_TIME', '07:55:00')))
        durations = tuple(int(e.get(key, '180')) for key in (
            'OTP_INPUT_TIMEOUT_SECONDS', 'CHECKOUT_TIMEOUT_SECONDS', 'PAYMENT_HANDOFF_TTL_SECONDS'))
        if any(d <= 0 for d in durations):
            raise ValueError('Input, checkout and handoff timeouts must be positive.')
        dry_run = boolean(e, 'DRY_RUN', 'true')
        approved = boolean(e, 'LIVE_CHECKOUT_APPROVED', 'false')
        if not dry_run and not approved:
            raise ValueError('Live checkout requires completion of the documented release gates.')
        if boolean(e, 'DEBUG_ARTIFACTS_ENABLED', 'false'):
            raise ValueError('Bot authentication/profile artifacts must remain disabled.')
        proxy = e.get('TELEGRAM_PROXY_URL', '').strip()
        if proxy:
            try:
                parsed = urlsplit(proxy)
                if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                        or parsed.path not in ('', '/') or parsed.query or parsed.fragment
                        or any(c.isspace() for c in proxy)):
                    raise ValueError
                parsed.port  # Reject malformed/out-of-range ports without exposing the URL.
            except ValueError:
                raise ValueError('TELEGRAM_PROXY_URL must be an HTTP(S) proxy URL.') from None
        # The bot never consumes a legacy national-ID environment setting.
        retailer = replace(Config.from_env({k: v for k, v in e.items() if k != 'NATIONAL_ID'}),
                           debug_artifacts=False, session_backup=False, gateway_output=False)
        return cls(token, *ids, retailer, dry_run, schedule,
                   boolean(e, 'DELETE_SENSITIVE_MESSAGES', 'true'), *durations, approved,
                   proxy_url=proxy or None)


def load_bot_settings() -> BotSettings:
    # Unlike CLI compatibility loading, do not copy legacy identity settings
    # into process-global os.environ. Exported values still take precedence.
    return BotSettings.from_env(settings_environment())
