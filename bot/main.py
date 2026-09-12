"""Entry point for the Discord bot."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

import discord
from discord import app_commands


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("discord_bot")


class StarterBot(discord.Client):
    """Small Discord bot with slash commands."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.started_at = datetime.now(timezone.utc)

    async def setup_hook(self) -> None:
        """Register application commands with Discord."""
        synced_commands = await self.tree.sync()
        logger.info("Synced %d application command(s)", len(synced_commands))

    async def on_ready(self) -> None:
        """Log a useful startup message once the bot is connected."""
        if self.user is not None:
            logger.info("Logged in as %s (id=%s)", self.user, self.user.id)
            logger.info("Connected to %d server(s)", len(self.guilds))


bot = StarterBot()


@bot.tree.command(name="ping", description="Check whether the bot is responding.")
async def ping(interaction: discord.Interaction) -> None:
    """Return the bot's current gateway latency."""
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong — {latency_ms} ms")


@bot.tree.command(name="about", description="Show information about this bot.")
async def about(interaction: discord.Interaction) -> None:
    """Describe the bot and how long it has been running."""
    uptime = datetime.now(timezone.utc) - bot.started_at
    total_seconds = int(uptime.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    await interaction.response.send_message(
        "I’m a Python Discord bot built with discord.py. "
        f"Uptime: {hours}h {minutes}m {seconds}s."
    )


@bot.tree.command(name="serverinfo", description="Show details about this server.")
async def serverinfo(interaction: discord.Interaction) -> None:
    """Show basic information about the current server."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a server.",
            ephemeral=True,
        )
        return

    guild = interaction.guild
    owner = guild.owner.mention if guild.owner else "Unknown"
    await interaction.response.send_message(
        f"**{guild.name}**\n"
        f"Members: {guild.member_count:,}\n"
        f"Owner: {owner}\n"
        f"Created: <t:{int(guild.created_at.timestamp())}:D>"
    )


def main() -> None:
    """Start the bot using the project secret."""
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logger.error(
            "DISCORD_BOT_TOKEN is not set. Add it in the project's Secrets "
            "panel before starting the bot."
        )
        sys.exit(1)

    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()