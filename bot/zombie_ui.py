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
    """Top-level game menu."""

    @discord.ui.select(
        placeholder="Choose a game menu...",
        options=[
            discord.SelectOption(label="Combat", value="combat", description="Start a run or take a turn"),
            discord.SelectOption(label="Shop", value="shop", description="Buy supplies and weapons"),
            discord.SelectOption(label="Zones", value="zones", description="Travel to an unlocked zone"),
            discord.SelectOption(label="Ammo Lab", value="ammo", description="Buy and equip elemental ammo"),
            discord.SelectOption(label="Upgrades", value="upgrades", description="Spend XP on upgrades"),
        ],
    )
    async def menu_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        player = self.store.get(self.user_id)
        view_map: dict[str, PlayerView] = {
            "combat": CombatView(self.user_id, self.store),
            "shop": ShopView(self.user_id, self.store),
            "zones": ZoneView(self.user_id, self.store),
            "ammo": AmmoView(self.user_id, self.store),
            "upgrades": UpgradeView(self.user_id, self.store),
        }
        view = view_map[select.values[0]]
        await interaction.response.edit_message(content=status(player), view=view)

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
    """Combat actions presented as a select menu."""

    @discord.ui.select(
        placeholder="Choose a combat action...",
        options=[
            discord.SelectOption(label="Attack", value="attack", description="Fire one round at the zombie"),
            discord.SelectOption(label="Reload", value="reload", description="Refill your magazine"),
            discord.SelectOption(label="Heal", value="heal", description="Choose a healing item"),
            discord.SelectOption(label="Flee", value="flee", description="End the current run"),
        ],
    )
    async def action_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        action = select.values[0]
        if action == "heal":
            await interaction.response.edit_message(
                content="Choose a healing item.",
                view=HealView(self.user_id, self.store),
            )
            return
        player = self.store.get(self.user_id)
        messages = take_action(player, action)
        self.store.save()
        next_view: PlayerView = self if player.run_active else ZombieMenuView(self.user_id, self.store)
        await interaction.response.edit_message(
            content=result_text(messages, player),
            view=next_view,
        )

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
            content=result_text(messages, player),
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
    """Secondary select menu for healing choices."""

    @discord.ui.select(
        placeholder="Choose a healing item...",
        options=[
            discord.SelectOption(label="Full restore", value="full_restore"),
            discord.SelectOption(label="Painkillers", value="painkillers"),
        ],
    )
    async def heal_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = take_action(player, "heal", select.values[0])
        self.store.save()
        next_view: PlayerView = CombatView(self.user_id, self.store) if player.run_active else ZombieMenuView(
            self.user_id,
            self.store,
        )
        await interaction.response.edit_message(
            content=result_text(messages, player),
            view=next_view,
        )

    @discord.ui.button(label="Back to combat", style=discord.ButtonStyle.secondary, row=1)
    async def back(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content=status(self.store.get(self.user_id)),
            view=CombatView(self.user_id, self.store),
        )


class ShopView(PlayerView):
    """Shop select menu."""

    @discord.ui.select(
        placeholder="Choose an item...",
        options=[
            discord.SelectOption(label="Ammo box — $30", value="ammo"),
            discord.SelectOption(label="Painkillers — $40", value="painkillers"),
            discord.SelectOption(label="Full restore — $120", value="full_restore"),
            *[
                discord.SelectOption(
                    label=f"{weapon_name} — ${weapon_data['price']}",
                    value=weapon_name,
                    description=f"{weapon_data['damage']} damage, {weapon_data['mag']} round magazine",
                )
                for weapon_name, weapon_data in WEAPONS.items()
                if weapon_name != "Pistol"
            ],
        ],
    )
    async def shop_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = buy_item(player, select.values[0])
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
    """Zone travel select menu."""

    @discord.ui.select(
        placeholder="Choose a zone...",
        options=[
            discord.SelectOption(
                label=zone_name,
                value=zone_name,
                description=f"Unlocks at level {zone_data['min_level']}",
            )
            for zone_name, zone_data in ZONES.items()
        ],
    )
    async def zone_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = change_zone(player, select.values[0])
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
    """Ammo lab select menu."""

    @discord.ui.select(
        placeholder="Choose an ammo type...",
        options=[
            discord.SelectOption(
                label=ammo_name,
                value=ammo_name,
                description=f"${ammo_data['price']} — unlocks at level {ammo_data['unlock_level']}",
            )
            for ammo_name, ammo_data in AMMO.items()
        ],
    )
    async def ammo_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = equip_ammo(player, select.values[0])
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
    """Upgrade select menu."""

    @discord.ui.select(
        placeholder="Choose an upgrade...",
        options=[
            discord.SelectOption(label="Max health — 80 XP", value="health"),
            discord.SelectOption(label="Weapon damage — 100 XP", value="damage"),
            discord.SelectOption(label="Magazine size — 70 XP", value="magazine"),
        ],
    )
    async def upgrade_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        player = self.store.get(self.user_id)
        messages = upgrade(player, select.values[0])
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