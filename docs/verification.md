# Verification record

Chronological record: environment descriptions, defaults and results belong to
the dated section where they appear. Current setup/status is in the
[documentation index](README.md), [architecture](architecture.md) and
[implementation status](telegram-implementation-status.md). Later owner decisions
supersede historical configuration descriptions; today's default quantity is 2.

Initial environment (2026-10-27): Windows, local portable CPython 3.12.10; Playwright 1.64.1 and its
Chromium installed under ignored `.tools/`. Product supports Python 3.11+ and
does not depend on the portable installation. Only playwright and python-dotenv
are declared runtime dependencies. Standard-library unittest is the test runner.

## Real public inspection

- Browser inspection with headed persistent Chromium succeeded: HTTP 200,
  title `فروشگاه کویرتایر`, URL `https://kavirtire.ir/esale`.
- Public terms explicitly state 2 tires per 6 months per national ID/license
  plate. Default target quantity 4 intentionally fails this cap.
- Verified ordinary checkbox `#confirm`, link `ورود به حساب`, public login URL
  `/esale/login`, national-ID input `input[name="n_code"]`, submit `ورود`.
- Checked public login form only. Never entered a national ID, requested SMS,
  submitted an OTP, inspected an authenticated account, created an order, or paid.
- Running `main.py` with its defaults opened the real site, stopped on the cap,
  saved masked PNG/sanitized HTML and exported state, closed the browser, returned
  exit code 1. This is the intended safety exit, not a successful live checkout.
- A generic web-fetch tool returned 403; the headed Chromium inspection above
  succeeded normally. No protection-bypass setting was used.

## Automated coverage

Final run: `python -m unittest discover -v` — **38 tests passed**, exit code 0,
50.734 seconds. Final `compileall`, runtime imports and `--check-config` also
passed. `git check-ignore` confirmed all secret/runtime paths are ignored.

The suite runs real headless Chromium against HTML/route fixtures, with dummy
identity/OTP values and no live purchase/login requests. It covers:

- config defaults, invalid/non-finite values, relative paths and leading zeros;
- Unicode/Persian normalization and complete model/size boundaries;
- exclusive OS-held locks and secret redaction;
- positive session evidence, national-ID/terminal-OTP login and saved state;
- persistent session-cookie recovery across two browser context launches;
- exact single-card matching, duplicate cards, stock evidence;
- delayed inventory mutation, refresh-button loading not counted as inventory,
  human protection pause before refresh and expired session detection;
- select/input/+− quantity, site maximum rejection and wrong order summary;
- extra cart item rejection with explicit summary scoping, candidate verification
  separate from catalog, refusal of buy controls lacking verified quantity;
- refusal to repeat checkout after changed toast text or synonymous order buttons;
- same-tab/new-tab gateway detection, popup checkout, no payment input filling;
- workflow from existing-session profile through product, quantity and fake gateway;
- sanitized debug HTML, published purchase-cap stop and unknown inventory pages.

Compile/import/CLI verification: `compileall`, imports of every runtime module,
`main.py --help`, and `main.py --check-config`. The root has no `selectors.py`;
the standard-library module is correctly imported by asyncio.

Independent code review found and prompted regression checks for duplicate
submits, extra basket rows, unverified direct buy, catalog/cart scoping and
premature refresh completion. These were addressed before delivery.

## Boundaries

Authenticated live selectors, stock, SMS behavior, order creation, actual gateway
provider and live quantity rules beyond public terms remain unverified. See the
[selector provenance](architecture.md#selector-provenance). A passing fixture suite
does not imply a successful real purchase. No actual payment URL was obtained.
Site/server session expiration cannot be prevented by persistent browser state.

## Subsequent supervised live run

The user explicitly approved quantity 2 and use of their existing configured
national ID. The identity was moved into ignored `.env` and cleared from
`.env.example`; the private setting is now `TARGET_QUANTITY=2`.

The real login button's accessible name includes a private-use Font Awesome
glyph. Semantic button matching now accepts these decorative prefix/suffix
glyphs while retaining complete label matching. A reCAPTCHA badge (anchor
inside `.grecaptcha-badge`) is distinguished from an actual interactive
challenge. Visible challenge frames, queue, 403/429 and other protections still
pause. Regression tests cover both conditions; no security mechanism was bypassed.

Actual SMS UI: `input#code-verification[autocomplete=one-time-code]`, 8-character
case-sensitive password, submit button `ثبت`, resend `#btn-resend`. The user
entered the code in the site, never in the chat or a project file. Profile and
purchase navigation were reached. One browser restart did not recover login;
after a subsequent normal resend-button interaction the site again showed an
authenticated profile. The browser has since been kept open. Session recovery
on the live site is not guaranteed by the fixture tests.

The real target card is `.product` with `h2.title`, under `.products`. Matching
now uses rendered `inner_text`; `has_text` can join adjacent block labels and
sizes without separators, breaking exact model boundaries. A regression fixture
covers the actual div structure. The matching target's visible state is
`اتمام موجودی`; no product selected or order created.

The inventory UI's `#refresh-availability` button is used normally. Its own
disabled/aria-busy cooldown (~4 seconds) is respected, so each cycle includes
the configured 5-second interval plus the site's completion/cooldown time.
No availability endpoint is called outside the UI. The live monitoring process
was left running in its headed browser, with one order workflow and no gateway
URL yet. A loopback-only ephemeral CDP connection in an ignored troubleshooting
helper allowed inspection of that same browser; payment DOM is not inspected.

After the live-selector fixes: full suite **41/41 passed** in 56.372 seconds;
compileall, config validation and ignore checks passed again.

## User-requested stop

The user clarified that the objective was only to test the process and asked
to stop after a successful test. Monitoring was stopped with Ctrl+C; the process
exited and its browser was closed. No product was selected, no order created,
and no payment URL captured. Live login, product recognition and inventory
refresh were tested; live checkout/payment handoff were not tested. Do not
restart monitoring or attempt a purchase without a fresh user request.
The final storage-state export was unavailable during Ctrl+C; the earlier
successful login snapshot and persistent profile remain, with server validity
not guaranteed on a future run.

## Telegram implementation verification — 2026-10-29

This is new local evidence, separate from the Windows/live runs above. The user
authorized proceeding with the Telegram implementation plan. Work is on
`feature/telegram-app`; no live bot, SMS, monitoring, order or payment was started.

Environment: Linux; portable access to existing CPython 3.12.3 through its snap
loader, Playwright 1.64.1, local Google Chrome 156.0.8078.47. SDK/version constraints
are committed in `requirements-tested.txt`, including PTB 22.8, tzdata 2026.6 and
pyee 13.0.1. Pyee 13 was selected to retain the Python 3.11 compatibility range;
the initially installed pyee 14 requires Python 3.12. System Python was not changed.

The complete **91-test suite passed in 121.661 seconds**. A subsequent shutdown
admission review added one regression preventing queued `/arm` during shutdown;
the **20 affected orchestration/application/state tests passed in 2.099 seconds**
after that fix. The delivered checkout contains **92 permanent tests**; it is not
claimed that all 92 ran in one final invocation. The original 41 regressions remain,
with only credential, interaction-port and profile-backup interface adaptations.

The temporary environment adapter substituted installed Chrome for Playwright's
bundled Chromium and installed a default page-request abort route; test-local
fixture routes took priority. This is not a native Windows/bundled-Chromium test.
All regression tests are committed under `tests/` and can run normally after
installing the documented dependencies and Playwright Chromium; they do not depend
on the temporary adapter or `/tmp` files for their source or fixtures.

Verified cases include:

- exact Tehran boundaries, timezone conversion, late results, midnight, clock
  rollback, slow cycles across window changes and a once-per-run login reminder;
- idle boot, duplicate/concurrent arm, unauthorized user/chat/update rejection,
  update replay rejection, cancellation during input/cleanup, bounded order and
  handoff lifetimes, queued-command rejection during shutdown and SDK cleanup
  even when controller cleanup fails;
- input reply correlation, stale/manual checkpoint refusal, numeric glyphs,
  case-sensitive OTP, format rejection without echo, deletion failure, prompt-send
  failure and broker cleanup on timeout/cancellation;
- real-browser fixtures for a Telegram national-ID/OTP conversation through dry
  run with zero selection, and through a single allowed synthetic order/pop-up
  gateway with fixed private recipient, no payment-field filling and no URL file;
- repeat-submit prevention with decorated/alias buttons, exact selected-button
  preflight, mixed-selector ambiguity, extra/cart-summary item rejection, strict
  quantity parsing, stock completion beyond metadata-only changes and disabled
  refresh cooldown instead of reload;
- existing-account confirmation, profile-bound cookie recovery without origin
  storage export, OTP reference removal before manual pauses, rejection/resend
  checkpoint without replay, same-tab gateway with no bank DOM queries, and
  refusal of preexisting gateway tabs;
- durable nonsecret order barriers across restart, corrupt-marker refusal,
  explicit matching-run resolution, and CLI refusal to bypass a bot order barrier.

Runtime module imports, both `--help` entry points, both config validators with
synthetic bot settings, Python 3.11 grammar parsing, local Markdown links and Git
whitespace checks passed. No identity is present in settings serialization and
example files contain no populated sensitive keys. Existing private `.env` and
profiles were not overwritten. The user's preexisting example-quantity edit was
kept outside implementation commits.

Remaining release gates: actual Python 3.11 and Windows execution; native bundled
Chromium; actual bot transport/device setup; authenticated live selectors and
limits; browser-written identity/OTP/cache/autofill audit on the real device;
verified live cancellation/recovery and phone payment-link usability. No online
CVE/OSV audit is claimed. Profile persistence is not proof of RAM-only personal
data. Four tires remain disallowed whenever the actual site cap is lower.

The bot defaults to `DRY_RUN=true`, `LIVE_CHECKOUT_APPROVED=false`, no auth/profile
artifacts and no separate session export. The CLI now asks for identity at runtime
and uses the same durable order barrier. See `telegram-operations.md` and
`telegram-implementation-status.md` before the separately authorized live stages.

## Linux execution preparation — 2026-10-29

At the owner's request, created the previously absent private `.env` with mode
0600, the confirmed product/size, quantity 2 matching the existing local example,
dry run enabled and all three Telegram credential/ID fields empty. Verified Git
ignores `.env`, `.tools` and `.venv`; the existing example edit was preserved.

Installed standalone CPython 3.12.16 under the project's ignored `.tools` and
the constrained dependencies in `.venv`; system Python 3.8 was not changed.
`pip check` passed. Playwright's Chromium installer rejected Ubuntu 20.04 as
unsupported. Added validated optional `BROWSER_CHANNEL=chrome` and selected the
already installed Google Chrome 156.0.8078.47 in the private config instead.

The real `persistent_browser` path successfully opened and closed **headed**
Chrome with a temporary profile and local HTML; no merchant page or Telegram
connection was opened. This does not validate live login or profile storage.
The Linux launcher passed Bash syntax checks and `--check-config` from `/tmp`
using synthetic Telegram values supplied only to the subprocess; the private
credential fields stayed empty. Final core, scheduling and orchestration run:
**26 tests passed**. Compile checks and `git diff --check` passed. The full browser
suite was not rerun in this preparation step; previous suite evidence above is
separate. Real bot transport, authentication, dry-run observation and live-order
release gates remain pending.

## First real Telegram startup — 2026-10-29

The owner populated the three private Telegram values locally. Config validation
passed without displaying them. Direct HTTPS to Telegram failed with a network
unreachable error while public PyPI remained accessible. The existing Linux
desktop HTTP proxy successfully reached Telegram. Added optional validated
`TELEGRAM_PROXY_URL` for both PTB API and getUpdates clients, without changing
system settings or the merchant browser's proxy configuration. Proxy values are
excluded from settings repr; malformed URLs are rejected without echo.

**8 scheduling/config and application tests passed**, including construction of
both Telegram HTTP clients with the explicit proxy. The real app then completed
Telegram initialization and polling startup and logged readiness in idle mode.
`DRY_RUN=true` and `LIVE_CHECKOUT_APPROVED=false` remain set. No proactive message,
merchant login, SMS, stock observation or order was initiated by the agent.
Owner command-response testing and all live merchant release gates remain pending.

## Copyable Telegram output — 2026-10-29

The owner confirmed real bot responses, then reported that message content could
not be copied. General notifications previously set `protect_content=True`
unconditionally. General command responses and events now use unprotected
messages, including `/start`, `/status` and manual checkpoint instructions.
National-ID/OTP prompts and payment-link messages explicitly retain protection.
Existing Telegram messages are not edited; the owner should request fresh output.

**13 Telegram handler and application tests passed**, including copyable start,
status and event messages, protected login prompts, and the protected fixed-chat
payment button. Config validation, compile checks and Git whitespace checks
passed. No merchant login, SMS or order was initiated for this change.

## Workspace and documentation consolidation — 2026-10-29

Reviewed the single local worktree on `feature/telegram-app`, accumulated source
changes, entry points, dependency constraints, tests and documentation. The owner
confirmed the real `/start` and `/status` responses and accepted the current
checkpoint. That confirms command transport and copyable output, not store login
or inventory/checkout behavior.

Aligned code and both configuration examples with the owner's confirmed target
quantity **2**. Explicit four-tire fixtures remain unchanged as regression data.
Extracted shared browser fixtures into `tests/browser_support.py`, removed the
safety suite's dependency on importing a test module, blocked unmatched fixture
page requests and added `TEST_BROWSER_CHANNEL=chrome` selection. The suite now
runs from the checkout without an external monkeypatch runner.

Rewrote the project README in English with Linux/Telegram setup and the separate
CLI behavior. Added a documentation index and current architecture/selector map,
updated operations/status and marked original plans as historical. Selector
evidence from 2026-10-27 was preserved rather than presented as a new inspection.

Final complete suite:

```bash
TEST_BROWSER_CHANNEL=chrome .venv/bin/python -m unittest discover -v
```

**95 tests passed in 124.983 seconds** on CPython 3.12.16, Playwright 1.64.1 and
installed Google Chrome 156.0.8078.47. This run used only permanent tests and
helpers in the checkout, temporary browser profiles and synthetic input. No live
Telegram message, SMS, merchant observation or order was initiated by these tests.

Additional checks passed: Python 3.11 grammar parsing for 42 Python files,
28 runtime-module imports, compileall, dependency consistency, both config
validators, Bash syntax, local Markdown paths, LF line endings and Git whitespace.
The English README and quantity-two examples/defaults were checked explicitly.
Private `.env` contents and the order marker were unchanged compared with the
start of this cleanup. The configured token/owner IDs and private runtime paths
were absent from the source prepared for commit. Ignored installation/profile
data was preserved.

Remaining gates are unchanged: real Telegram-driven store login/OTP, scheduled
observation/cancellation, current store terms, authenticated checkout selectors,
browser storage privacy and usable payment handoff. Windows, native Python 3.11,
bundled Chromium on this host and an online CVE audit were not validated here.

## Explicit one-time inventory test — 2026-10-29

The owner requested a supervised login-to-inventory check outside the sale hours,
with national ID and OTP supplied only through the private bot conversation.
Added `/test_inventory` and the explicit `--test-inventory` startup flag. They
require dry-run configuration, share owner authorization and the single-worker
and unresolved-attempt checks, and complete after one fresh inventory result.
Available, out-of-stock and target-absent results all return before selection or
checkout. The real clock, `.env` and daily sale schedule are not changed.

The test uses a ten-minute monotonic lifetime, normal per-input TTLs and bounded
cancellation/cleanup. Status identifies the one-time mode. Default startup
remains idle; the explicit CLI flag starts the test only after polling is ready.

**103 permanent tests passed in 127.575 seconds** using the documented installed
Chrome command. New coverage includes all stock outcomes outside hours, no
checkout/marker/payment, a normal scheduled run after a test, owner/live-mode
refusal, concurrent admission, cancellation, elapsed timeout, command replay and
explicit boot sequencing. A real-browser fixture at simulated 21:03 completed
correlated national-ID/OTP login, exactly one inventory refresh and an unavailable
result with zero selection/submission. Compile/import, grammar, config, Bash and
Git whitespace checks also passed. These are synthetic checks; live evidence is
recorded separately below when observed.

The previous idle bot was stopped gracefully and the real bot restarted with the
explicit inventory-test flag. It connected to Telegram and began waiting for the
owner's runtime input. No browser profile had been initialized and no order marker
existed at that checkpoint; real store login and inventory were not yet observed.
No accepted national-ID reply arrived within the configured 180-second input TTL.
The worker then ended at `WAITING_FOR_NATIONAL_ID` with a sanitized timeout and
cleaned up the request. No browser, SMS, inventory request or order was started.
The bot remained available for an owner-initiated `/test_inventory` retry.

## Independent store and Telegram network paths — 2026-10-29

A subsequent owner-initiated inventory test reached `CHECKING_SESSION`, paused
on detected site protection/access restrictions and expired waiting for manual
input. No order was attempted. The owner reported that the store did not open
with the desktop VPN/proxy enabled and asked to supply inputs from mobile Telegram.

Added validated `BROWSER_DIRECT_CONNECTION=true` for the retailer browser. It
launches Chrome/Chromium with `--no-proxy-server`; false preserves normal system
proxy behavior. Both Telegram HTTP clients keep their explicit configured proxy.
No OS proxy/VPN setting or process-global proxy variable was changed, and private
`.env` was not edited. A full VPN/TUN route is outside this browser-level control.

Public network checks on this device succeeded: direct public store HTTPS 200;
then headed Chrome using the real `persistent_browser` path returned 200 and
showed the ordinary terms checkbox, while Telegram `getMe` authenticated through
the existing local proxy in the same run. The browser used a temporary profile;
no login, SMS, inventory or order action was made by this probe.

**18 focused core/settings/application tests and 3 browser regressions passed**,
including both direct/system browser modes, unchanged proxy environment, session
persistence and the after-hours login-to-inventory fixture. There are now 104
permanent tests; the prior full 103-test result is separate and the full suite was
not rerun for this routing change. Config and whitespace checks passed. Mobile
message entry uses the same authorized account/chat; Telegram Desktop need not
run, but the Linux bot's local Telegram proxy service must stay reachable.

## Successful live inventory check and headless preference — 2026-10-29

The supervised Telegram test subsequently succeeded with the direct store
browser: sanitized logs recorded identity submission at 22:23:37 Tehran, successful
login and shop navigation at 22:24:19, inventory refresh and then
`inventory_test_out_of_stock` at 22:24:29. The owner confirmed that the unavailable
result ended the test and closed the browser. No order marker was created.
These observations validate one headed login/inventory test, not a complete
scheduled morning session or checkout.

At the owner's request, changed only `HEADLESS` to `true` in private `.env`;
all other parsed settings and owner-only file permissions were preserved. The
code's generic default remains headed for manual-browser compatibility. Headless
manual prompts now explain when a visible retry is needed; account confirmation
and protection checks have not been removed or automated.

Added a fake-clock regression that starts the daily run before 08:00, keeps
returning out-of-stock or target-absent, verifies repeated refreshes across all
three cadence windows and stops only at the 08:15 cutoff. Neither outcome calls
checkout or creates an attempt marker. **39 focused orchestration, handler and
core tests passed**; config and Git whitespace checks passed. There are now 106
permanent tests; this is separate from the earlier complete 103-test run. No new
live login/SMS was triggered for the headless configuration change. Real headless
store login and the complete morning session remain unverified.
