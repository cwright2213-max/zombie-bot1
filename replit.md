# Python Discord Bot

Starter Discord bot with slash commands, built with Python and discord.py.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Discord bot

- `python -m bot.main` — start the Discord bot
- Required secret: `DISCORD_BOT_TOKEN`
- `bot/main.py` — source of truth for commands and Discord client setup

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)
- Bot: Python 3.13 + discord.py

## Where things live

- `bot/main.py` — Discord client and slash commands
- `bot/README.md` — setup and invite instructions
- `pyproject.toml` / `uv.lock` — Python dependency metadata

## Architecture decisions

- The bot uses Discord slash commands, so message-content intent is not required for the starter commands.
- The bot token is read only from `DISCORD_BOT_TOKEN` and is never stored in source files.

## Product

The bot responds to `/ping`, `/about`, and `/serverinfo` in servers where it has
been invited.

## User preferences

No additional preferences recorded.

## Gotchas

- Invite the bot with the `applications.commands` scope so slash commands can sync.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
