# Documentation index

Use the [English project README](../README.md) for setup and daily usage. This
directory separates current guidance from the original plans and dated evidence.

## Current guides

| Document | Purpose |
|---|---|
| [Architecture](architecture.md) | Package responsibilities, runtime data, ownership boundaries and live selector provenance |
| [Telegram operations](telegram-operations.md) | Persian setup, early login, schedule, commands, manual steps and order recovery |
| [Implementation status](telegram-implementation-status.md) | Current implementation, owner-confirmed checks and remaining supervised validation |

The confirmed configuration is **Perfect (R14) KB27**, **185/65R14**, **2 tires**.
The bot defaults to observation mode. Both code defaults and example files follow
this quantity; `.env` remains private and explicit settings take precedence.

## Evidence and original plans

| Document | How to read it |
|---|---|
| [Verification record](verification.md) | Dated, chronological test/live evidence; earlier environment descriptions and counts belong to their own runs |
| [Original CLI plan](implementation-plan.md) | Historical scope of the initial CLI implementation |
| [Telegram integration plan](telegram-integration-plan.md) | Original baseline analysis and design; its planning-only restrictions and four-tire target describe the original task, not today's setup |

Current behavior is described by the source, README, architecture and operations
guide. Preserve original observations in the verification record; append later
evidence instead of silently turning historical results into current claims.
Fixture success, real Telegram responses and authenticated store checkout are
distinct validation stages.

When a behavior, path or entry point changes, update the relevant current guide
and implementation status. Record material verification results and limitations
in the dated verification record. Never include tokens, actual owner IDs,
national IDs, OTPs, cookies or gateway URLs in documentation.
