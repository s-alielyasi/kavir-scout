# Kavir Scout implementation plan

Historical plan for the initial CLI implementation on 2026-10-27. For the current
Telegram application, confirmed two-tire default and English README, use the
[documentation index](README.md) and [architecture](architecture.md). Completed
items below describe that original delivery, not current live release approval.

Spec: the user's 30-section request, 2026-10-27.

Architecture: async Playwright, one persistent Chromium context, explicit workflow
states, no HTTP purchase/login client. Python 3.11+. Configuration is immutable.
Selectors live in `kavirtire/selectors.py`: a root `selectors.py` would shadow
Python's standard-library module used by asyncio and break startup.

Safety: one process lock per project and per browser profile; never retry a
mutating order click; never return to monitoring after entering checkout;
verify the same product/size/quantity in a single order row before every
checkout transition. Unknown pages require manual intervention. Payment pages
are detected by HTTPS host allowlist (Shaparak by default), never interacted
with. No CAPTCHA, queue, purchase-limit or rate-limit bypass.

- [x] Configuration, normalization, process locking and redaction. First write
  unit tests for defaults, invalid environment, Persian text, gateway hostname
  boundaries, lock contention and secret removal, then implement and run.
- [x] Persistent browser, diagnostics, protection detection, semantic helpers
  and login. Test real Chromium against local HTML fixtures; public live site
  inspection only, without credentials or order creation.
- [x] Product monitoring and checkout. Test unique row matching, wrong size,
  stock controls, delayed refresh, quantity limits, final order verification,
  same-tab/new-tab gateway capture and refusal of unknown external hosts.
- [x] Workflow entry point, Persian README and selector provenance. Compile,
  import, run all tests, exercise help/check-config and inspect the public site.

Unverified live selectors must be explicitly listed. A successful fixture run
does not establish compatibility with authenticated live pages. Runtime files
and portable verification tools stay ignored. The new empty repository is
the requested output location; no extra worktree or automatic commit needed.
