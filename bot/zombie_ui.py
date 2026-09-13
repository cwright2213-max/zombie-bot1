"""Discord buttons and menus - CLEANED UI - minimal info."""

from __future__ import annotations

import discord

from bot.zombie_survival import (
    AMMO,
    MAX_FULL_RESTORES_PER_RUN,
    MAX_PAINKILLERS_PER_RUN,
    WEAPONS,
    ZONES,
    GameStore,
    ammo_effectiveness_text,
    buy_item,
    change_zone,
    equip_ammo,
    get_upgrade_cost,
    start_run,
    status,
    take_action,
    upgrade,
)

def _health_bar(current: int, maximum: int, width: int = 12) -> str:
    if not maximum:
        return "`░░░░░░░░░░░░`"
    pct = max(0, min(current, maximum)) / maximum
    filled = round(pct * width)
    return f"`{'█' * filled}{'░' * (width - filled)}`"

def _heal_counts(player):
    pain_left = max(0, MAX_PAINKILLERS_PER_RUN - player.painkillers_used_this_run)
    full_left = max(0, MAX_FULL_RESTORES_PER_RUN - player.full_restores_used_this_run)
    return pain_left, full_left

def combat_embed(messages: list[str], player: object) -> discord.Embed:
    is_dead = not getattr(player, "run_active", False)

    if is_dead:
        embed = discord.Embed(
            title="☠️ Run Ended",
            color=discord.Color.from_rgb(90, 90, 90),
            description="\n".join(m for m in messages if m) or "Your run is over.",
        )
        run_money = getattr(player, "run_money_earned", 0)
        run_xp = getattr(player, "run_xp_earned", 0)
        if run_money or run_xp:
            embed.add_field(
                name="📊 This Run",
                value=f"💵 +${run_money} • ✨ +{run_xp} XP",
                inline=True,
            )
        embed.add_field(
            name="💰 Total",
            value=f"**${player.money}** • Lvl {player.level}",
            inline=True,
        )
        embed.add_field(name="Status", value=f"❤️ {player.health}/{player.max_health} HP restored", inline=False)
        embed.set_footer(text="Start another run or open shop.")
        return embed

    embed = discord.Embed(
        title=f"🧟 WAVE {player.wave} • {player.zombies_remaining} left",
        color=discord.Color.from_rgb(237, 66, 69),
        description="\n".join(m for m in messages if m) or "Choose your action.",
    )
    # Clean player field - no dict spam
    spare = player.get_spare() if hasattr(player, 'get_spare') else player.spare_ammo.get(player.ammo_name, 0)
    embed.add_field(
        name=f"❤️ YOU — {player.health}/{player.max_health} HP",
        value=f"{_health_bar(player.health, player.max_health)} **{player.health}/{player.max_health}**\n🔫 `{player.magazine}/{player.magazine_size}` + {spare} spare",
        inline=True,
    )
    enemy = player.enemy
    if enemy:
        embed.add_field(
            name=f"💀 {enemy.name.upper()} — {enemy.health}/{enemy.max_health} HP",
            value=f"{_health_bar(enemy.health, enemy.max_health)} **{enemy.health}/{enemy.max_health}**\nWave {player.wave}",
            inline=True,
        )
    embed.set_footer(text="💊 Heal does NOT use your turn")
    return embed

def heal_menu_embed(player: object) -> discord.Embed:
    pain_left, full_left = _heal_counts(player)
    embed = discord.Embed(
        title="💚 Field Medic Kit",
        color=discord.Color.from_rgb(87, 242, 135),
        description=f"Health: **{player.health}/{player.max_health} HP** {_health_bar(player.health, player.max_health)}",
    )
    pain_status = "✅ Ready" if player.painkillers > 0 and pain_left > 0 and player.health < player.max_health else "❌"
    embed.add_field(name=f"💊 Painkillers {pain_status}", value=f"**{player.painkillers} owned**\n`{pain_left} left this run`", inline=True)
    full_status = "✅ Ready" if player.full_restores > 0 and full_left > 0 and player.health < player.max_health else "❌"
    embed.add_field(name=f"✨ Full Restore {full_status}", value=f"**{player.full_restores} owned**\n`{full_left} left this run`", inline=True)
    return embed

def status_detail_embed(player: object) -> discord.Embed:
    embed = discord.Embed(title="📊 Survivor Stats", color=discord.Color.from_rgb(88, 101, 242))
    embed.add_field(name="🔫 Loadout", value=f"**{player.weapon_name}** • {player.ammo_name}\n{player.magazine}/{player.magazine_size} + {player.get_spare()} spare", inline=True)
    embed.add_field(name="📈 Progress", value=f"Lvl {player.level} • {player.xp} XP\n⭐ {player.stars} • 💰 ${player.money}", inline=True)
    embed.add_field(name="💪 Upgrades", value=f"❤️ HP Lvl {player.health_upgrades}\n💥 Dmg Lvl {player.damage_upgrades}\n📦 Mag Lvl {player.mag_upgrades}\n🎯 Crit Lvl {player.crit_upgrades}\n🛡️ Armor Lvl {player.armor_upgrades}\n💰 Loot Lvl {player.scavenger_upgrades}", inline=False)
    embed.add_field(name=f"🌍 {player.zone_name}", value=ammo_effectiveness_text(player), inline=False)
    return embed

def shop_embed(player: object, last_messages: list[str] | None = None) -> discord.Embed:
    """CLEAN shop - no dict spam"""
    embed = discord.Embed(
        title="🛒 Armory Shop",
        color=discord.Color.from_rgb(87, 242, 135),
        description="\n".join(last_messages) if last_messages else f"💰 **${player.money}** available",
    )
    # Clean ammo display - not raw dict
    spare = player.get_spare() if hasattr(player, 'get_spare') else 0
    ammo_line = f"{player.magazine}/{player.magazine_size} mag + {spare} spare"
    if hasattr(player, 'spare_ammo') and isinstance(player.spare_ammo, dict):
        # Show total spare across types if multiple
        total_spare = sum(player.spare_ammo.values())
        ammo_line = f"{player.magazine}/{player.magazine_size} mag • {total_spare} total spare"
    
    embed.add_field(name="💰 Money", value=f"**${player.money}**", inline=True)
    embed.add_field(name="📦 Ammo", value=ammo_line, inline=True)
    embed.add_field(name="💊 Heals", value=f"{player.painkillers}x 💊 • {player.full_restores}x ✨", inline=True)
    return embed

class PlayerView(discord.ui.View):
    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(timeout=900)
        self.user_id = user_id
        self.store = store
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("This menu belongs to another survivor. Use `/zombie menu` for your own.", ephemeral=True)
        return False
    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

class ZombieMenuView(PlayerView):
    """CLEAN 2-row main menu - no clutter"""
    @discord.ui.button(label="▶️ Start Run", style=discord.ButtonStyle.success, row=0)
    async def start_run_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        messages = start_run(player)
        self.store.save()
        await interaction.response.edit_message(content=None, embed=combat_embed(messages, player), view=CombatView(self.user_id, self.store))

    @discord.ui.button(label="🛒 Shop", style=discord.ButtonStyle.primary, row=0)
    async def shop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=None, embed=shop_embed(player), view=ShopView(self.user_id, self.store))

    @discord.ui.button(label="⬆️ Upgrades", style=discord.ButtonStyle.success, row=0)
    async def upgrades(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=None, embed=status_detail_embed(player), view=UpgradeView(self.user_id, self.store))

    @discord.ui.button(label="🗺️ Zones", style=discord.ButtonStyle.secondary, row=1)
    async def zones(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(player), view=ZoneView(self.user_id, self.store))

    @discord.ui.button(label="🔬 Ammo Lab", style=discord.ButtonStyle.secondary, row=1)
    async def ammo(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(player) + "\n\n" + ammo_effectiveness_text(player), view=AmmoView(self.user_id, self.store))

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.secondary, row=1)
    async def stats_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=None, embed=status_detail_embed(player), view=ZombieMenuView(self.user_id, self.store))


class CombatView(PlayerView):
    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        player = self.store.get(user_id)
        if not player.run_active:
            self.clear_items()
            start_btn = discord.ui.Button(label="▶️ Start run", style=discord.ButtonStyle.success, row=0)
            async def start_cb(inter: discord.Interaction):
                p = self.store.get(self.user_id)
                msgs = start_run(p)
                self.store.save()
                await inter.response.edit_message(content=None, embed=combat_embed(msgs, p), view=CombatView(self.user_id, self.store))
            start_btn.callback = start_cb
            self.add_item(start_btn)
            menu_btn = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=0)
            async def menu_cb(inter: discord.Interaction):
                await inter.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))
            menu_btn.callback = menu_cb
            self.add_item(menu_btn)

    async def _take_action(self, interaction: discord.Interaction, action: str) -> None:
        player = self.store.get(self.user_id)
        messages = take_action(player, action)
        self.store.save()
        if player.run_active:
            await interaction.response.edit_message(content=None, embed=combat_embed(messages, player), view=CombatView(self.user_id, self.store))
        else:
            await interaction.response.edit_message(content=None, embed=combat_embed(messages, player), view=ZombieMenuView(self.user_id, self.store))

    @discord.ui.button(label="🔫 Attack", style=discord.ButtonStyle.danger, row=0)
    async def attack(self, interaction: discord.Interaction, _b): await self._take_action(interaction, "attack")
    @discord.ui.button(label="💊 Heal", style=discord.ButtonStyle.success, row=0)
    async def heal(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=None, embed=heal_menu_embed(self.store.get(self.user_id)), view=HealView(self.user_id, self.store))
    @discord.ui.button(label="🔄 Reload", style=discord.ButtonStyle.primary, row=0)
    async def reload(self, interaction: discord.Interaction, _b): await self._take_action(interaction, "reload")
    @discord.ui.button(label="🏃 Flee", style=discord.ButtonStyle.secondary, row=0)
    async def flee(self, interaction: discord.Interaction, _b): await self._take_action(interaction, "flee")
    @discord.ui.button(label="📊 Status", style=discord.ButtonStyle.secondary, row=1)
    async def show_status(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=None, embed=status_detail_embed(self.store.get(self.user_id)), view=StatusDetailView(self.user_id, self.store))
    @discord.ui.button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))

class StatusDetailView(PlayerView):
    @discord.ui.button(label="⬅️ Back to combat", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=None, embed=combat_embed([], player), view=CombatView(self.user_id, self.store))
    @discord.ui.button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=0)
    async def main_menu(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))

class HealView(PlayerView):
    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        player = self.store.get(user_id)
        pain_left, full_left = _heal_counts(player)
        at_full_hp = player.health >= player.max_health
        full_disabled = player.full_restores <= 0 or full_left <= 0 or at_full_hp
        full_label = f"✨ Full Restore • {player.full_restores} owned ({full_left} left)"
        full_button = discord.ui.Button(label=full_label, style=discord.ButtonStyle.success, row=0, disabled=full_disabled)
        async def full_callback(interaction: discord.Interaction) -> None:
            await self._use_heal(interaction, "full_restore")
        full_button.callback = full_callback
        self.add_item(full_button)
        pain_disabled = player.painkillers <= 0 or pain_left <= 0 or at_full_hp
        pain_label = f"💊 Painkillers • {player.painkillers} owned ({pain_left} left)"
        pain_button = discord.ui.Button(label=pain_label, style=discord.ButtonStyle.success, row=0, disabled=pain_disabled)
        async def pain_callback(interaction: discord.Interaction) -> None:
            await self._use_heal(interaction, "painkillers")
        pain_button.callback = pain_callback
        self.add_item(pain_button)
        back_button = discord.ui.Button(label="⬅️ Back to combat", style=discord.ButtonStyle.secondary, row=1)
        async def back_callback(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(content=None, embed=combat_embed([], self.store.get(self.user_id)), view=CombatView(self.user_id, self.store))
        back_button.callback = back_callback
        self.add_item(back_button)

    async def _use_heal(self, interaction: discord.Interaction, item: str) -> None:
        player = self.store.get(self.user_id)
        messages = take_action(player, "heal", item)
        self.store.save()
        await interaction.response.edit_message(content=None, embed=combat_embed(messages, player), view=CombatView(self.user_id, self.store) if player.run_active else ZombieMenuView(self.user_id, self.store))

class ShopView(PlayerView):
    def __init__(self, user_id: int, store: GameStore, last_messages: list[str] | None = None) -> None:
        super().__init__(user_id, store)
        self.last_messages = last_messages
        player = self.store.get(user_id)
        choices = [
            ("📦 Ammo box · $30", "ammo", discord.ButtonStyle.primary, player.money >= 30),
            ("💊 Painkillers · $40", "painkillers", discord.ButtonStyle.primary, player.money >= 40),
            ("✨ Full restore · $120", "full_restore", discord.ButtonStyle.primary, player.money >= 120),
        ]
        choices.extend((f"{name} · ${data['price']}", name, discord.ButtonStyle.secondary, player.money >= data["price"] and player.level >= data["unlock_level"]) for name, data in WEAPONS.items() if name != "Pistol")
        for index, (label, value, style, can_afford) in enumerate(choices):
            # Disable if can't afford to make it obvious money matters
            button = discord.ui.Button(label=label, style=style, row=index // 4, disabled=not can_afford)
            async def callback(interaction: discord.Interaction, selected: str = value) -> None:
                await self._buy(interaction, selected)
            button.callback = callback
            self.add_item(button)
        back = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=2)
        async def back_callback(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))
        back.callback = back_callback
        self.add_item(back)

    async def _buy(self, interaction: discord.Interaction, item: str) -> None:
        player = self.store.get(self.user_id)
        messages = buy_item(player, item)
        self.store.save()
        # CRITICAL FIX: Re-fetch player and rebuild embed with NEW money value
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=None, embed=shop_embed(player, messages), view=ShopView(self.user_id, self.store, messages))

class ZoneView(PlayerView):
    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        for index, zone_name in enumerate(ZONES):
            button = discord.ui.Button(label=f"🗺️ {zone_name}", style=discord.ButtonStyle.primary, row=index // 5)
            async def callback(interaction: discord.Interaction, selected: str = zone_name) -> None:
                await self._travel(interaction, selected)
            button.callback = callback
            self.add_item(button)
        back = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=1)
        async def back_callback(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))
        back.callback = back_callback
        self.add_item(back)
    async def _travel(self, interaction: discord.Interaction, zone_name: str) -> None:
        player = self.store.get(self.user_id)
        messages = change_zone(player, zone_name)
        self.store.save()
        await interaction.response.edit_message(content=status(player) + "\n\n" + "\n".join(messages), view=ZoneView(self.user_id, self.store))

class AmmoView(PlayerView):
    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        player = self.store.get(self.user_id)
        for index, ammo_name in enumerate(AMMO):
            ammo = AMMO[ammo_name]
            modifier = ZONES[player.zone_name].get("ammo_mods", {}).get(ammo_name, 1.0)
            marker = " ↑" if modifier > 1.0 else " ↓" if modifier < 1.0 else ""
            button = discord.ui.Button(label=f"{ammo_name} ({ammo['cost_per_attack']}/shot){marker}", style=discord.ButtonStyle.primary, row=index // 3)
            async def callback(interaction: discord.Interaction, selected: str = ammo_name) -> None:
                await self._equip(interaction, selected)
            button.callback = callback
            self.add_item(button)
        back = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=2)
        async def back_callback(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))
        back.callback = back_callback
        self.add_item(back)
    async def _equip(self, interaction: discord.Interaction, ammo_name: str) -> None:
        player = self.store.get(self.user_id)
        messages = equip_ammo(player, ammo_name)
        self.store.save()
        await interaction.response.edit_message(content=status(player) + "\n\n" + "\n".join(messages) + "\n\n" + ammo_effectiveness_text(player), view=AmmoView(self.user_id, self.store))

class UpgradeView(PlayerView):
    def __init__(self, user_id: int, store: GameStore) -> None:
        super().__init__(user_id, store)
        player = self.store.get(user_id)
        # Show all 6 upgrades with dynamic money costs
        choices = [
            (f"❤️ Health +20 · ${get_upgrade_cost(player,'health')}", "health", player.health_upgrades),
            (f"💥 Damage +3 · ${get_upgrade_cost(player,'damage')}", "damage", player.damage_upgrades),
            (f"📦 Mag +1 · ${get_upgrade_cost(player,'mag')}", "mag", player.mag_upgrades),
            (f"🎯 Crit +0.5% · ${get_upgrade_cost(player,'crit')}", "crit", player.crit_upgrades),
            (f"🛡️ Armor -2 dmg · ${get_upgrade_cost(player,'armor')}", "armor", player.armor_upgrades),
            (f"💰 Loot +5% · ${get_upgrade_cost(player,'scavenger')}", "scavenger", player.scavenger_upgrades),
        ]
        for index, (label, value, count) in enumerate(choices):
            cost = get_upgrade_cost(player, value)
            can_afford = player.money >= cost
            # Show current level in label: e.g. ❤️ Health +20 Lvl3 · $450
            display_label = f"{label} (Lvl {count})"
            button = discord.ui.Button(
                label=display_label, 
                style=discord.ButtonStyle.success if can_afford else discord.ButtonStyle.secondary, 
                row=index // 3,
                disabled=not can_afford
            )
            async def callback(interaction: discord.Interaction, selected: str = value) -> None:
                await self._upgrade(interaction, selected)
            button.callback = callback
            self.add_item(button)
        back = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=2)
        async def back_callback(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))
        back.callback = back_callback
        self.add_item(back)
        
        # Add info button showing money and stars
        info = discord.ui.Button(label=f"💰 ${player.money} | ⭐ {player.stars} flex", style=discord.ButtonStyle.primary, row=2, disabled=True)
        self.add_item(info)

    async def _upgrade(self, interaction: discord.Interaction, stat: str) -> None:
        player = self.store.get(self.user_id)
        messages = upgrade(player, stat)
        self.store.save()
        # Rebuild view with updated costs
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(player) + "\n\n" + "\n".join(messages), view=UpgradeView(self.user_id, self.store))
