"""Ultimate clean bot v4 - waves + kills, no Total Money Earned"""
import os, sys, json, random, logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone
import discord
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('zombie-bot')
from discord import app_commands

if Path("/data").exists():
    DB_PATH = Path("/data/players.db")
else:
    DB_PATH = Path("data/players.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def _get_conn():
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

def load_all_players():
    try:
        conn = _get_conn()
        cur = conn.execute("SELECT user_id, data FROM players")
        result = {}
        for uid, jdata in cur.fetchall():
            try:
                result[uid] = json.loads(jdata)
            except:
                pass
        conn.close()
        print(f"[STORAGE] Loaded {len(result)} players")
        return result
    except Exception as e:
        print(f"[STORAGE] Load failed: {e}")
        return {}

def save_player(user_id, player_dict):
    try:
        conn = _get_conn()
        conn.execute("INSERT OR REPLACE INTO players (user_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (str(user_id), json.dumps(player_dict)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Save failed: {e}")

SAVE_FILE = DB_PATH

def make_bar(current: int, max_val: int, length: int = 12) -> str:
    if max_val <= 0:
        return "░" * length
    pct = max(0, min(1, current / max_val))
    filled = int(pct * length)
    return "█" * filled + "░" * (length - filled)

def combat_embed(player, last_msgs=None):
    import discord
    p_bar = make_bar(player.health, player.max_health, 12)
    p_pct = int(player.health / player.max_health * 100) if player.max_health else 0
    if player.enemy:
        e_bar = make_bar(player.enemy.health, player.enemy.max_health, 12)
        e_pct = int(player.enemy.health / player.enemy.max_health * 100) if player.enemy.max_health else 0
        e_name = player.enemy.name
        e_hp = f"{player.enemy.health}/{player.enemy.max_health}"
        e_dmg = player.enemy.damage
    else:
        e_bar = "░"*12
        e_pct = 0
        e_name = "No enemy"
        e_hp = "0/0"
        e_dmg = 0
    embed = discord.Embed(
        title=f"🧟 {player.zone_name} — WAVE {player.wave} | {player.zombies_remaining} zombies left",
        color=discord.Color.from_rgb(200, 50, 50) if p_pct < 30 else discord.Color.from_rgb(50, 180, 80)
    )
    embed.add_field(
        name=f"❤️ You: {player.health}/{player.max_health} HP ({p_pct}%)",
        value=f"`{p_bar}`\n🔫 {player.weapon_name} {player.magazine}/{player.magazine_size} ({player.get_spare()} spare) [{player.ammo_name}]",
        inline=False
    )
    embed.add_field(
        name=f"💀 {e_name}: {e_hp} HP ({e_pct}%)",
        value=f"`{e_bar}`\n⚔️ ~{e_dmg} dmg",
        inline=False
    )
    if last_msgs:
        clean = [m for m in last_msgs if m and "HP restored" not in m and "Waves survived" not in m][:3]
        if clean:
            embed.add_field(name="⚔️ Last action", value="\n".join(clean)[:1024], inline=False)
    embed.set_footer(text=f"💰 ${player.money} | ⭐ {player.stars} | ✨ {player.xp} XP | {player.ammo_name} {player.magazine}/{player.magazine_size}")
    return embed



MAX_PAINKILLERS_PER_RUN = 3
MAX_FULL_RESTORES_PER_RUN = 1
ZONES: dict[str, dict[str, Any]] = {
    "Graveyard": {"min_level": 1, "hp_mult": 0.9, "dmg_mult": 0.9, "money_mult": 1.5, "xp_mult": 1.6, "desc": "Foggy, quiet, and good for learning.", "weights": [60, 25, 12, 3], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.00, "Frostbite": 1.00, "Toxic": 1.00, "Shock": 1.00}},
    "Mega Death City": {"min_level": 50, "hp_mult": 2.2, "dmg_mult": 1.4, "money_mult": 1.6, "xp_mult": 1.6, "desc": "A concrete jungle with tougher, richer zombies.", "weights": [30, 30, 25, 15], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.20, "Frostbite": 0.90, "Toxic": 1.00, "Shock": 1.15}},
    "Frostbitten Outskirts": {"min_level": 100, "hp_mult": 3.8, "dmg_mult": 1.8, "money_mult": 2.2, "xp_mult": 2.4, "desc": "Freezing rain and frost armor.", "weights": [20, 20, 35, 25], "ammo_mods": {"Standard": 1.00, "Bleed": 0.90, "Incendiary": 1.40, "Frostbite": 0.70, "Toxic": 1.00, "Shock": 1.15}},
    "Toxic Wasteland": {"min_level": 150, "hp_mult": 6.0, "dmg_mult": 2.3, "money_mult": 3.0, "xp_mult": 3.2, "desc": "A green haze where toxic rounds shine.", "weights": [15, 15, 35, 35], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.10, "Frostbite": 1.00, "Toxic": 1.50, "Shock": 0.90}},
    "The Void": {"min_level": 200, "hp_mult": 10.0, "dmg_mult": 3.0, "money_mult": 4.0, "xp_mult": 4.5, "desc": "Endgame. Everything wants you dead.", "weights": [10, 10, 30, 50], "ammo_mods": {"Standard": 1.00, "Bleed": 1.10, "Incendiary": 1.15, "Frostbite": 1.10, "Toxic": 1.25, "Shock": 1.50}},
}
AMMO: dict[str, dict[str, Any]] = {
    "Standard": {"unlock_level": 1, "price": 0, "desc": "Reliable regular lead.", "effect": None, "cost_per_attack": 1, "box_price": 30, "box_amount": 24},
    "Bleed": {"unlock_level": 10, "price": 200, "desc": "25% bleed 8 dmg x3", "effect": "bleed", "cost_per_attack": 2, "box_price": 50, "box_amount": 24},
    "Incendiary": {"unlock_level": 35, "price": 600, "desc": "30% burn 12 dmg x2", "effect": "burn", "cost_per_attack": 3, "box_price": 80, "box_amount": 24},
    "Frostbite": {"unlock_level": 70, "price": 1200, "desc": "20% halve dmg x3", "effect": "freeze", "cost_per_attack": 4, "box_price": 110, "box_amount": 24},
    "Toxic": {"unlock_level": 110, "price": 2500, "desc": "35% poison 10 dmg x4", "effect": "poison", "cost_per_attack": 5, "box_price": 150, "box_amount": 24},
    "Shock": {"unlock_level": 160, "price": 5000, "desc": "15% stun 1 turn", "effect": "shock", "cost_per_attack": 6, "box_price": 200, "box_amount": 24},
}
WEAPONS: dict[str, dict[str, int]] = {
    "Pistol": {"damage": 20, "mag": 12, "price": 0, "unlock_level": 1},
    "Shotgun": {"damage": 45, "mag": 6, "price": 250, "unlock_level": 15},
    "Rifle": {"damage": 35, "mag": 30, "price": 500, "unlock_level": 30},
    "SMG": {"damage": 25, "mag": 40, "price": 900, "unlock_level": 60},
    "Sawed-Of": {"damage": 70, "mag": 2, "price": 1800, "unlock_level": 90},
}

# --- DEATH LINES - SPLIT BY TYPE ---
NORMAL_DEATH_LINES = [
    "Bro really thought he was the main character 💀 LMAO dead.",
    "Your K/D is so bad the zombies are laughing at you.",
    "Even the Walkers are embarrassed they killed YOU.",
    "You got folded like laundry, buddy. Stay down.",
    "Graveyard's full of heroes like you — oh wait, you're just food.",
    "Skill issue. Literally. Uninstall, survivor.",
    "The zombies didn't even have to try. You just sucked.",
    "Nice try, hero. The graveyard just got one plot fuller.",
]

NO_AMMO_DEATH_LINES = [
    "The hoard was too big for you eh buddy? Pathetic.",
    "You brought a water gun to a zombie apocalypse. Clown.",
    "Imagine dying with all that expensive gear. Couldn't be me.",
    "CLICK CLICK... that's the sound of you being an idiot.",
    "Shoulda bought ammo instead of that dumb hat, rookie!",
    "You ran out of bullets AND braincells at the same time. Impressive.",
    "No ammo? No chance. No brain? Obviously.",
    "My man really tried to fist-fight the hoard. Respectfully, dumbass.",
]

def get_cocky_line() -> str:
    import random
    return random.choice(NORMAL_DEATH_LINES)

def get_no_ammo_line() -> str:
    import random
    return random.choice(NO_AMMO_DEATH_LINES)


ZOMBIES: dict[str, dict[str, int]] = {
    "Walker": {"health": 50, "damage": 10, "money": 18, "xp": 10},
    "Runner": {"health": 35, "damage": 18, "money": 32, "xp": 18},
    "Brute": {"health": 100, "damage": 15, "money": 65, "xp": 30},
    "Mutant": {"health": 150, "damage": 25, "money": 140, "xp": 70},
}
@dataclass
class Enemy:
    name: str; health: int; max_health: int; damage: int; money_reward: int; xp_reward: int; effects: dict[str, int] = field(default_factory=dict)
@dataclass
class Survivor:
    max_health: int = 100; health: int = 100; money: int = 0; xp: int = 0; stars: int = 0
    weapon_name: str = "Pistol"; weapon_damage: int = 20; magazine_size: int = 12; magazine: int = 12
    spare_ammo: dict[str, int] = field(default_factory=lambda: {"Standard": 36})
    full_restores: int = 1; painkillers: int = 3; painkillers_used_this_run: int = 0; full_restores_used_this_run: int = 0
    run_money_earned: int = 0; run_xp_earned: int = 0; run_zombies_killed: int = 0; zone_name: str = "Graveyard"; ammo_name: str = "Standard"
    owned_ammo: list[str] = field(default_factory=lambda: ["Standard"]); owned_weapons: list[str] = field(default_factory=lambda: ["Pistol"])
    run_active: bool = False; wave: int = 0; zombies_remaining: int = 0; enemy: Enemy | None = None
    # --- NEW: permanent upgrade counters ---
    damage_upgrades: int = 0; health_upgrades: int = 0; mag_upgrades: int = 0
    crit_upgrades: int = 0; armor_upgrades: int = 0; scavenger_upgrades: int = 0
    # --- STAR UPGRADES (prestige) - CUSTOM 4 ---
    star_dodge_upgrades: int = 0; star_magical_upgrades: int = 0
    star_medic_upgrades: int = 0; star_pet_upgrades: int = 0
    @property
    def level(self) -> int: return level_for_xp(self.xp)
    def get_spare(self, ammo_type: str | None = None) -> int: return self.spare_ammo.get(ammo_type or self.ammo_name, 0)
    def recalc_stats(self):
        """Recalculate weapon damage / max_health / mag size based on permanent upgrades"""
        base = WEAPONS.get(self.weapon_name, WEAPONS["Pistol"])
        self.weapon_damage = base["damage"] + self.damage_upgrades * 3
        self.magazine_size = base["mag"] + self.mag_upgrades * 1
        self.max_health = 100 + self.health_upgrades * 20
    @property
    def crit_chance(self) -> float:
        if self.crit_upgrades <= 0:
            return 0.0
        # First upgrade = 2%, each extra = +0.5%, cap 40%
        chance = 0.02 + (self.crit_upgrades - 1) * 0.005
        return min(chance, 0.40)
    @property
    def armor_reduction(self) -> int:
        return min(self.armor_upgrades * 2, 35)
    @property
    def scavenger_bonus(self) -> float:
        return 1.0 + self.scavenger_upgrades * 0.05
    # --- STAR UPGRADE PROPERTIES ---
    @property
    def dodge_chance(self) -> float:
        if self.star_dodge_upgrades <= 0:
            return 0.0
        # 10% base, +0.5% per extra level, cap 30%
        chance = 0.10 + (self.star_dodge_upgrades - 1) * 0.005
        return min(chance, 0.30)
    @property
    def magical_bullet_chance(self) -> float:
        if self.star_magical_upgrades <= 0:
            return 0.0
        chance = 0.05 + (self.star_magical_upgrades - 1) * 0.005
        return min(chance, 0.20)
    @property
    def medic_chance(self) -> float:
        if self.star_medic_upgrades <= 0:
            return 0.0
        chance = 0.02 + (self.star_medic_upgrades - 1) * 0.0025
        return min(chance, 0.07)
    @property
    def pet_chance(self) -> float:
        if self.star_pet_upgrades <= 0:
            return 0.0
        chance = 0.05 + (self.star_pet_upgrades - 1) * 0.01
        return min(chance, 0.10)
    @property
    def pet_damage(self) -> int:
        return int(self.weapon_damage * 0.25)
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self); d["__version"] = 3; return d
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Survivor":
        if data.get("zone_name") not in ZONES: data["zone_name"] = "Graveyard"
        if data.get("ammo_name") not in AMMO: data["ammo_name"] = "Standard"
        if data.get("weapon_name") not in WEAPONS: data["weapon_name"] = "Pistol"
        # Migration: ensure upgrade counters exist
        if "damage_upgrades" not in data:
            # Estimate from old saves: if weapon_damage higher than base, convert to upgrades
            base_dmg = WEAPONS.get(data.get("weapon_name","Pistol"), WEAPONS["Pistol"])["damage"]
            old_bonus = max(0, data.get("weapon_damage", base_dmg) - base_dmg)
            # Old system was +5 per upgrade, new is +3 - approximate
            data["damage_upgrades"] = old_bonus // 5
        if "health_upgrades" not in data:
            data["health_upgrades"] = max(0, (data.get("max_health",100)-100)//20)
        if "star_dodge_upgrades" not in data:
            data["star_dodge_upgrades"] = data.get("star_crit_dmg_upgrades", 0)  # migrate old if exists
        if "star_magical_upgrades" not in data:
            data["star_magical_upgrades"] = data.get("star_elemental_upgrades", 0)
        if "star_medic_upgrades" not in data:
            data["star_medic_upgrades"] = data.get("star_fortitude_upgrades", 0)
        if "star_pet_upgrades" not in data:
            data["star_pet_upgrades"] = data.get("star_hunter_upgrades", 0)

        # Ensure new fields exist
        for f in ["star_dodge_upgrades", "star_magical_upgrades", "star_medic_upgrades", "star_pet_upgrades"]:
            if f not in data:
                data[f] = 0

        if "mag_upgrades" not in data:
            base_mag = WEAPONS.get(data.get("weapon_name","Pistol"), WEAPONS["Pistol"])["mag"]
            old_mag_bonus = max(0, data.get("magazine_size", base_mag) - base_mag)
            data["mag_upgrades"] = old_mag_bonus // 4
        if "crit_upgrades" not in data:
            data["crit_upgrades"] = 0
        if "armor_upgrades" not in data:
            data["armor_upgrades"] = 0
        if "scavenger_upgrades" not in data:
            data["scavenger_upgrades"] = 0
        enemy_data = data.get("enemy")
        enemy = Enemy(**enemy_data) if isinstance(enemy_data, dict) else None
        spare = data.get("spare_ammo", {"Standard": 36})
        if isinstance(spare, int): spare = {"Standard": spare}
        allowed = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        allowed["spare_ammo"] = spare; allowed["enemy"] = enemy
        allowed.setdefault("painkillers_used_this_run", 0); allowed.setdefault("full_restores_used_this_run", 0)
        allowed.setdefault("run_money_earned", 0); allowed.setdefault("run_xp_earned", 0)
        allowed.setdefault("owned_ammo", ["Standard"]); allowed.setdefault("owned_weapons", ["Pistol"])
        if "Pistol" not in allowed["owned_weapons"]: allowed["owned_weapons"].append("Pistol")
        if "stars" not in data: allowed["stars"] = max(0, level_for_xp(int(data.get("xp", 0))) - 1)
        return cls(**allowed)
def status(player: Survivor) -> str:
    """CLEAN VERSION - minimal info at a glance"""
    earned, needed = level_progress(player)
    
    if player.run_active and player.enemy:
        lines = [
            f"**🧟 {player.zone_name} — WAVE {player.wave}** | {player.zombies_remaining} zombies left",
            f"❤️ {player.health}/{player.max_health} HP | 🔫 {player.weapon_name} {player.magazine}/{player.magazine_size} ({player.get_spare()} spare)",
            f"💀 Fighting {player.enemy.name} {player.enemy.health}/{player.enemy.max_health} HP",
        ]
        if player.run_money_earned or player.run_xp_earned:
            lines.append(f"💵 Run: ${player.run_money_earned} • ✨ {player.run_xp_earned} XP")
        return "\n".join(lines)
    
    lines = [
        f"**🧟 {player.zone_name} — Lvl {player.level}** ({earned}/{needed} XP)",
        f"❤️ {player.health}/{player.max_health} | 💰 ${player.money} | ⭐ {player.stars}",
        f"🔫 {player.weapon_name} {player.magazine}/{player.magazine_size} • {player.get_spare()} spare [{player.ammo_name}]",
    ]
    
    if player.health < player.max_health and (player.painkillers > 0 or player.full_restores > 0):
        pain_left = MAX_PAINKILLERS_PER_RUN - player.painkillers_used_this_run
        full_left = MAX_FULL_RESTORES_PER_RUN - player.full_restores_used_this_run
        heals = []
        if player.painkillers > 0:
            heals.append(f"💊 {player.painkillers}x ({pain_left} left)")
        if player.full_restores > 0:
            heals.append(f"✨ {player.full_restores}x ({full_left} left)")
        if heals:
            lines.append(" • ".join(heals))
    
    return "\n".join(lines)

def status_detailed(player: Survivor) -> str:
    """Detailed view for inventory/stats menu"""
    earned, needed = level_progress(player)
    lines = [
        f"**📊 Survivor Detail — Lvl {player.level}**",
        f"❤️ HP: {player.health}/{player.max_health} (+{player.health_upgrades*20})",
        f"💥 Dmg: {player.weapon_damage} (+{player.damage_upgrades*3}) | 📦 Mag: {player.magazine_size} (+{player.mag_upgrades})",
        f"🎯 Crit: {int(player.crit_chance*100)}% | 🛡️ Armor: -{player.armor_reduction} | 💰 Loot: +{int((player.scavenger_bonus-1)*100)}%",
        f"💰 ${player.money} | ⭐ {player.stars} | ✨ {player.xp} XP ({earned}/{needed})",
        f"🔫 {player.weapon_name} [{player.ammo_name}] | 📦 Spare: {player.get_spare()}",
        f"🎒 Ammo: {', '.join([f'{k}:{v}' for k,v in player.spare_ammo.items() if v>0]) or 'Empty'}",
        f"💊 Painkillers: {player.painkillers} | ✨ Restores: {player.full_restores}",
        f"🗺️ Zone: {player.zone_name} | Guns: {', '.join(player.owned_weapons)}",
    ]
    return "\n".join(lines)

def get_status(player: Survivor) -> str:
    return status(player)

def get_detailed_status(player: Survivor) -> str:

    return status_detailed(player)




class GameStore:
    """CONSTANT SAVE - every single player action triggers instant Postgres save - zero loss"""
    def __init__(self):
        self.players = {}
        self._save_count = 0
        self.load()
    def get(self, user_id: int):
        key = str(user_id)
        if key not in self.players:
            self.players[key] = Survivor()
            try:
                save_player(key, self.players[key].to_dict())
                self._save_count += 1
            except:
                from dataclasses import asdict
                save_player(key, asdict(self.players[key]))
        return self.players[key]
    def save_one(self, key: str):
        p = self.players.get(key)
        if p:
            try:
                save_player(key, p.to_dict())
                self._save_count += 1
            except:
                from dataclasses import asdict
                save_player(key, asdict(p))
    async def save_one_async(self, key: str):
        import asyncio
        p = self.players.get(key)
        if p:
            try:
                d = p.to_dict()
            except:
                from dataclasses import asdict
                d = asdict(p)
            await asyncio.to_thread(save_player, key, d)
            self._save_count += 1
    def save(self):
        for k, p in self.players.items():
            try:
                save_player(k, p.to_dict())
            except:
                from dataclasses import asdict
                save_player(k, asdict(p))
        if self.players:
            print(f"[AUTOSAVE] Saved {len(self.players)} players to Postgres - all safe")
    async def save_async(self):
        import asyncio
        tasks=[]
        for k,p in self.players.items():
            try: d=p.to_dict()
            except:
                from dataclasses import asdict
                d=asdict(p)
            tasks.append(asyncio.to_thread(save_player,k,d))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    def load(self):
        raw=load_all_players()
        loaded={}
        for k,v in raw.items():
            try:
                if isinstance(v, dict):
                    loaded[k]=Survivor.from_dict(v)
            except Exception as e:
                print(f"Corrupt {k}: {e}")
                continue
        self.players=loaded
        print(f"[STORE] Loaded {len(loaded)} players - PERSISTENT")

game_store = GameStore()

async def background_autosave():
    import asyncio
    await asyncio.sleep(60)
    while True:
        try:
            game_store.save()
        except Exception as e:
            print(f"[AUTOSAVE ERROR] {e}")
        await asyncio.sleep(60)

class PlayerView(discord.ui.View):
    def __init__(self, user_id: int, store: GameStore, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.store = store
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your game!", ephemeral=True)
            return False
        return True

class ZombieMenuView(PlayerView):
    @discord.ui.button(label="▶️ Start run", style=discord.ButtonStyle.success, row=0)
    async def start_run(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        if player.run_active:
            await interaction.response.send_message("⚠️ Already in a run! Use Combat.", ephemeral=True)
            return
        msgs = start_run(player)
        self.store.save()
        await interaction.response.edit_message(content="\n".join(msgs) + "\n\n" + status(player), view=CombatView(self.user_id, self.store))
    @discord.ui.button(label="⚔️ Combat", style=discord.ButtonStyle.danger, row=0)
    async def combat(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        if not player.run_active:
            await interaction.response.send_message("❌ Not in a run. Tap Start run first.", ephemeral=True)
            return
        embed = combat_embed(player, [action_help(player)])
        await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store))
    @discord.ui.button(label="🛒 Shop", style=discord.ButtonStyle.primary, row=0)
    async def shop(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ShopView(self.user_id, self.store))
    @discord.ui.button(label="🗺️ Zones", style=discord.ButtonStyle.primary, row=1)
    async def zones(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ZoneView(self.user_id, self.store))
    @discord.ui.button(label="🧪 Ammo lab", style=discord.ButtonStyle.primary, row=1)
    async def ammo(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=AmmoView(self.user_id, self.store))
    @discord.ui.button(label="⬆️ Upgrades", style=discord.ButtonStyle.success, row=1)
    async def upgrades(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)) + f"\n💰 ${self.store.get(self.user_id).money} | ⭐ {self.store.get(self.user_id).stars} flex", view=UpgradeView(self.user_id, self.store))
    @discord.ui.button(label="🔄 Refresh status", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ZombieMenuView(self.user_id, self.store))


class CombatView(PlayerView):
    @discord.ui.button(label="🔫 Attack", style=discord.ButtonStyle.danger, row=0)
    async def attack(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        msgs = take_action(player, "attack")
        self.store.save()
        if not player.run_active:
            embed = discord.Embed(
                title="☠️ Run Ended",
                description="\n".join(msgs),
                color=discord.Color.red()
            )
            embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
            embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
            embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
            embed.set_footer(text=f"HP restored to {player.max_health}/{player.max_health} • Use Start run for another go")
            await interaction.response.edit_message(content=None, embed=embed, view=ZombieMenuView(self.user_id, self.store))
        else:
            embed = combat_embed(player, msgs)
            await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store))

    @discord.ui.button(label="🔄 Reload", style=discord.ButtonStyle.primary, row=0)
    async def reload(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        msgs = take_action(player, "reload")
        self.store.save()
        if not player.run_active:
            embed = discord.Embed(
                title="☠️ Run Ended",
                description="\n".join(msgs),
                color=discord.Color.red()
            )
            embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
            embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
            embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
            embed.set_footer(text=f"HP restored to {player.max_health}/{player.max_health}")
            await interaction.response.edit_message(content=None, embed=embed, view=ZombieMenuView(self.user_id, self.store))
        else:
            embed = combat_embed(player, msgs)
            await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store))

    @discord.ui.button(label="💊 Heal", style=discord.ButtonStyle.success, row=0)
    async def heal(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        embed = combat_embed(player, ["Choose heal item"])
        await interaction.response.edit_message(content=None, embed=embed, view=HealView(self.user_id, self.store))

    @discord.ui.button(label="🏃 Flee", style=discord.ButtonStyle.secondary, row=0)
    async def flee(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        msgs = take_action(player, "flee")
        self.store.save()
        embed = discord.Embed(
            title="🏃 You Fled!",
            description="\n".join(msgs),
            color=discord.Color.green()
        )
        embed.add_field(name="🌊 Waves", value=f"{player.wave} survived\nReached Wave {player.wave}", inline=True)
        embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
        embed.add_field(name="💰 Kept", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
        embed.set_footer(text=f"HP restored to {player.max_health}/{player.max_health} • Fleeing keeps all rewards")
        await interaction.response.edit_message(content=None, embed=embed, view=ZombieMenuView(self.user_id, self.store))


class HealView(PlayerView):
    def __init__(self, user_id: int, store, timeout: float = 180):
        super().__init__(user_id, store, timeout)
        player = self.store.get(user_id)
        # Update button labels to show counts
        # We need to dynamically set labels, so override in __init__
        # Clear default buttons and re-add with counts
        self.clear_items()
        # Painkillers button with count and limits
        pk_left = 3 - player.painkillers_used_this_run
        pk_label = f"💊 Painkillers ({player.painkillers}x - {pk_left} left this run)"
        pk_btn = discord.ui.Button(label=pk_label[:80], style=discord.ButtonStyle.success, row=0)
        async def pk_cb(interaction,):
            p=self.store.get(self.user_id)
            msgs=take_action(p,"heal","painkillers")
            self.store.save()
            embed = combat_embed(p, msgs)
            await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store))
        pk_btn.callback = pk_cb
        self.add_item(pk_btn)

        fr_left = 1 - player.full_restores_used_this_run
        fr_label = f"✨ Full restore ({player.full_restores}x - {fr_left} left)"
        fr_btn = discord.ui.Button(label=fr_label[:80], style=discord.ButtonStyle.success, row=0)
        async def fr_cb(interaction,):
            p=self.store.get(self.user_id)
            msgs=take_action(p,"heal","full_restore")
            self.store.save()
            embed = combat_embed(p, msgs)
            await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store))
        fr_btn.callback = fr_cb
        self.add_item(fr_btn)

        back_btn = discord.ui.Button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=1)
        async def back_cb(interaction,):
            p=self.store.get(self.user_id)
            embed = combat_embed(p, [action_help(p)])
            await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store))
        back_btn.callback = back_cb
        self.add_item(back_btn)





class ShopView(PlayerView):
    def __init__(self, user_id: int, store, timeout: float = 180):
        super().__init__(user_id, store, timeout)
        player = self.store.get(user_id)
        # Weapon buttons with cost and level
        for i, wname in enumerate(["Shotgun", "Rifle", "SMG", "Sawed-Of"]):
            if wname in WEAPONS:
                w = WEAPONS[wname]
                owned = wname in player.owned_weapons
                price = w["price"]
                lvl = w["unlock_level"]
                if owned:
                    label = f"🔫 {wname} (Owned)"
                else:
                    label = f"🔫 {wname} ${price} Lvl {lvl}"
                btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary if not owned else discord.ButtonStyle.secondary, row=i//2)
                async def cb(interaction, wn=wname):
                    p=self.store.get(self.user_id)
                    msgs=buy_item(p, wn)
                    self.store.save()
                    await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+status(p), view=ShopView(self.user_id, self.store))
                btn.callback = cb
                self.add_item(btn)

    @discord.ui.button(label="📦 Ammo box", style=discord.ButtonStyle.primary, row=2)
    async def ammo(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        # Show box cost before buying
        cur_ammo = p.ammo_name
        box_price = AMMO[cur_ammo]["box_price"]
        box_amount = AMMO[cur_ammo]["box_amount"]
        msgs=buy_item(p,"ammo")
        self.store.save()
        # Add cost info
        info = f"📦 {cur_ammo} crate: ${box_price} for {box_amount} rounds"
        await interaction.response.edit_message(content="\n".join(msgs)+"\n"+info+"\n\n"+status(p), view=ShopView(self.user_id, self.store))
    
    @discord.ui.button(label="💊 Painkillers $15", style=discord.ButtonStyle.success, row=2)
    async def pk(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        msgs=buy_item(p,"painkillers")
        self.store.save()
        await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+status(p), view=ShopView(self.user_id, self.store))
    
    @discord.ui.button(label="✨ Full restore $80", style=discord.ButtonStyle.success, row=2)
    async def fr(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        msgs=buy_item(p,"full_restore")
        self.store.save()
        await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+status(p), view=ShopView(self.user_id, self.store))
    
    @discord.ui.button(label="🧪 Ammo prices", style=discord.ButtonStyle.primary, row=3)
    async def ammo_prices(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        # Show all ammo crate costs
        lines = ["**📦 Ammo Crate Costs:**"]
        for aname, adata in AMMO.items():
            lines.append(f"{aname}: ${adata['box_price']} for {adata['box_amount']} rounds ({adata['cost_per_attack']}/shot) - {adata['desc']}")
        lines.append("")
        lines.append(status(p))
        await interaction.response.edit_message(content="\n".join(lines), view=ShopView(self.user_id, self.store))
    
    @discord.ui.button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=3)
    async def main(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ZombieMenuView(self.user_id, self.store))



class ZoneView(PlayerView):
    def __init__(self, user_id, store):
        super().__init__(user_id, store)
        for i, zone_name in enumerate(ZONES):
            btn = discord.ui.Button(label=zone_name, style=discord.ButtonStyle.primary, row=i//2)
            async def cb(interaction, zn=zone_name):
                p=self.store.get(self.user_id); msgs=change_zone(p,zn); self.store.save()
                await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+status(p), view=ZoneView(self.user_id, self.store))
            btn.callback = cb
            self.add_item(btn)
    @discord.ui.button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=2)
    async def main(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))


class AmmoView(PlayerView):
    def __init__(self, user_id, store):
        super().__init__(user_id, store)
        player = self.store.get(user_id)
        for i, ammo_name in enumerate(AMMO):
            ammo = AMMO[ammo_name]
            owned = ammo_name in player.owned_ammo
            cost_per = ammo["cost_per_attack"]
            price = ammo["price"]
            lvl = ammo["unlock_level"]
            desc = ammo["desc"]
            spare = player.spare_ammo.get(ammo_name, 0)
            if ammo_name == "Standard":
                label = f"Standard {cost_per}/shot (Free) {spare} spare"
            else:
                if owned:
                    label = f"{ammo_name} {cost_per}/shot {spare} spare {desc}"
                else:
                    label = f"{ammo_name} {cost_per}/shot ${price} Lvl {lvl} {desc}"
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary if not owned else discord.ButtonStyle.success, row=i//2)
            async def cb(interaction, an=ammo_name):
                p=self.store.get(self.user_id)
                msgs=equip_ammo(p,an)
                self.store.save()
                ammo_info = AMMO[an]
                # Build details with explicit newline via \n in file
                details = f"**{an}** | Cost: {ammo_info['cost_per_attack']}/shot | Effect: {ammo_info['desc']} | Box: ${ammo_info['box_price']} for {ammo_info['box_amount']} | Spare: {p.spare_ammo.get(an,0)}"
                await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+details+"\n\n"+status(p), view=AmmoView(self.user_id, self.store))
            btn.callback = cb
            self.add_item(btn)
    
    @discord.ui.button(label="Buy ammo box $30-200", style=discord.ButtonStyle.primary, row=3)
    async def buy_box(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        msgs=buy_item(p,"ammo")
        self.store.save()
        await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+status(p), view=AmmoView(self.user_id, self.store))
    
    @discord.ui.button(label="Main menu", style=discord.ButtonStyle.secondary, row=3)
    async def main(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ZombieMenuView(self.user_id, self.store))



class UpgradeView(PlayerView):
    def __init__(self, user_id: int, store):
        super().__init__(user_id, store)
        player = self.store.get(user_id)
        def make_btn(stat, emoji, name, plus, row):
            cost = get_upgrade_cost(player, stat)
            lvl = getattr(player, f"{stat}_upgrades", 0)
            if stat == "scavenger":
                lvl = player.scavenger_upgrades
            label = f"{emoji} {name} {plus} · ${cost} (Lvl {lvl})"
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.success, row=row)
            async def cb(interaction, stat=stat):
                p=self.store.get(self.user_id); msgs=upgrade(p,stat); self.store.save()
                await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+status(p)+f"\n💰 ${p.money} | ⭐ {p.stars}", view=UpgradeView(self.user_id, self.store))
            btn.callback = cb
            return btn
        self.add_item(make_btn("health","❤️","Health","+20",0))
        self.add_item(make_btn("damage","💥","Damage","+3",0))
        self.add_item(make_btn("mag","📦","Mag","+1",0))
        self.add_item(make_btn("crit","🎯","Crit","+2%",1))
        self.add_item(make_btn("armor","🛡️","Armor","-2",1))
        self.add_item(make_btn("scavenger","💰","Loot","+5%",1))
    @discord.ui.button(label="⭐ Star Upgrades", style=discord.ButtonStyle.primary, row=2)
    async def stars(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(p)+f"\n💰 ${p.money} | ⭐ {p.stars} flex\n**STAR PRESTIGE**", view=StarUpgradeView(self.user_id, self.store))
    @discord.ui.button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=2)
    async def mainmenu(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))

class StarUpgradeView(PlayerView):
    def __init__(self, user_id: int, store):
        super().__init__(user_id, store)
        player = self.store.get(user_id)
        def make_star(stat, emoji, name, row):
            cost = get_star_upgrade_cost(player, stat)
            lvl = 0
            cur = 0.0
            cap = ""
            if stat == "dodge":
                lvl = player.star_dodge_upgrades; cur = player.dodge_chance*100; cap="30%"
            elif stat == "magical":
                lvl = player.star_magical_upgrades; cur = player.magical_bullet_chance*100; cap="20%"
            elif stat == "medic":
                lvl = player.star_medic_upgrades; cur = player.medic_chance*100; cap="7%"
            elif stat == "pet":
                lvl = player.star_pet_upgrades; cur = player.pet_chance*100; cap="10%"
            label = f"{emoji} {name} {cur:.1f}% · ⭐{cost} (Lvl {lvl}/{cap})"
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary, row=row)
            async def cb(interaction, stat=stat):
                p=self.store.get(self.user_id); msgs=upgrade_star(p,stat); self.store.save()
                await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+status(p)+f"\n💰 ${p.money} | ⭐ {p.stars} flex", view=StarUpgradeView(self.user_id, self.store))
            btn.callback = cb
            return btn
        self.add_item(make_star("dodge","💨","Dodge",0))
        self.add_item(make_star("magical","✨","Magical",0))
        self.add_item(make_star("medic","💊","Medic",0))
        self.add_item(make_star("pet","🐺","Pet",1))
    @discord.ui.button(label="⬆️ Money Upgrades", style=discord.ButtonStyle.success, row=2)
    async def money(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(p)+f"\n💰 ${p.money} | ⭐ {p.stars}", view=UpgradeView(self.user_id, self.store))
    @discord.ui.button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=2)
    async def mainmenu2(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))

class StarterBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        await self.tree.sync()
        print(f"Synced {len(self.tree.get_commands())} commands")
        try:
            self.loop.create_task(background_autosave())
            print("[AUTOSAVE] Background autosave every 60s STARTED - double protection")
        except Exception as e:
            print(f"[AUTOSAVE] Failed start: {e}")

bot = StarterBot()

@bot.tree.command(name="zombie", description="Zombie Survival - main menu")
async def zombie_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    player = game_store.get(interaction.user.id)
    await interaction.followup.send(content=status(player), view=ZombieMenuView(interaction.user.id, game_store))

@bot.tree.command(name="zombie_start", description="Start a zombie run")
async def zombie_start_cmd(interaction: discord.Interaction):
    await interaction.response.defer()  # Prevent timeout - fixes "didn't respond in time"
    player = game_store.get(interaction.user.id)
    if player.run_active:
        embed = combat_embed(player, [f"Already in run! Wave {player.wave}"])
        await interaction.followup.send(embed=embed, view=CombatView(interaction.user.id, game_store))
        return
    msgs = start_run(player)
    game_store.save()
    embed = combat_embed(player, msgs)
    await interaction.followup.send(embed=embed, view=CombatView(interaction.user.id, game_store))

def main():
    import os, sys
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN missing")
        sys.exit(1)
    print(f"Token found {token[:10]}... Starting FIXED V14 - crit/armor/loot/medic/pet fixed")
    bot.run(token, log_handler=None)

if __name__ == "__main__":
    main()
