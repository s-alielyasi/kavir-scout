# Verification record — 2026-10-27

Environment: Windows, local portable CPython 3.12.10; Playwright 1.64.1 and its
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
README section `Selectors that may need adjustment`. A passing fixture suite
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
