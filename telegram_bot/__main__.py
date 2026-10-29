"""python -m telegram_bot [--check-config]; no import-time activity."""
import argparse
import asyncio
from contextlib import ExitStack
import sys


def main():
    if sys.version_info < (3, 11):
        print('Python 3.11 or newer is required.', file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description='Private Kavir Scout Telegram controller; defaults to dry run.')
    parser.add_argument('--check-config', action='store_true')
    parser.add_argument('--show-attempt', action='store_true', help='Show the nonsecret local order barrier.')
    parser.add_argument('--resolve-attempt', choices=('no_order', 'order_exists'))
    parser.add_argument('--attempt-run-id', help='Exact run ID from --show-attempt; resolution requires local review.')
    args = parser.parse_args()
    try:
        from config import load_bot_settings, load_config
        from kavirtire.security import InstanceLock, SecretFilter
        from kavirtire.orchestration.order_attempts import OrderAttemptStore
        if args.show_attempt or args.resolve_attempt:
            import json
            config = load_config()
            with ExitStack() as locks:
                locks.enter_context(InstanceLock(config.root / 'data/bot.lock'))
                locks.enter_context(InstanceLock(config.user_data_dir / '.kavir-scout.lock'))
                store = OrderAttemptStore(config.root / 'data/order_attempt.json')
                if args.resolve_attempt:
                    store.resolve(args.attempt_run_id or '', args.resolve_attempt)
                print(json.dumps(store.read(), ensure_ascii=False))
            return 0
        settings = load_bot_settings()
        if args.check_config:
            print('Telegram configuration valid. Secrets omitted; no connection or browser started.')
            return 0
        from kavirtire.diagnostics import setup_logging, LOG
        from telegram_bot.app import build_application, serve
        setup_logging(settings.retailer.root, SecretFilter([settings.token]), tehran=True)
        with ExitStack() as locks:
            locks.enter_context(InstanceLock(settings.retailer.root / 'data/bot.lock'))
            locks.enter_context(InstanceLock(settings.retailer.user_data_dir / '.kavir-scout.lock'))
            runtime = build_application(settings)
            asyncio.run(serve(runtime))
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 130
    except Exception:
        # SDK errors can embed bot tokens and bank URLs. Never print their body.
        print('Stopped: check private configuration, local locks and the operations guide. Details omitted.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
