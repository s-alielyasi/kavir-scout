# Kavir Scout

A private Telegram controller and browser assistant for Kavir Tire. It uses
async Playwright and the store's visible interface for login, inventory checks
and a guarded checkout workflow. Payment remains manual. The Telegram interface
is in Persian; this README describes setup and development in English.

The confirmed target is **Perfect (R14) KB27**, **185/65R14**, **2 tires**.
The store's current purchase limits always take precedence.

## Current status

The Telegram app runs on the prepared Linux workstation. The owner has confirmed
`/start`, `/status` and copyable responses. Real Telegram login/OTP integration
with the store, scheduled inventory observation, live checkout and usable payment
handoff still need supervised validation. Earlier CLI live-site observations are
historical evidence, not validation of the current Telegram workflow.

The bot defaults to `DRY_RUN=true` and `LIVE_CHECKOUT_APPROVED=false`. A dry run
can authenticate and observe inventory, but cannot select a product, change its
quantity, add it to the cart or create an order. Starting or restarting the bot
does not arm a run.

## Run on the prepared Linux workstation

From the repository root:

```bash
./run-telegram.sh --check-config
./run-telegram.sh
```

The launcher uses this checkout's `.venv`, works from any working directory and
does not install dependencies or create a system service. Keep its terminal
open and the machine awake. Use the graphical desktop session so manual browser
steps are accessible. If another instance is already running, use that instance
or stop it gracefully before starting a replacement.

Private settings live in `.env`. The prepared workstation uses installed Google
Chrome and a Telegram-only HTTP proxy; keep the existing proxy application
running. Tokens, numeric owner IDs and browser profiles must remain local.

## Set up a new checkout

Use **Python 3.11 or newer**. If `python3` is older, substitute a newer interpreter
in the environment-creation command. Then install the recorded dependencies:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt -c requirements-tested.txt
```

Choose the browser:

- With Google Chrome already installed, set `BROWSER_CHANNEL=chrome` in `.env`.
  No bundled Chromium download is needed.
- For Playwright's bundled Chromium on a supported OS, leave `BROWSER_CHANNEL`
  empty and run `./.venv/bin/python -m playwright install chromium`. System
  browser dependencies may also be needed. The pinned Playwright Chromium
  installer does not support the current Ubuntu 20.04 workstation; use Chrome
  there.

Create the private configuration **only if it does not already exist**:

```bash
cp -n .env.telegram.example .env
chmod 600 .env
```

For an existing `.env`, merge missing settings manually without replacing its
contents. Fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` and
`TELEGRAM_ALLOWED_CHAT_ID` locally, then run the config check and launcher above.
Both IDs identify the allowed owner in their private chat; usernames are not IDs.
Send `/start` to your own bot in Telegram after startup.

On Windows, create the environment with a Python 3.11+ interpreter and use
`.\.venv\Scripts\python.exe` instead of `./.venv/bin/python`. Run the app with
`python -m telegram_bot` using that interpreter; the Bash launcher is for Linux.
See the [operations guide](docs/telegram-operations.md) for setup and recovery.

## Daily Telegram workflow

1. Start the app before 08:00 Tehran time.
2. Send `/arm` in the allowed private chat, for example at 07:50.
3. Reply to the current national-ID and OTP prompts. Complete any manual browser
   challenge and confirm the account when asked. Existing sessions are checked,
   not assumed to belong to the requested account.
4. After authentication, the worker waits until 08:00 and begins scheduled
   observation without another command.

All schedule decisions use `Asia/Tehran` and the date of the armed run:

| Tehran time | Minimum spacing between inventory-check starts |
|---|---:|
| Before 08:00 | Login preparation and waiting; no periodic stock checks |
| 08:00–08:05 | 5 seconds |
| 08:05–08:10 | 15 seconds |
| 08:10–08:15 | 30 seconds |
| From 08:15 | No new check or order admission |

Checks run sequentially. Site cooldowns and slow responses can extend the spacing;
missed checks are not replayed in a burst. In dry-run mode, detecting available
target stock ends the run without checkout. A restart always returns to idle;
daily arming is never restored automatically. The configured schedule is not a
claim about the store's current sale hours.

| Command | Behavior |
|---|---|
| `/start` | Show help and the configured target; no browser or purchase starts. |
| `/arm` | Arm one run for today's Tehran date; reject after the cutoff. |
| `/status` | Show a nonsecret, copyable status snapshot. |
| `/cancel` | Request cancellation and bounded cleanup. |
| `/resume` | Resume only when replying to the current manual checkpoint; alternatively send `/resume CHECKPOINT_ID`. |

General responses can be copied and forwarded. Login prompts and payment-link
messages retain content protection. Incoming credentials are deleted on a
best-effort basis; Telegram is not an end-to-end encrypted credential channel.

## Configuration

[.env.telegram.example](.env.telegram.example) lists all bot settings. Explicitly
exported environment values override `.env`; relative profile paths are resolved
against the repository root. National ID and OTP are runtime inputs, not settings.
The obsolete `NATIONAL_ID` setting is ignored.

| Setting | Default / purpose |
|---|---|
| `TARGET_PRODUCT`, `TARGET_SIZE`, `TARGET_QUANTITY` | Confirmed model, size and quantity 2 |
| `HEADLESS` | `false`; visible browser for manual steps |
| `BROWSER_CHANNEL` | Empty for bundled Chromium; `chrome` for installed Chrome |
| `USER_DATA_DIR` | Bot example: `./data/telegram_profile` |
| `TELEGRAM_PROXY_URL` | Optional HTTP(S) proxy for both Telegram HTTP clients; does not configure the store browser |
| `DRY_RUN`, `LIVE_CHECKOUT_APPROVED` | `true`, `false`; live mode requires both an explicit configuration change and completed release gates |
| `DEBUG_ARTIFACTS_ENABLED` | Must remain `false` for the Telegram app |
| `OTP_INPUT_TIMEOUT_SECONDS` | 180; current input request lifetime, also bounded by the sale cutoff |
| `CHECKOUT_TIMEOUT_SECONDS`, `PAYMENT_HANDOFF_TTL_SECONDS` | 180 each; separate bounded checkout and handoff lifetimes |
| `GATEWAY_HOSTS` | `shaparak.ir`; HTTPS allowlist including its subdomains |

An order admitted before 08:15 may finish within its bounded checkout deadline.
No new order is admitted after the cutoff. The app never fills bank fields or
claims that delivering a gateway link means payment succeeded. Cross-device
payment-link usability remains unverified.

## CLI compatibility and order recovery

`main.py` remains a separate terminal-driven workflow. It starts browser activity
immediately, uses fixed `POLL_INTERVAL` spacing and **does not use the Telegram
dry-run switch or sale schedule**. Use the Telegram entry point for the daily
armed workflow. `.env.example` documents the CLI settings.

Both entry points share process/profile locks and the durable
`data/order_attempt.json` barrier. A possible order remains blocked across
cancellation, crashes and date changes until explicitly reconciled. Stop the app
and inspect the store's existing orders before using the local recovery commands:

```bash
./run-telegram.sh --show-attempt
# Only after checking the matching attempt and confirming that no order exists:
./run-telegram.sh --resolve-attempt no_order --attempt-run-id EXACT_RUN_ID
```

See the [operations guide](docs/telegram-operations.md) for the `order_exists`
resolution and uncertain checkout handling. Cancellation does not cancel an order
that the store may already have recorded.

## Development and verification

Tests use the standard-library `unittest` runner, synthetic Telegram messages,
an injectable clock and local browser fixtures. They never require real bot
credentials. Browser fixtures block unmatched page requests. To use bundled
Chromium:

```bash
./.venv/bin/python -m unittest discover -v
```

On the prepared Linux workstation, use installed Chrome:

```bash
TEST_BROWSER_CHANNEL=chrome ./.venv/bin/python -m unittest discover -v
./.venv/bin/python -m compileall -q main.py config.py kavirtire telegram_bot tests
./.venv/bin/python -m pip check
bash -n run-telegram.sh
git diff --check
```

`TEST_BROWSER_CHANNEL` only selects the fixture browser; tests do not consume the
private `.env`. Four-tire rows remain explicit synthetic regression data even
though the application default is two. Passing fixtures do not validate the live
store's checkout selectors or browser-written identity/cache storage.

## Project map and documentation

```text
config.py                 Validated CLI and Telegram settings
main.py                   Terminal workflow entry point
run-telegram.sh            Linux launcher for the private Telegram app
telegram_bot/             Access checks, short handlers, prompts and delivery
kavirtire/                Browser, login, inventory and checkout services
  orchestration/          One worker, Tehran schedule, input broker, order barrier
tests/                    Unit tests and offline browser fixtures
docs/                     Operations, architecture, status, plans and evidence
requirements*.txt         Runtime dependencies and tested constraints
```

Runtime `.env`, `data/`, `logs/`, `debug/`, `payment_url.txt`, `.venv/` and
`.tools/` are private/ignored and are not part of a transferable installation.
The browser profile still persists on disk. Telegram mode disables debug
artifacts and separate session exports; the CLI can create masked debug files
and a profile-bound merchant cookie backup. Neither is proof that the store
never writes personal data into its own browser storage.

Start with the [documentation index](docs/README.md), then use the
[architecture and selector map](docs/architecture.md),
[Telegram operations](docs/telegram-operations.md),
[current implementation status](docs/telegram-implementation-status.md) and
[dated verification record](docs/verification.md). Original plans are historical
design references; current behavior is described by the code and these guides.
