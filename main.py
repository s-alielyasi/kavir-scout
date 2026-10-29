"""Run with Python 3.11+: python main.py. No network activity at import time."""
import argparse
import asyncio
from contextlib import ExitStack
import sys


def main() -> int:
    if sys.version_info < (3, 11):
        print('Python 3.11 or newer is required.', file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description='Kavir Tire UI-only order assistant; stops at payment.')
    parser.add_argument('--check-config', action='store_true', help='Validate .env without opening a browser.')
    args = parser.parse_args()
    try:
        from config import load_config
        config = load_config()
    except (ValueError, ImportError):
        print('Invalid configuration or missing dependencies. Check .env and requirements.txt.', file=sys.stderr)
        return 2
    if args.check_config:
        print('Configuration valid. No browser started; identity is requested at runtime.')
        return 0
    from kavirtire.diagnostics import LOG, setup_logging
    from kavirtire.security import InstanceLock, SecretFilter
    secrets = SecretFilter()
    setup_logging(config.root, secrets)
    try:
        from kavirtire.workflow import run
        with ExitStack() as stack:
            stack.enter_context(InstanceLock(config.root / 'data/bot.lock'))
            stack.enter_context(InstanceLock(config.user_data_dir / '.kavir-scout.lock'))
            LOG.info('Starting Kavir Tire bot...')
            # Avoid presenting a previous run's URL as a new order's gateway.
            (config.root / 'payment_url.txt').unlink(missing_ok=True)
            asyncio.run(run(config, secrets))
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        LOG.info('Monitoring stopped by user. Browser/session cleanup completed where possible.')
        return 130
    except EOFError:
        LOG.error('Terminal input closed. Run in an interactive terminal for OTP/manual steps.')
        return 1
    except Exception as error:
        # Playwright exception bodies can include entered values / tokens.
        from kavirtire.errors import BotError
        if isinstance(error, (BotError, RuntimeError)) and not error.__class__.__module__.startswith('playwright'):
            LOG.error('%s', str(error))
        else:
            LOG.error('Stopped safely (%s). Check local debug artifacts and README.', type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
