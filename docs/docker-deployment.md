# Docker deployment

The repository includes `Dockerfile`, `compose.yaml`, `.dockerignore` and
`.env.docker.example`. The container runs `python -m telegram_bot` directly;
it does not depend on the workstation's `.venv`, Chrome installation or Bash
launcher. The base image and constrained Python package both use Playwright
1.64.1. Update those versions together.

## First deployment

Install Docker Engine and the Docker Compose plugin on the Linux server. Clone
this repository and run from its root:

```bash
cp -n .env.docker.example .env.docker
chmod 600 .env.docker
```

Edit `.env.docker` privately. Set `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_ALLOWED_USER_ID` and `TELEGRAM_ALLOWED_CHAT_ID`. Keep `DRY_RUN=true`
and `LIVE_CHECKOUT_APPROVED=false` for the initial deployment. The Compose
service explicitly loads `.env.docker`; the workstation's `.env` is not loaded
into the container. Do not commit or bake private settings into the image.

Stop another running instance of this bot, including any instance on a different
machine, before starting the container. Use one replica with this bot token and
profile.

```bash
docker compose up -d --build
docker compose logs -f --tail=100
```

The service uses Telegram long polling. It needs outbound HTTPS access to
Telegram and the retailer; there is no inbound port to publish and no need for
an application domain, webhook, reverse proxy or separate database. The first
build downloads the browser image and Python dependencies.

Send `/start` from the allowed private chat and reply to the second message with
national ID; `/set_national_id` edits it. Once registered, daily login starts
automatically at 07:50 Tehran. `DAILY_LOGIN_TIME` defaults to `07:50:00`.
A restart between 07:50 and 08:15 catches up if today's persistent slot is unused.
A consumed slot is never retried automatically; `/arm` remains a deliberate
manual retry. `/cancel` suppresses today's automatic slot as well as cancelling
an active worker. `/test_inventory` remains an explicit observation-only check.
Scheduling explicitly uses `Asia/Tehran` and Tehran dates, independently of the
European host timezone/DST. Keep the server clock synchronized.

## Runtime settings and persistent state

Compose fixes `HEADLESS=true`, `BROWSER_CHANNEL` to empty and `USER_DATA_DIR` to
`/app/data/telegram_profile`. This uses the Chromium supplied by the image,
independently of any Chrome installation on the host. Other settings come from
`.env.docker`; apply changes by recreating the service:

```bash
docker compose up -d --force-recreate
```

The image runs as the existing unprivileged `pwuser`. New named volumes are
initialized from the image's writable data/log directories. If restoring data
from another installation, give this user access to the restored files.

| Compose volume | Container path | Purpose |
|---|---|---|
| `kavir-data` | `/app/data` | Browser profile, process/profile locks, private `owner_profile.json`, `daily_start.json` and `order_attempt.json` |
| `kavir-logs` | `/app/logs` | Application log and rotating `diagnostics/workflow.jsonl` reports |

Compose prefixes actual volume names with the project name. Reuse the same
project name and volumes when updating. Preserve the **whole data volume**,
including the identity, daily admission journal and unresolved-order barrier,
rather than only the browser profile. Registered identity is plaintext accessible
to the service user, stored atomically with POSIX mode 0600.
Treat profile backups as private. Stop the service before backing up or restoring
browser state. A persistent profile does not guarantee that the retailer keeps a
session valid or that a profile copied from another OS/device can be reused.

```bash
docker compose stop
docker compose start
```

Ordinary `docker compose down` retains named volumes. Do not use `down -v` to
update or recover the application: it deletes the session and the order barrier.
Docker's console logs are rotated by Compose. The separate application file
`/app/logs/kavirtire.log` still needs normal host/operator retention management.

## Proxy connectivity

Leave `TELEGRAM_PROXY_URL` empty when Telegram is reachable directly. Otherwise
set an HTTP(S) proxy address reachable from the container. `127.0.0.1` and
`localhost` refer to the container, not a proxy running on the host or your laptop.
Use a reachable proxy service address; a proxy on the host must also listen on an
interface reachable by the container and allow that connection.

The retailer browser remains direct with `BROWSER_DIRECT_CONNECTION=true`.
The Telegram proxy does not configure Chromium or change OS VPN/TUN routing.
Reachability of the retailer from the actual server IP must be established on
that server.

## Updates and order recovery

The service receives SIGTERM on stop. `init: true` reaps child processes, the
60-second stop grace period allows application/browser cleanup, and
`restart: unless-stopped` brings the bot back after an unexpected exit or host
restart. Registered identity and daily admission state determine the next login.

Pull an update and rebuild while retaining the same volumes:

```bash
git pull --ff-only
docker compose up -d --build
```

If the installation was transferred as a source archive instead of a Git clone,
upload and extract the updated public source files in the same directory instead
of running `git pull`. Preserve `.env.docker` and the existing Compose project and
volumes. The verified VPS installation uses this archive deployment method in
`/opt/kavir-scout`.

For local reconciliation, first stop the running service so the recovery command
can acquire its locks. Both commands below use the same data volume as the bot:

```bash
docker compose stop
docker compose run --rm --no-deps kavir-scout --show-attempt
```

Inspect the corresponding retailer orders. Only after confirming the outcome,
use the exact recorded run ID and the matching disposition:

```bash
docker compose run --rm --no-deps kavir-scout --resolve-attempt no_order --attempt-run-id EXACT_RUN_ID
# Use order_exists instead of no_order when reconciling an existing order.
docker compose up -d
```

Do not delete `order_attempt.json` to clear an uncertain order. Recovery does not
cancel an order already recorded by the retailer.

## Manual browser steps and live checkout

Headless deployment supports the implemented Telegram credential prompts and
inventory workflow. CAPTCHA, changed forms, order reconciliation and confirmation
of an existing logged-in account can still require seeing and interacting with
the browser. The bot pauses at those checkpoints; `/resume` alone does not
perform the missing action.

This Compose setup does not include a remote desktop or noVNC. For a checkpoint
requiring visual interaction, stop/cancel the run and arrange a graphical
execution environment with access to the appropriate profile. Setting
`HEADLESS=false` alone is insufficient on a server without a display.

Docker packaging does not enable live checkout or validate payment-link use on
another device. Preserve the release gates in the
[implementation status](telegram-implementation-status.md) and follow the
[operations guide](telegram-operations.md). Image build, configuration loading,
offline headless Chromium rendering, volume persistence, real Telegram
authentication/polling and graceful stop/start were verified on the European
Ubuntu 26.04 VPS on 2026-11-02. The service was left running in observation-only
idle mode. These startup checks did not log into the retailer or validate live
checkout. See the dated [verification record](verification.md).

## Extract diagnostics from the deployed server

The stable container path is `/app/logs/diagnostics/workflow.jsonl` (plus `.1`
through `.5`) in the existing logs volume. The host installation root is
`/opt/kavir-scout`; the physical Docker volume path depends on the Compose
project name. Use `docker compose cp` as documented in the
[diagnostic extraction guide](diagnostic-reports.md), which also describes report
contents, rotation, timezone checks and files to exclude from an AI review.
This version must be rebuilt/recreated on the VPS before these new paths and
automatic registration/login behavior are available there.
