"""Entry point for the Discord bot."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands

from bot.zombie_survival import (
    AMMO,
    WEAPONS,
    GameStore,
    buy_item,
    change_zone,
    equip_ammo,
    start_run,
    status,
    take_action,
    upgrade,
)
from bot.zombie_ui import CombatView, ZombieMenuView, combat_embed


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
game_store = GameStore()


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


zombie = app_commands.Group(name="zombie", description="Play turn-based zombie survival.")


@zombie.command(name="start", description="Start a zombie survival run.")
async def zombie_start(interaction: discord.Interaction) -> None:
    player = game_store.get(interaction.user.id)
    messages = start_run(player)
    game_store.save()
    await interaction.response.send_message(
        embed=combat_embed(messages, player),
        view=CombatView(interaction.user.id, game_store),
        ephemeral=True,
    )


@zombie.command(name="status", description="Show your survivor status.")
async def zombie_status(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        status(game_store.get(interaction.user.id)),
        view=ZombieMenuView(interaction.user.id, game_store),
        ephemeral=True,
    )


@zombie.command(name="menu", description="Open selectable zombie survival menus.")
async def zombie_menu(interaction: discord.Interaction) -> None:
    """Open the interactive select-menu game interface."""
    await interaction.response.send_message(
        status(game_store.get(interaction.user.id)),
        view=ZombieMenuView(interaction.user.id, game_store),
        ephemeral=True,
    )


@zombie.command(name="action", description="Take a turn in your current fight.")
@app_commands.describe(action="Your combat action", heal_item="Required when action is heal")
@app_commands.choices(
    action=[
        app_commands.Choice(name="Attack", value="attack"),
        app_commands.Choice(name="Reload", value="reload"),
        app_commands.Choice(name="Heal", value="heal"),
        app_commands.Choice(name="Flee", value="flee"),
    ],
    heal_item=[
        app_commands.Choice(name="Full restore", value="full_restore"),
        app_commands.Choice(name="Painkillers", value="painkillers"),
    ],
)
async def zombie_action(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    heal_item: app_commands.Choice[str] | None = None,
) -> None:
    player = game_store.get(interaction.user.id)
    messages = take_action(player, action.value, heal_item.value if heal_item else None)
    game_store.save()
    await interaction.response.send_message(
        embed=combat_embed(messages, player),
        view=CombatView(interaction.user.id, game_store) if player.run_active else ZombieMenuView(interaction.user.id, game_store),
        ephemeral=True,
    )


def action_help_for_response(player: Any) -> str:
    if player.run_active:
        return f"\n{status(player).splitlines()[-1]}"
    return ""


@zombie.command(name="shop", description="Buy supplies or equip a weapon.")
@app_commands.describe(item="The shop item to buy or equip")
@app_commands.choices(
    item=[
        app_commands.Choice(name="Ammo box", value="ammo"),
        app_commands.Choice(name="Painkillers", value="painkillers"),
        app_commands.Choice(name="Full restore", value="full_restore"),
        *[
            app_commands.Choice(name=weapon_name, value=weapon_name)
            for weapon_name in WEAPONS
            if weapon_name != "Pistol"
        ],
    ]
)
async def zombie_shop(interaction: discord.Interaction, item: app_commands.Choice[str]) -> None:
    player = game_store.get(interaction.user.id)
    messages = buy_item(player, item.value)
    game_store.save()
    await interaction.response.send_message("\n".join(messages))


@zombie.command(name="zone", description="Travel to an unlocked zone.")
@app_commands.describe(zone_name="The zone to travel to")
@app_commands.choices(
    zone_name=[
        app_commands.Choice(name=zone_name, value=zone_name)
        for zone_name in (
            "Graveyard",
            "Mega Death City",
            "Frostbitten Outskirts",
            "Toxic Wasteland",
            "The Void",
        )
    ]
)
async def zombie_zone(interaction: discord.Interaction, zone_name: app_commands.Choice[str]) -> None:
    player = game_store.get(interaction.user.id)
    messages = change_zone(player, zone_name.value)
    game_store.save()
    await interaction.response.send_message("\n".join(messages))


@zombie.command(name="ammo", description="Buy and equip an ammo type.")
@app_commands.describe(ammo_name="The ammo type to equip")
@app_commands.choices(
    ammo_name=[
        app_commands.Choice(name=ammo_name, value=ammo_name)
        for ammo_name in AMMO
    ]
)
async def zombie_ammo(interaction: discord.Interaction, ammo_name: app_commands.Choice[str]) -> None:
    player = game_store.get(interaction.user.id)
    messages = equip_ammo(player, ammo_name.value)
    game_store.save()
    await interaction.response.send_message("\n".join(messages))


@zombie.command(name="upgrade", description="Spend XP on survivor upgrades.")
@app_commands.describe(stat="The stat to upgrade")
@app_commands.choices(
    stat=[
        app_commands.Choice(name="Max health", value="health"),
        app_commands.Choice(name="Weapon damage", value="damage"),
        app_commands.Choice(name="Magazine size", value="magazine"),
    ]
)
async def zombie_upgrade(interaction: discord.Interaction, stat: app_commands.Choice[str]) -> None:
    player = game_store.get(interaction.user.id)
    messages = upgrade(player, stat.value)
    game_store.save()
    await interaction.response.send_message("\n".join(messages))


bot.tree.add_command(zombie)


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