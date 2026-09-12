"""Discord select menus and buttons for the zombie survival game."""

from __future__ import annotations

import discord

from bot.zombie_survival import (
    AMMO,
    WEAPONS,
    ZONES,
    GameStore,
    buy_item,
    change_zone,
    equip_ammo,
    start_run,
    status,
    take_action,
    upgrade,
)


def result_text(messages: list[str], player: object) -> str:
    """Keep the latest action and current state together in one message."""
    parts = [message for message in messages if message]
    current_status = status(player)  # type: ignore[arg-type]
    return "\n".join(parts + [current_status])


def _health_bar(current: int, maximum: int, width: int = 12) -> str:
    filled = round(max(0, min(current, maximum)) / maximum * width) if maximum else 0
    return f"`{'█' * filled}{'░' * (width - filled)}`"


def combat_embed(messages: list[str], player: object) -> discord.Embed:
    """Render the latest turn and both sides of the current fight."""
    embed = discord.Embed(
        title="Zombie Survival",
        color=discord.Color.dark_red(),
    )
    embed.description = "\n".join(message for message in messages if message) or "Choose your next action."

    if getattr(player, "run_active", False) and getattr(player, "enemy", None):
        enemy = player.enemy
        embed.add_field(
            name=f"You — {player.health}/{player.max_health} HP",
            value=f"{_health_bar(player.health, player.max_health)}\n"
            f"Ammo: {player.magazine}/{player.magazine_size} + {player.spare_ammo} spare",
            inline=True,
        )
        embed.add_field(
            name=f"{enemy.name} — {enemy.health}/{enemy.max_health} HP",
            value=f"{_health_bar(enemy.health, enemy.max_health)}\n"
            f"Wave {player.wave} • {player.zombies_remaining} left",
            inline=True,
        )
        embed.add_field(
            name="Loadout",
            value=f"{player.weapon_name} • {player.ammo_name} ammo",
            inline=False,
        )
        embed.set_footer(text="Choose an action below. This panel updates after every turn.")
    else:
        embed.add_field(
            name="Run ended",
            value=f"Health: {player.health}/{player.max_health} HP\n"
            f"Money: ${player.money} • XP: {player.xp}",
            inline=False,
        )
        embed.set_footer(text="Use Start run to begin another survival run.")
    return embed


class PlayerView(discord.ui.View):
    """Base view that prevents one player from controlling another player's menu."""

    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(timeout=900)
        self.user_id = user_id
        self.store = store

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This menu belongs to another survivor. Use `/zombie menu` for your own menu.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


class ZombieMenuView(PlayerView):
    """Top-level game menu displayed as quick-access buttons."""

    async def _open(
        self,
        interaction: discord.Interaction,
        view: PlayerView,
    ) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(player), view=view)

    @discord.ui.button(label="Combat", style=discord.ButtonStyle.danger, row=0)
    async def combat(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._open(interaction, CombatView(self.user_id, self.store))

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.primary, row=0)
    async def shop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._open(interaction, ShopView(self.user_id, self.store))

    @discord.ui.button(label="Zones", style=discord.ButtonStyle.primary, row=0)
    async def zones(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._open(interaction, ZoneView(self.user_id, self.store))

    @discord.ui.button(label="Ammo lab", style=discord.ButtonStyle.primary, row=0)
    async def ammo(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._open(interaction, AmmoView(self.user_id, self.store))

    @discord.ui.button(label="Upgrades", style=discord.ButtonStyle.success, row=0)
    async def upgrades(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._open(interaction, UpgradeView(self.user_id, self.store))

    @discord.ui.button(label="Refresh status", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_status(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=status(self.store.get(self.user_id)),
            view=ZombieMenuView(self.user_id, self.store),
        )


class CombatView(PlayerView):
    """Combat actions presented as one-click choice buttons."""

    async def _take_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = take_action(player, action)
        self.store.save()
        next_view: PlayerView = self if player.run_active else ZombieMenuView(self.user_id, self.store)
        await interaction.response.edit_message(
            content=None,
            embed=combat_embed(messages, player),
            view=next_view,
        )

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, row=0)
    async def attack(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._take_action(interaction, "attack")

    @discord.ui.button(label="Heal", style=discord.ButtonStyle.success, row=0)
    async def heal(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Choose a healing item.",
            embed=None,
            view=HealView(self.user_id, self.store),
        )

    @discord.ui.button(label="Reload", style=discord.ButtonStyle.primary, row=0)
    async def reload(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._take_action(interaction, "reload")

    @discord.ui.button(label="Flee", style=discord.ButtonStyle.secondary, row=0)
    async def flee(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._take_action(interaction, "flee")

    @discord.ui.button(label="Start run", style=discord.ButtonStyle.success, row=1)
    async def start(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = start_run(player)
        self.store.save()
        await interaction.response.edit_message(
            content=None,
            embed=combat_embed(messages, player),
            view=CombatView(self.user_id, self.store),
        )

    @discord.ui.button(label="Status", style=discord.ButtonStyle.secondary, row=1)
    async def show_status(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=status(self.store.get(self.user_id)),
            view=CombatView(self.user_id, self.store),
        )

    @discord.ui.button(label="Main menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=status(self.store.get(self.user_id)),
            view=ZombieMenuView(self.user_id, self.store),
        )


class HealView(PlayerView):
    """Secondary button choices for healing."""

    async def _use_heal(
        self,
        interaction: discord.Interaction,
        item: str,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = take_action(player, "heal", item)
        self.store.save()
        next_view: PlayerView = CombatView(self.user_id, self.store) if player.run_active else ZombieMenuView(
            self.user_id,
            self.store,
        )
        await interaction.response.edit_message(
            content=None,
            embed=combat_embed(messages, player),
            view=next_view,
        )

    @discord.ui.button(label="Full restore", style=discord.ButtonStyle.success, row=0)
    async def full_restore(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._use_heal(interaction, "full_restore")

    @discord.ui.button(label="Painkillers", style=discord.ButtonStyle.success, row=0)
    async def painkillers(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._use_heal(interaction, "painkillers")

    @discord.ui.button(label="Back to combat", style=discord.ButtonStyle.secondary, row=1)
    async def back(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=None,
            embed=combat_embed([], self.store.get(self.user_id)),
            view=CombatView(self.user_id, self.store),
        )


class ShopView(PlayerView):
    """Shop choices displayed as buttons."""

    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        choices = [
            ("Ammo box · $30", "ammo", discord.ButtonStyle.primary),
            ("Painkillers · $40", "painkillers", discord.ButtonStyle.primary),
            ("Full restore · $120", "full_restore", discord.ButtonStyle.primary),
        ]
        choices.extend(
            (
                f"{weapon_name} · ${weapon_data['price']}",
                weapon_name,
                discord.ButtonStyle.secondary,
            )
            for weapon_name, weapon_data in WEAPONS.items()
            if weapon_name != "Pistol"
        )
        for index, (label, value, style) in enumerate(choices):
            button = discord.ui.Button(label=label, style=style, row=index // 4)

            async def callback(
                interaction: discord.Interaction,
                selected: str = value,
            ) -> None:
                await self._buy(interaction, selected)

            button.callback = callback
            self.add_item(button)

    async def _buy(
        self,
        interaction: discord.Interaction,
        item: str,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = buy_item(player, item)
        self.store.save()
        await interaction.response.edit_message(
            content=result_text(messages, player),
            view=ShopView(self.user_id, self.store),
        )

    @discord.ui.button(label="Main menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=status(self.store.get(self.user_id)),
            view=ZombieMenuView(self.user_id, self.store),
        )


class ZoneView(PlayerView):
    """Zone travel choices displayed as buttons."""

    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        for index, zone_name in enumerate(ZONES):
            button = discord.ui.Button(label=zone_name, style=discord.ButtonStyle.primary, row=index // 5)

            async def callback(
                interaction: discord.Interaction,
                selected: str = zone_name,
            ) -> None:
                await self._travel(interaction, selected)

            button.callback = callback
            self.add_item(button)

    async def _travel(
        self,
        interaction: discord.Interaction,
        zone_name: str,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = change_zone(player, zone_name)
        self.store.save()
        await interaction.response.edit_message(
            content=result_text(messages, player),
            view=ZoneView(self.user_id, self.store),
        )

    @discord.ui.button(label="Main menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=status(self.store.get(self.user_id)),
            view=ZombieMenuView(self.user_id, self.store),
        )


class AmmoView(PlayerView):
    """Ammo choices displayed as buttons."""

    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        for index, ammo_name in enumerate(AMMO):
            button = discord.ui.Button(label=ammo_name, style=discord.ButtonStyle.primary, row=index // 4)

            async def callback(
                interaction: discord.Interaction,
                selected: str = ammo_name,
            ) -> None:
                await self._equip(interaction, selected)

            button.callback = callback
            self.add_item(button)

    async def _equip(
        self,
        interaction: discord.Interaction,
        ammo_name: str,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = equip_ammo(player, ammo_name)
        self.store.save()
        await interaction.response.edit_message(
            content=result_text(messages, player),
            view=AmmoView(self.user_id, self.store),
        )

    @discord.ui.button(label="Main menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=status(self.store.get(self.user_id)),
            view=ZombieMenuView(self.user_id, self.store),
        )


class UpgradeView(PlayerView):
    """Upgrade choices displayed as buttons."""

    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        choices = [
            ("Max health · 80 XP", "health"),
            ("Weapon damage · 100 XP", "damage"),
            ("Magazine size · 70 XP", "magazine"),
        ]
        for label, value in choices:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.success, row=0)

            async def callback(
                interaction: discord.Interaction,
                selected: str = value,
            ) -> None:
                await self._upgrade(interaction, selected)

            button.callback = callback
            self.add_item(button)

    async def _upgrade(
        self,
        interaction: discord.Interaction,
        stat: str,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = upgrade(player, stat)
        self.store.save()
        await interaction.response.edit_message(
            content=result_text(messages, player),
            view=UpgradeView(self.user_id, self.store),
        )

    @discord.ui.button(label="Main menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=status(self.store.get(self.user_id)),
            view=ZombieMenuView(self.user_id, self.store),
        )