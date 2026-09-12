# Python Discord Bot

This project is a Discord bot built with `discord.py`. It connects using the
`DISCORD_BOT_TOKEN` project secret and exposes starter commands plus a
turn-based zombie survival game.

- `/ping` — check the gateway latency
- `/about` — view bot information and uptime
- `/serverinfo` — view basic details about the current server
- `/zombie start` — start a run
- `/zombie status` — view your survivor
- `/zombie action` — attack, reload, heal, or flee
- `/zombie shop` — buy supplies and weapons
- `/zombie zone` — travel between unlocked zones
- `/zombie ammo` — buy and equip elemental ammo
- `/zombie upgrade` — spend stars on upgrades
- `/zombie menu` — open private selectable menus and buttons for the game

Each Discord user has an independent save in `zombie_saves.json`. The game
converts the attached terminal game into one-action-per-command turns, so a
fight can be played directly from Discord without blocking the bot.

XP uses a gradually increasing level curve. Every level gained awards one star,
and each of the three upgrades costs one star.

`/zombie menu` opens a public button-based interface so other players can see
levels and progress. Only the player who opened a menu can use its buttons.
The buttons cover
combat, healing, shopping, zones, ammo, and upgrades, with the same quick
action layout used by the combat screen. Slash commands remain available for
players who prefer typing commands.

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

The bot only needs Discord's default intent set. If you later add
message-based commands or member presence features, enable the matching
privileged intents in the Developer Portal and in `bot/main.py`.