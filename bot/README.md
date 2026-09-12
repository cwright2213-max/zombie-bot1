# Python Discord Bot

This project is a starter Discord bot built with `discord.py`. It connects
using the `DISCORD_BOT_TOKEN` project secret and exposes three slash commands:

- `/ping` — check the gateway latency
- `/about` — view bot information and uptime
- `/serverinfo` — view basic details about the current server

## Run it

Use the **Discord Bot** workflow, or run:

```bash
python -m bot.main
```

The bot exits with a clear error if `DISCORD_BOT_TOKEN` is missing.

## Discord setup

1. Create an application and bot in the Discord Developer Portal.
2. Copy the bot token into the Replit Secrets panel as `DISCORD_BOT_TOKEN`.
3. Invite the bot to a server with the `bot` and `applications.commands` scopes.
4. Start the **Discord Bot** workflow.

The starter commands only need Discord's default intent set. If you later add
message-based commands or member presence features, enable the matching
privileged intents in the Developer Portal and in `bot/main.py`.