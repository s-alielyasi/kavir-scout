# Architecture and repository map

This describes the implemented application. See [operations](telegram-operations.md)
for usage, [status](telegram-implementation-status.md) for release gates and
[verification](verification.md) for the dates and limits of live observations.

## Source layout

```text
config.py
main.py
run-telegram.sh
telegram_bot/
  __main__.py              CLI flags, process/profile locks, safe exit
  app.py                   PTB composition and explicit async lifecycle
  authorization.py         Exact user/chat/private-message admission
  handlers.py              Short command/input handlers and nonsecret status
  interactions.py          Correlated credential/manual prompts
  notifications.py         Fixed-recipient messages and private payment button
kavirtire/
  browser.py               Persistent browser and optional cookie-only backup
  login.py                 Terms, positive session evidence, transient ID/OTP
  shop.py                  Exact target matching, refresh and stock evidence
  checkout.py              Quantity/summary checks, submit phases, gateway watch
  guard.py                 Human challenges, queue and HTTP cooldown handling
  selectors.py             Centralized selectors and DOM observation scripts
  ui.py                    Semantic locators and ordinary UI waits
  text.py                  Persian normalization and strict quantity parsing
  interactions.py          Interaction protocol and terminal adapter
  workflow.py              Separate terminal-driven workflow
  diagnostics.py           Filtered logging and optional masked debug artifacts
  security.py              Host validation, secret filtering and kernel locks
  errors.py                Domain exceptions
  orchestration/
    purchase_workflow.py   Single task, transitions, deadlines and cancellation
    retailer.py            Browser adapter owned by that task
    scheduling.py          Tehran clock and date-bound 5/15/30-second windows
    input_broker.py        One transient correlated input/checkpoint request
    order_attempts.py      Durable nonsecret attempt marker and reconciliation
    models.py              State transitions and immutable status/result models
tests/
  browser_support.py       Shared synthetic rows and offline browser contexts
  test_*.py                Unit, concurrency, transport and browser regressions
docs/                      Current guides, original plans and dated evidence
```

Keep selectors inside the package: a root `selectors.py` would shadow Python's
standard-library module used by asyncio. Runtime packages have no dependency on
the test helpers or ignored local installation tools.

## Ownership and execution

Telegram messages pass the universal authorization gate before reaching a short
handler. Handlers signal `PurchaseOrchestrator`; they do not own Playwright pages
or await the full login/monitor/checkout workflow. This keeps `/status` and
`/cancel` available while an input request or browser task is waiting.

The orchestrator owns one background workflow, its clock, input broker and
attempt store. The retailer adapter owns browser-service calls. The persistent
context stays on that async event loop. The broker correlates owner replies with
the current run, prompt, generation and deadline, and consumes each input once.
No credential is part of shared configuration or the status snapshot.

Boot and restart are idle. `/arm` binds a run to today's Tehran date. Login can
complete before 08:00; periodic observation starts at 08:00. New checks/admissions
stop at 08:15. Dry run ends before selection. Live admission requires both explicit
configuration gates and a compatible observed purchase policy. Before a possible
order action, the durable attempt marker is written atomically with fsync.

The explicitly requested `/test_inventory` command (or `--test-inventory` boot
flag) instead runs login and one inventory refresh/check without the sale window.
It requires dry-run settings, shares single-worker/authorization/attempt checks
and returns before any selection for every recognized stock result. Its ten-minute
deadline uses elapsed monotonic time; input TTL and cancellation still apply.
It does not modify the actual clock, private settings or the daily schedule.

Cancellation stops further actions and bounds cleanup; it cannot undo a server
side effect. An unresolved marker survives restarts and date changes. Local
reconciliation requires the exact run ID while both project/profile locks are
free. A recognized gateway result must originate from the current checkout;
preexisting and unrelated gateway tabs are rejected.

`main.py` owns a separate terminal workflow over the same retailer services,
locks and attempt store. It has fixed-interval monitoring and no Telegram dry-run
or Tehran schedule. Its behavior must not be inferred from Telegram settings.

## Configuration and private files

`Config` holds immutable retailer settings; `BotSettings` adds token, allowlist,
schedule, dry-run gates, deadlines and an optional HTTP(S) Telegram proxy. Empty
`BROWSER_CHANNEL` selects Playwright Chromium; `chrome` selects installed Chrome.
The proxy is passed to both Telegram HTTP clients, not to the store browser.
`BROWSER_DIRECT_CONNECTION=true` adds `--no-proxy-server` to the store browser,
so it does not inherit desktop HTTP/SOCKS proxy settings. False preserves normal
system-proxy behavior. This changes neither process-wide proxy variables nor
OS VPN/TUN routes; Telegram's explicit proxy remains independent. Mobile and
desktop Telegram clients are not part of the Linux bot's transport lifecycle.

The confirmed application default is quantity 2. Historical four-tire plans and
explicit four-tire test fixtures do not override that default or the store's
current policy. `.env.example` is for the terminal entry point;
`.env.telegram.example` covers the bot. Exported environment values override the
private `.env` without copying its values into process-global environment state.

| Path | Contents and lifecycle |
|---|---|
| `.env` | Local secrets/settings; owner-only permissions on the prepared Linux host |
| `data/bot.lock` | Kernel-held project lock; a leftover file does not mean a live process |
| `USER_DATA_DIR/` | Persistent browser profile and profile lock; bot example uses `data/telegram_profile` |
| `data/order_attempt.json` | Run ID, date, attempt status and explicit resolution; no identity, cookie or URL |
| `USER_DATA_DIR/.kavir-session.json` | Optional CLI-only merchant cookie backup; no origin storage export |
| `logs/kavirtire.log` | Filtered runtime diagnostics; bot HTTP framework payloads are suppressed |
| `debug/` | Optional CLI masked screenshots/HTML; disabled in bot mode |
| `payment_url.txt` | CLI-only gateway output; disabled in bot mode |
| `.venv/`, `.tools/` | Ignored local environment and installation tools; not portable source |

All these paths are ignored by Git. The old `data/storage_state.json` export is
not automatically restored. Chromium can still persist site-owned storage,
cache and autofill; a real-device privacy audit remains required. Telegram
message deletion and Python reference cleanup do not guarantee server/device
erasure or zeroed RAM.

General bot output is copyable. Credential prompts and the payment message use
content protection. Payment URLs are delivered only to the fixed owner chat;
they are not logged or written to a bot output file. Payment DOM is never read
or filled, and delivered links may depend on the original browser session.

## Browser tests

`tests/browser_support.py` provides explicit synthetic four-tire configuration,
shared rows and contexts that abort unmatched page requests. Fixture routes
registered later take precedence. `TEST_BROWSER_CHANNEL=chrome` selects installed
Chrome without reading `.env`; an empty value uses bundled Chromium. Persistence
regressions use temporary profiles. No external monkeypatch runner is needed.

The suite covers authentication fixtures, copyable status, protected payment,
authorization, stale/replayed input, schedule boundaries, cancellation, checkout
preflight, duplicate submission prevention, correlated gateway detection and
durable order recovery. Fixtures do not establish current live selector validity.

## Selector provenance

The following is historical evidence from supervised/public CLI inspections on
2026-10-27, not a fresh inspection of the store. Selectors live in
`kavirtire/selectors.py`; the scheduled morning and checkout workflows still need
supervised store validation.

On 2026-10-29, a supervised Telegram run also completed login and one out-of-stock
refresh with the headed browser. This validates that observed flow, not every
selector below or real checkout. The owner then selected headless operation;
manual challenges/account confirmation still require appropriate human access.

| Surface | Recorded evidence / remaining limit |
|---|---|
| Public terms | `#confirm` and ordinary login link observed; terms then stated two tires per six months per national ID/plate |
| National-ID form | `/esale/login`, `input[name="n_code"]`, ordinary submit observed |
| OTP | `#code-verification`, `autocomplete="one-time-code"`, case-sensitive eight-character code and ordinary submit/resend observed; split fields remain fixture-only |
| Account / purchase navigation | Positive logout/profile evidence and purchase link with decorative icon observed; automatic account-ID matching remains unverified |
| Target product / unavailable state | `.product`, `h2.title`, full model and size in one card under `.products` observed; available-product selection not tested live |
| Refresh | `#refresh-availability`, actual inventory completion and site's disabled-button cooldown observed |
| Quantity and order summary | General selectors and strict fixture checks implemented; actual authenticated checkout DOM not verified |
| Gateway / cross-device handoff | HTTPS host checks and popup/same-tab fixtures implemented; real order and portable payment link not verified |
| Protection controls | Supported visible challenge/queue/HTTP cases pause; unknown or changed pages require manual inspection |

Record new live evidence separately, update only supported selectors, and run
the corresponding fixture regressions. Do not infer a successful live purchase
from a passing test or a login that worked in an earlier deployment.
