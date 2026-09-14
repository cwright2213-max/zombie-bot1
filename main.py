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
    "Bleed": {"unlock_level": 10, "price": 200, "desc": "25% bleed 8 dmg x3", "effect": "bleed", "cost_per_attack": 2, "box_price": 100, "box_amount": 24},
    "Incendiary": {"unlock_level": 35, "price": 600, "desc": "30% burn 12 dmg x2", "effect": "burn", "cost_per_attack": 3, "box_price": 200, "box_amount": 24},
    "Frostbite": {"unlock_level": 70, "price": 1200, "desc": "20% halve dmg x3", "effect": "freeze", "cost_per_attack": 4, "box_price": 200, "box_amount": 24},
    "Toxic": {"unlock_level": 110, "price": 2500, "desc": "35% poison 10 dmg x4", "effect": "poison", "cost_per_attack": 5, "box_price": 300, "box_amount": 24},
    "Shock": {"unlock_level": 160, "price": 5000, "desc": "15% stun 1 turn", "effect": "shock", "cost_per_attack": 6, "box_price": 375, "box_amount": 24},
}
WEAPONS: dict[str, dict[str, Any]] = {
    "Pistol": {"damage": 20, "mag": 12, "price": 0, "unlock_level": 1, "shots": 1},
    "Shotgun": {"damage": 45, "mag": 6, "price": 250, "unlock_level": 15, "shots": 1},
    "Rifle": {"damage": 25, "mag": 30, "price": 2500, "unlock_level": 30, "shots": 2},
    "SMG": {"damage": 15, "mag": 42, "price": 4000, "unlock_level": 60, "shots": 3},
    "Sawed-Off": {"damage": 70, "mag": 2, "price": 6000, "unlock_level": 90, "shots": 1},
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
    star_medic_upgrades: int = 0; star_pet_upgrades: int = 0; star_xp_upgrades: int = 0
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
    @property
    def xp_bonus(self) -> float:
        if self.star_xp_upgrades <= 0:
            return 0.0
        bonus = 0.10 + (self.star_xp_upgrades - 1) * 0.01
        return min(bonus, 0.25)
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
        if "star_xp_upgrades" not in data:
            data["star_xp_upgrades"] = 0
        if "star_pet_upgrades" not in data:
            data["star_pet_upgrades"] = data.get("star_hunter_upgrades", 0)

        # Ensure new fields exist
        for f in ["star_dodge_upgrades", "star_magical_upgrades", "star_medic_upgrades", "star_pet_upgrades", "star_xp_upgrades"]:
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
class GameStore:
    def __init__(self) -> None:
        self.players: dict[str, Survivor] = {}
        self.load()
    def get(self, user_id: int) -> Survivor:
        key = str(user_id)
        if key not in self.players:
            self.players[key] = Survivor()
            self.save_one(key)
        return self.players[key]
    def save_one(self, key: str) -> None:
        p = self.players.get(key)
        if p:
            save_player(key, p.to_dict())
    def save(self) -> None:
        for k, p in self.players.items():
            save_player(k, p.to_dict())
    def load(self) -> None:
        raw = load_all_players()
        loaded = {}
        for k, v in raw.items():
            try:
                if isinstance(v, dict):
                    loaded[k] = Survivor.from_dict(v)
            except Exception as e:
                logging.getLogger("zombie.storage").error(f"Corrupt player {k} quarantined: {e}")
                continue
        self.players = loaded

def zone_for(player: Survivor) -> dict[str, Any]:
    return ZONES.get(player.zone_name, ZONES["Graveyard"])

def ammo_modifier(player: Survivor, ammo_name: str) -> float:
    return float(zone_for(player).get("ammo_mods", {}).get(ammo_name, 1.0))

def ammo_effectiveness_text(player: Survivor) -> str:
    mods = zone_for(player).get("ammo_mods", {})
    strong = [f"{n} 🔥 {int(mods[n]*100)}%" for n, m in mods.items() if m >= 1.25 and n != "Standard"]
    weak = [f"{n} ❄️ {int(mods[n]*100)}%" for n, m in mods.items() if m <= 0.85 and n != "Standard"]
    bonus = ", ".join(strong) if strong else "No major bonus"
    penalty = ", ".join(weak) if weak else "No major penalty"
    return f"**Bonus:** {bonus}\n**Penalty:** {penalty}"

def xp_to_next_level(level: int) -> int:
    # FAST START: levels 1-10 are introduction - smooth and quick
    if level <= 5:
        return 50 + (level - 1) * 15  # 50,65,80,95,110 = 400 total to reach lvl6
    elif level <= 10:
        return 110 + (level - 5) * 20  # 130,150,170,190,210 = 850 more, 1250 total to reach 11
    else:
        # HILL CLIMB: after 10, grind kicks in
        return 200 + (level - 10) * 35 + (level - 1) * 10

def level_for_xp(total_xp: int) -> int:
    level = 1
    earned = max(0, total_xp)
    while earned >= xp_to_next_level(level):
        earned -= xp_to_next_level(level)
        level += 1
    return level

def level_progress(player: Survivor) -> tuple[int, int]:
    earned = max(0, player.xp)
    level = 1
    while earned >= xp_to_next_level(level):
        earned -= xp_to_next_level(level)
        level += 1
    return earned, xp_to_next_level(level)

def spawn_enemy(player: Survivor) -> Enemy:
    zone = zone_for(player)
    name = random.choices(list(ZOMBIES), weights=zone["weights"])[0]
    base = ZOMBIES[name]
    health = int((base["health"] + (player.wave - 1) * 6) * zone["hp_mult"])
    damage = int((base["damage"] + (player.wave - 1) // 2) * zone["dmg_mult"])
    return Enemy(name=name, health=health, max_health=health, damage=damage, money_reward=int(base["money"]*zone["money_mult"]), xp_reward=int(base["xp"]*zone["xp_mult"]))

def start_run(player: Survivor) -> list[str]:
    if player.run_active:
        return ["⚠️ Already in a run!"]
    player.health = player.max_health
    # Allow start with no ammo - player will get overwhelmed message
    if player.get_spare() <= 0 and player.magazine <= 0:
        player.wave = 1; player.zombies_remaining = 3; player.run_active = True; player.enemy = spawn_enemy(player)
        return [f"⚠️ You started with NO {player.ammo_name} ammo! The hoard smells blood...", f"Wave {player.wave}: **{player.enemy.name}** ({player.enemy.health} HP) - you\'re about to get overwhelmed!"]
    if player.magazine == 0:
        spare = player.get_spare()
        if spare > 0:
            load_amt = min(player.magazine_size, spare)
            player.magazine = load_amt
            player.spare_ammo[player.ammo_name] = spare - load_amt
    player.painkillers_used_this_run = 0
    player.full_restores_used_this_run = 0
    player.run_money_earned = 0
    player.run_xp_earned = 0
    player.run_zombies_killed = 0
    player.wave = 1
    player.zombies_remaining = 3
    player.run_active = True
    player.enemy = spawn_enemy(player)
    cost = AMMO[player.ammo_name]["cost_per_attack"]
    return [f"🧟 **Run started in {player.zone_name}** | Using **{player.ammo_name}** ({cost}/shot)", f"Wave {player.wave}: **{player.enemy.name}** ({player.enemy.health} HP)"]

def action_help(player: Survivor) -> str:
    if player.enemy is None:
        return "Choose your next move."
    cost = AMMO[player.ammo_name]["cost_per_attack"]
    return f"🔫 {player.ammo_name} {player.magazine}/{player.magazine_size} ({cost}/shot) | spare: {player.get_spare()} | 🧟 {player.enemy.name} {player.enemy.health} HP"

def _enemy_damage(player: Survivor) -> list[str]:
    enemy = player.enemy
    if enemy is None:
        return []
    if enemy.effects.pop("shock", 0):
        return [f"⚡ **{enemy.name} stunned!** Misses."]
    # DODGE CHECK - star prestige
    if player.dodge_chance > 0 and random.random() < player.dodge_chance:
        return [f"💨 **DODGED!** You evaded {enemy.name}'s attack! ({player.dodge_chance*100:.1f}% chance)"]
    base_dmg = enemy.damage // 2 if enemy.effects.get("freeze", 0) else enemy.damage
    damage = max(1, base_dmg - player.armor_reduction)
    player.health = max(0, player.health - damage)
    if enemy.effects.get("freeze", 0):
        enemy.effects["freeze"] -= 1
        if enemy.effects["freeze"] <= 0:
            del enemy.effects["freeze"]
        result = [f"🧊 Frozen! {enemy.name} hits for {damage} dmg."]
    else:
        result = [f"💥 {enemy.name} hits for {damage} dmg."]
    if player.health == 0:
        player.health = player.max_health
        # CLEAN: only summary, no "Walker hits for X" clutter
        data = build_run_summary(player, "died")
        # build_run_summary now returns dict, convert to pretty list
        if isinstance(data, dict):
            msgs = [
                f"💀 **You died!** {get_cocky_line()}",
                "",
                f"🌊 **Waves survived:** {data['waves_survived']} (reached Wave {data['reached_wave']})",
                f"🧟 **Zombies killed:** {data['zombies_killed']}",
                f"💰 **Money earned:** +${data['money']}",
                f"✨ **XP earned:** +{data['xp']} XP",
                "",
                f"❤️ **HP restored:** {data['max_hp']}/{data['max_hp']}"
            ]
        else:
            msgs = data
        player.run_active = False
        player.enemy = None
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        msgs.extend(_grant_end_of_run_rewards(player))
        return msgs
    return result

def _apply_damage_over_time(player: Survivor) -> list[str]:
    enemy = player.enemy
    if enemy is None:
        return []
    messages: list[str] = []
    for effect in list(enemy.effects):
        if effect in {"bleed", "burn", "poison"}:
            base = {"bleed": 8, "burn": 12, "poison": 10}[effect]
            mod_name = {"bleed": "Bleed", "burn": "Incendiary", "poison": "Toxic"}[effect]
            damage = int(base * ammo_modifier(player, mod_name))
            enemy.health = max(0, enemy.health - damage)
            enemy.effects[effect] -= 1
            messages.append(f"☠️ {effect.title()} {damage} dmg.")
            if enemy.effects[effect] <= 0:
                del enemy.effects[effect]
    return messages

def _finish_enemy(player: Survivor) -> list[str]:
    enemy = player.enemy
    if enemy is None or enemy.health > 0:
        return []
    money_gain = int(enemy.money_reward * player.scavenger_bonus)
    player.money += money_gain
    player.xp += enemy.xp_reward
    player.run_money_earned += money_gain
    player.run_xp_earned += enemy.xp_reward
    player.run_zombies_killed += 1
    player.zombies_remaining -= 1
    messages = [f"✅ **{enemy.name} defeated!** +${enemy.money_reward} • +{enemy.xp_reward} XP"]
    if player.level > level_for_xp(player.xp - enemy.xp_reward):
        ups = player.level - level_for_xp(player.xp - enemy.xp_reward)
        if ups > 0:
            player.stars += ups
            messages.append(f"🎉 **LEVEL UP!** Level {player.level}! +{ups} ⭐")
    if player.zombies_remaining <= 0:
        # MEDIC DROP CHECK - per wave now, not per kill (less OP)
        if player.medic_chance > 0 and random.random() < player.medic_chance:
            if random.random() < 0.5:
                player.painkillers += 2
                messages.append(f"💊 **Medic drop!** +2 painkillers on wave clear! ({player.medic_chance*100:.2f}% chance)")
            else:
                player.full_restores += 1
                messages.append(f"✨ **Medic drop!** +1 full restore on wave clear! ({player.medic_chance*100:.2f}% chance)")
        bonus = int(10 * player.wave * zone_for(player)["money_mult"])
        player.money += bonus
        player.run_money_earned += bonus
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + 5
        player.wave += 1
        player.zombies_remaining = player.wave + 2
        player.health = min(player.max_health, player.health + 5)
        messages.append(f"🌊 **Wave cleared!** +${bonus} • +5 {player.ammo_name} ammo • +5 HP. Wave {player.wave} - {player.zombies_remaining} zombies!")
    player.enemy = spawn_enemy(player)
    messages.append(f"🧟 **{player.enemy.name}** appears! {player.enemy.health} HP")
    return messages

def take_action(player: Survivor, action: str, heal_item: str | None = None) -> list[str]:
    if not player.run_active or player.enemy is None:
        return ["Not in a run. Use Start run."]

    # NEW: Overwhelmed check - if completely out of ammo at start of any action
    def check_overwhelmed():
        if player.magazine <= 0 and player.get_spare() <= 0:
            # die overwhelmed
            player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
            player.magazine = 0
            player.run_active = False
            player.enemy = None
            player.health = player.max_health
            msgs = [
                "💀 **OUT OF AMMO!**",
                f"🧟‍♂️ {get_no_ammo_line()}",
                f"🏃 You limped back to safehouse with ${player.run_money_earned} and {player.run_xp_earned} XP from this run.",
            ]
            msgs.extend(_grant_end_of_run_rewards(player))
            return msgs
        return None

    if action == "heal":
        if heal_item == "full_restore":
            if player.full_restores_used_this_run >= MAX_FULL_RESTORES_PER_RUN:
                return [f"⚠️ Limit: {MAX_FULL_RESTORES_PER_RUN}/run."]
            if player.full_restores <= 0:
                return ["❌ No full restores."]
            if player.health >= player.max_health:
                return ["❤️ Full HP!"]
            # MEDIC STAR CHECK - chance to not consume
            if player.medic_chance > 0 and random.random() < player.medic_chance:
                player.health = player.max_health
                return [f"💊 **MEDIC SAVE!** Full heal kept! ({player.medic_chance*100:.1f}%) {player.max_health} HP", f"{player.full_restores} owned • ✨ Saved!"]
            player.health = player.max_health
            player.full_restores -= 1
            player.full_restores_used_this_run += 1
            left = MAX_FULL_RESTORES_PER_RUN - player.full_restores_used_this_run
            return [f"✨ **Full heal!** {player.max_health} HP", f"{player.full_restores} owned • {left} left"]
        if heal_item == "painkillers":
            if player.painkillers_used_this_run >= MAX_PAINKILLERS_PER_RUN:
                return [f"⚠️ Limit: {MAX_PAINKILLERS_PER_RUN}/run."]
            if player.painkillers <= 0:
                return ["❌ No painkillers."]
            if player.health >= player.max_health:
                return ["❤️ Full HP!"]
            amount = max(1, player.max_health // 4)
            # MEDIC STAR CHECK - chance to not consume
            if player.medic_chance > 0 and random.random() < player.medic_chance:
                player.health = min(player.max_health, player.health + amount)
                return [f"💊 **MEDIC SAVE!** +{amount} HP without using item! ({player.medic_chance*100:.1f}%) Now {player.health}/{player.max_health}", f"{player.painkillers} owned • ✨ Saved!"]
            player.health = min(player.max_health, player.health + amount)
            player.painkillers -= 1
            player.painkillers_used_this_run += 1
            left = MAX_PAINKILLERS_PER_RUN - player.painkillers_used_this_run
            return [f"💊 **+{amount} HP!** Now {player.health}/{player.max_health}", f"{player.painkillers} owned • {left} left"]
        return ["Choose heal item."]
    messages = _apply_damage_over_time(player)
    if player.enemy is None or player.enemy.health <= 0:
        messages.extend(_finish_enemy(player))
        return messages
    enemy = player.enemy
    if action == "attack":
        ammo_data = AMMO[player.ammo_name]
        base_cost = int(ammo_data["cost_per_attack"])
        # NEW: Weapon shots per attack
        weapon_data = WEAPONS.get(player.weapon_name, WEAPONS["Pistol"])
        shots = int(weapon_data.get("shots", 1))
        cost = base_cost * shots

        # NEW: Mag size must support ammo type - e.g. Sawed-Off mag 2 can't use Shock cost 6
        # Check if max magazine size is too small for this ammo type (even with 1 shot)
        if player.magazine_size < base_cost:
            return [f"❌ **{player.weapon_name} mag too small for {player.ammo_name}!**", f"Need mag size {base_cost}, you have {player.magazine_size}. Upgrade mag or use lighter ammo.", f"🔧 {player.weapon_name} {player.magazine}/{player.magazine_size} can't fit {player.ammo_name} ({base_cost}/shot)"]
        if player.magazine_size < cost:
            return [f"❌ **{player.weapon_name} mag too small for {shots}x {player.ammo_name}!**", f"Need mag size {cost} ({base_cost}x{shots} shots), you have {player.magazine_size}. Upgrade mag!", f"🔧 {player.weapon_name} can't do {shots}x {player.ammo_name}"]

        if player.magazine < cost:
            spare = player.get_spare()
            if spare <= 0:
                # OVERWHELMED - no ammo at all
                player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
                player.magazine = 0
                player.run_active = False
                player.enemy = None
                player.health = player.max_health
                return [
                    "💀 **CLICK... CLICK... OUT OF AMMO!**",
                    f"🧟‍♂️ {get_no_ammo_line()}",
                    f"💰 You kept ${player.run_money_earned} • {player.run_xp_earned} XP from this run.",
                ] + _grant_end_of_run_rewards(player)
            return [f"❌ Need {cost} {player.ammo_name} ammo! Have {player.magazine}/{player.magazine_size}", f"🔄 Reload (you have {spare} spare)"]
        # MAGICAL BULLET CHECK - chance to not use ammo
        is_magical = False
        if player.magical_bullet_chance > 0 and random.random() < player.magical_bullet_chance:
            is_magical = True
        else:
            player.magazine -= cost
        
        mod = ammo_modifier(player, player.ammo_name)
        total_dmg = 0
        total_crits = 0
        hit_details = []
        for shot_i in range(shots):
            dmg = int(player.weapon_damage * mod)
            is_crit = random.random() < player.crit_chance
            if is_crit:
                dmg = int(dmg * 2)
                total_crits += 1
            enemy.health = max(0, enemy.health - dmg)
            total_dmg += dmg
            hit_details.append(dmg)
            if enemy.health <= 0:
                break
        mod_txt = f" (Zone {int(mod*100)}%)" if mod != 1.0 else ""
        crit_txt = f" **{total_crits}x CRIT!**" if total_crits > 0 else ""
        magical_txt = " ✨ **MAGICAL! Free shot!**" if is_magical else ""
        if shots > 1:
            messages.append(f"🔫 **{shots}x** {player.weapon_name} Hit **{enemy.name} for {total_dmg}** ({'+'.join(map(str, hit_details))}){crit_txt}{magical_txt} using {player.ammo_name} ({base_cost}x{shots}={cost} ammo){mod_txt}")
        else:
            messages.append(f"🔫 Hit **{enemy.name} for {total_dmg}**{crit_txt}{magical_txt} using {player.ammo_name} ({cost}/shot){mod_txt}")
        
        # PET ATTACK CHECK
        if player.pet_chance > 0 and random.random() < player.pet_chance:
            pet_dmg = player.pet_damage
            enemy.health = max(0, enemy.health - pet_dmg)
            messages.append(f"🐺 **Wolf bites {enemy.name} for {pet_dmg} dmg!** ({player.pet_chance*100:.0f}% chance)")
        effect = ammo_data["effect"]
        chances = {"bleed": 0.25, "burn": 0.30, "freeze": 0.20, "poison": 0.35, "shock": 0.15}
        if effect and random.random() < chances[effect]:
            durations = {"bleed": 3, "burn": 2, "freeze": 3, "poison": 4, "shock": 1}
            enemy.effects[effect] = durations[effect]
            messages.append(f"💥 {player.ammo_name} procs **{effect}**!")
    elif action == "reload":
        if player.magazine == player.magazine_size:
            return ["✅ Mag full!"]
        spare = player.get_spare()
        if spare <= 0:
            # OVERWHELMED on reload attempt with no spare
            player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
            player.magazine = 0
            player.run_active = False
            player.enemy = None
            player.health = player.max_health
            return [
                "💀 **No spare ammo left!**",
                f"🧟‍♂️ {get_no_ammo_line()}",
                f"💰 You escaped with ${player.run_money_earned} • {player.run_xp_earned} XP.",
            ] + _grant_end_of_run_rewards(player)
        amount = min(player.magazine_size - player.magazine, spare)
        player.magazine += amount
        player.spare_ammo[player.ammo_name] = spare - amount
        messages.append(f"🔄 Reloaded {amount} {player.ammo_name}. {player.spare_ammo[player.ammo_name]} spare left.")
    elif action == "flee":
        # USER WANTS: flee still rewards players + full heal
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        player.run_active = False
        player.enemy = None
        player.health = player.max_health
        messages.append(f"🏃 You fled like a legend! Kept ${player.run_money_earned} • {player.run_xp_earned} XP this run. Full healed!")
        messages.extend(_grant_end_of_run_rewards(player))
        return messages
    else:
        return ["Attack, reload, heal, or flee."]
    if enemy.health <= 0:
        messages.extend(_finish_enemy(player))
    else:
        messages.extend(_enemy_damage(player))
    return messages

def buy_item(player: Survivor, item: str) -> list[str]:
    if player.run_active:
        return ["⚠️ Can't shop in a run! Flee first."]
    if item == "ammo":
        ammo_type = player.ammo_name
        box_price = AMMO[ammo_type]["box_price"]
        box_amount = AMMO[ammo_type]["box_amount"]
        if player.money < box_price:
            return [f"❌ Need ${box_price} for {ammo_type} box, you have ${player.money}"]
        player.money -= box_price
        player.spare_ammo[ammo_type] = player.spare_ammo.get(ammo_type, 0) + box_amount
        return [f"📦 Bought {ammo_type} box +{box_amount}. {player.spare_ammo[ammo_type]} spare now. ${player.money} left."]
    if item == "painkillers":
        if player.money < 15:
            return [f"❌ Need $15, you have ${player.money}"]
        player.money -= 15
        player.painkillers += 2
        return [f"💊 Bought painkillers +2. ${player.money} left."]
    if item == "full_restore":
        if player.money < 80:
            return [f"❌ Need $80, you have ${player.money}"]
        player.money -= 80
        player.full_restores += 1
        return [f"✨ Bought full restore +1. ${player.money} left."]
    if item not in WEAPONS:
        return ["Item doesn't exist."]
    weapon = WEAPONS[item]
    if player.level < weapon["unlock_level"]:
        return [f"{item} unlocks at level {weapon['unlock_level']}."]
    if item in player.owned_weapons:
        player.weapon_name = item
        player.recalc_stats()
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        return [f"🔫 Re-equipped **{item}** for free (+{player.damage_upgrades*3} dmg from upgrades)."]
    if player.money < weapon["price"]:
        return [f"Need ${weapon['price']} for {item}, you have ${player.money}"]
    player.money -= weapon["price"]
    player.weapon_name = item
    player.recalc_stats()
    if item not in player.owned_weapons:
        player.owned_weapons.append(item)
    player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
    player.magazine = 0
    return [f"🔫 Equipped **{item}** (+{player.damage_upgrades*3} dmg from upgrades). ${player.money} left."]

def equip_ammo(player: Survivor, ammo_name: str) -> list[str]:
    if ammo_name not in AMMO:
        return ["That ammo doesn't exist."]
    if ammo_name not in player.owned_ammo:
        ammo = AMMO[ammo_name]
        if player.level < ammo["unlock_level"]:
            return [f"{ammo_name} unlocks at level {ammo['unlock_level']}."]
        if player.money < ammo["price"]:
            return [f"Need ${ammo['price']} for {ammo_name}, you have ${player.money}"]
        player.money -= ammo["price"]
        player.owned_ammo.append(ammo_name)
        player.spare_ammo[ammo_name] = player.spare_ammo.get(ammo_name, 0) + 12
    if player.ammo_name != ammo_name:
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        player.ammo_name = ammo_name
        spare = player.get_spare(ammo_name)
        if spare > 0:
            load = min(player.magazine_size, spare)
            player.magazine = load
            player.spare_ammo[ammo_name] = spare - load
            return [f"🔬 Equipped **{ammo_name}** ({AMMO[ammo_name]['cost_per_attack']}/shot) and loaded {load} rounds. ${player.money} left."]
        else:
            return [f"🔬 Equipped **{ammo_name}** ({AMMO[ammo_name]['cost_per_attack']}/shot) - no spare, buy ammo box!"]
    else:
        return [f"🔬 Already using **{ammo_name}** ({AMMO[ammo_name]['cost_per_attack']}/shot)."]

def change_zone(player: Survivor, zone_name: str) -> list[str]:
    if player.run_active:
        return ["Can't change zones in a run!"]
    if zone_name not in ZONES:
        return ["Zone doesn't exist."]
    if player.level < ZONES[zone_name]["min_level"]:
        return [f"{zone_name} unlocks at level {ZONES[zone_name]['min_level']}."]
    player.zone_name = zone_name
    return [f"🗺️ Travelled to **{zone_name}**.", ammo_effectiveness_text(player)]

def get_upgrade_cost(player: Survivor, stat: str) -> int:
    """Balanced exponential scaling costs"""
    stat = stat.lower()
    # Base costs
    bases = {
        "damage": 250,
        "health": 200,
        "mag": 400,
        "crit": 500,
        "armor": 450,
        "scavenger": 700,
    }
    # Multipliers per level (how fast it gets expensive)
    mults = {
        "damage": 1.35,
        "health": 1.30,
        "mag": 1.45,
        "crit": 1.50,
        "armor": 1.40,
        "scavenger": 1.60,
    }
    if stat not in bases:
        return 999999
    count = 0
    if stat == "damage": count = player.damage_upgrades
    elif stat == "health": count = player.health_upgrades
    elif stat == "mag": count = player.mag_upgrades
    elif stat == "crit": count = player.crit_upgrades
    elif stat == "armor": count = player.armor_upgrades
    elif stat == "scavenger": count = player.scavenger_upgrades
    # cost = base * mult^count
    return int(bases[stat] * (mults[stat] ** count))



def upgrade(player: Survivor, stat: str) -> list[str]:
    """Money upgrades: health, damage, mag, crit, armor, scavenger"""
    if player.run_active:
        return ["⚠️ Can't upgrade during a run! Flee first."]
    stat = stat.lower().strip()
    # Map aliases
    alias = {
        "health": "health", "hp": "health", "max_health": "health",
        "damage": "damage", "dmg": "damage", "weapon": "damage",
        "mag": "mag", "magazine": "mag", "ammo": "mag",
        "crit": "crit", "critical": "crit", "crit_chance": "crit",
        "armor": "armor", "armour": "armor", "defense": "armor",
        "scavenger": "scavenger", "loot": "scavenger", "money": "scavenger"
    }
    canonical = alias.get(stat, stat)
    cost = get_upgrade_cost(player, canonical)
    if player.money < cost:
        return [f"❌ Need ${cost} for {canonical}, you have ${player.money}"]
    player.money -= cost
    if canonical == "health":
        player.max_health += 20
        player.health_upgrades += 1
        player.health = player.max_health
        return [f"❤️ Max HP → **{player.max_health}** (+20). ${player.money} left. Lvl {player.health_upgrades}"]
    elif canonical == "damage":
        player.weapon_damage += 3
        player.damage_upgrades += 1
        return [f"💥 Damage → **{player.weapon_damage}** (+3). ${player.money} left. Lvl {player.damage_upgrades}"]
    elif canonical == "mag":
        player.magazine_size += 1
        player.mag_upgrades += 1
        return [f"📦 Mag size → **{player.magazine_size}** (+1). ${player.money} left. Lvl {player.mag_upgrades}"]
    elif canonical == "crit":
        player.crit_upgrades += 1
        return [f"🎯 Crit chance → **{int(player.crit_chance*100)}%** (+2% first, +0.5% after). ${player.money} left. Lvl {player.crit_upgrades}"]
    elif canonical == "armor":
        player.armor_upgrades += 1
        return [f"🛡️ Armor → **-{player.armor_reduction} dmg** (cap -35). ${player.money} left. Lvl {player.armor_upgrades}"]
    elif canonical == "scavenger":
        player.scavenger_upgrades += 1
        return [f"💰 Loot bonus → **+{int((player.scavenger_bonus-1)*100)}%** (+5% per lvl). ${player.money} left. Lvl {player.scavenger_upgrades}"]
    else:
        # Refund if unknown
        player.money += cost
        return [f"❓ Unknown upgrade '{stat}'. Try: health, damage, mag, crit, armor, scavenger"]



def get_star_upgrade_cost(player: Survivor, stat: str) -> int:
    """All star upgrades: 5 to unlock, 3 per level after"""
    stat = stat.lower().strip()
    alias = {
        "dodge": "dodge", "dodge_chance": "dodge", "evade": "dodge",
        "magical": "magical", "magical_bullet": "magical", "magic": "magical", "bullet": "magical", "ammo_saver": "magical",
        "medic": "medic", "medic_drop": "medic", "heal_drop": "medic",
        "pet": "pet", "pet_attack": "pet", "wolf": "pet", "dog": "pet",
        "xp": "xp", "xp_gain": "xp", "experience": "xp", "exp": "xp",
    }
    canonical = alias.get(stat, stat)
    lvl = 0
    if canonical == "dodge":
        lvl = player.star_dodge_upgrades
    elif canonical == "magical":
        lvl = player.star_magical_upgrades
    elif canonical == "medic":
        lvl = player.star_medic_upgrades
    elif canonical == "pet":
        lvl = player.star_pet_upgrades
    elif canonical == "xp":
        lvl = player.star_xp_upgrades
    if lvl == 0:
        return 5
    return 3



def upgrade_star(player: Survivor, stat: str) -> list[str]:
    if player.run_active:
        return ["Can't upgrade during a run!"]
    stat = stat.lower().strip()
    alias = {
        "dodge": "dodge", "dodge_chance": "dodge", "evade": "dodge",
        "magical": "magical", "magical_bullet": "magical", "magic": "magical", "bullet": "magical", "ammo_saver": "magical",
        "medic": "medic", "medic_drop": "medic", "heal_drop": "medic",
        "pet": "pet", "pet_attack": "pet", "wolf": "pet", "dog": "pet",
        "xp": "xp", "xp_gain": "xp", "experience": "xp", "exp": "xp",
    }
    canonical = alias.get(stat)
    if not canonical:
        return [f"Unknown star upgrade '{stat}'. Options: dodge(⭐{get_star_upgrade_cost(player,'dodge')}) / magical(⭐{get_star_upgrade_cost(player,'magical')}) / medic(⭐{get_star_upgrade_cost(player,'medic')}) / pet(⭐{get_star_upgrade_cost(player,'pet')}) | ⭐ {player.stars} stars"]

    cost = get_star_upgrade_cost(player, canonical)
    if player.stars < cost:
        return [f"Need ⭐{cost} for {canonical}, you have ⭐{player.stars}. Keep grinding waves!"]

    # Check caps before purchase
    if canonical == "dodge":
        if player.star_dodge_upgrades > 0 and player.dodge_chance >= 0.30:
            return [f"❌ Dodge already maxed at 30%! (Lvl {player.star_dodge_upgrades})"]
        player.stars -= cost
        player.star_dodge_upgrades += 1
        return [f"💨 Dodge → **{player.dodge_chance*100:.1f}%** dodge chance (Lvl {player.star_dodge_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | Next: ⭐{get_star_upgrade_cost(player,'dodge')} (cap 30%)"]
    if canonical == "magical":
        if player.star_magical_upgrades > 0 and player.magical_bullet_chance >= 0.20:
            return [f"❌ Magical Bullet already maxed at 20%! (Lvl {player.star_magical_upgrades})"]
        player.stars -= cost
        player.star_magical_upgrades += 1
        return [f"✨ Magical Bullet → **{player.magical_bullet_chance*100:.1f}%** free shot (Lvl {player.star_magical_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | Next: ⭐{get_star_upgrade_cost(player,'magical')} (cap 20%)"]
    if canonical == "medic":
        if player.star_medic_upgrades > 0 and player.medic_chance >= 0.07:
            return [f"❌ Medic already maxed at 7%! (Lvl {player.star_medic_upgrades})"]
        player.stars -= cost
        player.star_medic_upgrades += 1
        return [f"💊 Medic → **{player.medic_chance*100:.2f}%** heal drop (Lvl {player.star_medic_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | Next: ⭐{get_star_upgrade_cost(player,'medic')} (cap 7%)"]
    if canonical == "pet":
        if player.star_pet_upgrades > 0 and player.pet_chance >= 0.10:
            return [f"❌ Pet already maxed at 10%! (Lvl {player.star_pet_upgrades})"]
        player.stars -= cost
        player.star_pet_upgrades += 1
        return [f"🐺 Wolf Pet → **{player.pet_chance*100:.0f}%** to deal {player.pet_damage} dmg (Lvl {player.star_pet_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | Next: ⭐{get_star_upgrade_cost(player,'pet')} (cap 10%)"]

    if canonical == "xp":
        if player.star_xp_upgrades > 0 and player.xp_bonus >= 0.25:
            return [f"❌ XP Gain already maxed at 25%! (Lvl {player.star_xp_upgrades})"]
        player.stars -= cost
        player.star_xp_upgrades += 1
        return [f"✨ XP Gain → **{player.xp_bonus*100:.1f}%** bonus XP (Lvl {player.star_xp_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | Next: ⭐{get_star_upgrade_cost(player,'xp')} (cap 25%)"]

    return ["Unknown error"]



def _grant_star_drop(player: Survivor) -> list[str]:
    # Apply hunter bonus - increases chance of 1-3 stars
    """RARE star drop: 0-2 stars normally, 3 stars ONLY after wave 20+"""
    wave = max(1, player.wave)
    
    # 3 stars impossible before wave 20
    if wave < 20:
        if wave <= 2:
            weights = [92, 8, 0, 0]   # 0,1,2,3 - no 2 or 3
        elif wave <= 5:
            weights = [80, 16, 4, 0]  # no 3
        elif wave <= 9:
            weights = [65, 25, 10, 0] # no 3
        elif wave <= 14:
            weights = [50, 32, 18, 0] # no 3
        else:  # 15-19 - best before mythic
            weights = [40, 35, 25, 0] # still no 3, but good 2-star chance
    else:
        # Wave 20+ - MYTHIC unlocked
        weights = [35, 33, 24, 8]  # 8% chance for 3 stars, 32% for 1-2
    
    import random
    r = random.random() * 100
    cumulative = 0
    stars = 0
    for i, w in enumerate(weights):
        cumulative += w
        if r <= cumulative:
            stars = i
            break
    
    if stars > 0:
        player.stars += stars
        if stars == 1:
            return [f"⭐ **RARE!** +{stars} star found! (Wave {wave})"]
        elif stars == 2:
            return [f"⭐⭐ **ULTRA RARE!** +{stars} stars! (Wave {wave})"]
        else:  # 3 stars - wave 20+ only
            return [f"⭐⭐⭐ **MYTHIC HAUL!** +{stars} STARS! WAVE {wave} LEGEND! First time ever?"]
    else:
        return []


def build_run_summary(player: Survivor, cause: str) -> list[str]:
    waves_survived = player.wave if cause != "died" else max(0, player.wave - 1 if player.zombies_remaining>0 else player.wave)
    if player.run_zombies_killed==0 and player.wave==1:
        waves_survived=0
    lines=[]
    if cause=="died":
        lines.append(f"💀 **You died!** {get_cocky_line()}")
    elif cause=="fled":
        lines.append(f"🏃 **You escaped alive!**")
    else:
        lines.append(f"💀 **Out of ammo!** {get_no_ammo_line()}")
    lines.append("")
    lines.append(f"🌊 Waves survived: {waves_survived} (reached Wave {player.wave})")
    lines.append(f"🧟 Zombies killed: {player.run_zombies_killed}")
    lines.append(f"💰 Money earned: +${player.run_money_earned}")
    lines.append(f"✨ XP earned: +{player.run_xp_earned} XP")
    lines.append("")
    lines.append(f"❤️ HP restored: {player.max_health}/{player.max_health}")
    return lines

def _grant_end_of_run_rewards(player: Survivor) -> list[str]:
    msgs = []
    msgs.extend(_grant_random_elemental_drop(player))
    msgs.extend(_grant_star_drop(player))
    return msgs

def _grant_random_elemental_drop(player: Survivor) -> list[str]:
    elemental_owned = [a for a in player.owned_ammo if a != "Standard"]
    if not elemental_owned:
        return []
    chosen = random.choice(elemental_owned)
    normal_amount = random.randint(1, 10)
    player.spare_ammo[chosen] = player.spare_ammo.get(chosen, 0) + 1
    player.spare_ammo["Standard"] = player.spare_ammo.get("Standard", 0) + normal_amount
    return [f"🎁 **Scavenged!** +1x **{chosen}** bullet + {normal_amount}x Standard bullets found!"]


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
    def __init__(self):
        self.players = {}
        self.load()
    def get(self, user_id: int):
        key = str(user_id)
        if key not in self.players:
            self.players[key] = Survivor()
            self.save_one(key)
        return self.players[key]
    def save_one(self, key: str):
        p = self.players.get(key)
        if p:
            try:
                save_player(key, p.to_dict())
            except:
                save_player(key, asdict(p))
    def save(self):
        for k, p in self.players.items():
            try:
                save_player(k, p.to_dict())
            except:
                save_player(k, asdict(p))
    def load(self):
        raw = load_all_players()
        loaded = {}
        for k, v in raw.items():
            try:
                if isinstance(v, dict):
                    loaded[k] = Survivor.from_dict(v)
            except Exception as e:
                print(f"Corrupt {k}: {e}")
                continue
        self.players = loaded

game_store = GameStore()

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
    def __init__(self, user_id: int, store):
        super().__init__(user_id, store)
        player = self.store.get(user_id)
        
        # Dynamic Start/Continue button
        is_active = getattr(player, 'run_active', False) and player.enemy is not None
        if is_active:
            label = f"▶️ Continue Run (W{player.wave})"
            style = discord.ButtonStyle.success
            emoji_text = f"Wave {player.wave} - {player.zombies_remaining} left"
        else:
            label = "▶️ Start Run"
            style = discord.ButtonStyle.success

        # --- ROW 0: Main actions ---
        btn_start = discord.ui.Button(label=label, style=style, row=0)
        async def start_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            # RESUME LOGIC - if already in run, go back to combat (boss caught you at work mode)
            if p.run_active and p.enemy:
                embed = combat_embed(p, [f"🔄 Resumed your run! Wave {p.wave} | {p.zombies_remaining} zombies left"])
                await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store))
                return
            # Otherwise start fresh run
            msgs = start_run(p)
            self.store.save()
            # Show combat immediately
            embed = combat_embed(p, msgs)
            await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store))
        btn_start.callback = start_cb
        self.add_item(btn_start)

        btn_shop = discord.ui.Button(label="🛒 Shop", style=discord.ButtonStyle.primary, row=0)
        async def shop_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ShopView(self.user_id, self.store))
        btn_shop.callback = shop_cb
        self.add_item(btn_shop)

        # --- ROW 1: Progression ---
        btn_zones = discord.ui.Button(label="🗺️ Zones", style=discord.ButtonStyle.secondary, row=1)
        async def zones_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ZoneView(self.user_id, self.store))
        btn_zones.callback = zones_cb
        self.add_item(btn_zones)

        btn_ammo = discord.ui.Button(label="🧪 Ammo Lab", style=discord.ButtonStyle.secondary, row=1)
        async def ammo_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=AmmoView(self.user_id, self.store))
        btn_ammo.callback = ammo_cb
        self.add_item(btn_ammo)

        btn_up = discord.ui.Button(label="⬆️ Upgrades", style=discord.ButtonStyle.secondary, row=1)
        async def up_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            await interaction.response.edit_message(content=status(p) + chr(10) + f"💰 ${p.money} | ⭐ {p.stars} flex", embed=None, view=UpgradeView(self.user_id, self.store))
        btn_up.callback = up_cb
        self.add_item(btn_up)

        # --- ROW 2: Utility ---
        btn_refresh = discord.ui.Button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=2)
        async def refresh_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ZombieMenuView(self.user_id, self.store))
        btn_refresh.callback = refresh_cb
        self.add_item(btn_refresh)





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
        for i, wname in enumerate(["Shotgun", "Rifle", "SMG", "Sawed-Off"]):
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
                    await interaction.response.edit_message(content=chr(10).join(msgs)+chr(10)+chr(10)+status(p), view=ShopView(self.user_id, self.store))
                btn.callback = cb
                self.add_item(btn)

    @discord.ui.button(label="📦 Ammo box", style=discord.ButtonStyle.primary, row=2)
    async def ammo(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        cur_ammo = p.ammo_name
        cur_data = AMMO.get(cur_ammo, AMMO["Standard"])
        box_price = cur_data["box_price"]
        box_amount = cur_data["box_amount"]
        msgs=buy_item(p,"ammo")
        self.store.save()
        new_spare = p.spare_ammo.get(cur_ammo, 0)
        lines = []
        lines.extend(msgs)
        lines.append("")
        lines.append(f"Bought {cur_ammo} crate: ${box_price} for {box_amount} rounds | Now {new_spare} spare")
        lines.append("")
        lines.append(status(p))
        await interaction.response.edit_message(content=chr(10).join(lines), view=ShopView(self.user_id, self.store))

    @discord.ui.button(label="💊 Painkillers $15", style=discord.ButtonStyle.success, row=2)
    async def pk(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        msgs=buy_item(p,"painkillers")
        self.store.save()
        await interaction.response.edit_message(content=chr(10).join(msgs)+chr(10)+chr(10)+status(p), view=ShopView(self.user_id, self.store))

    @discord.ui.button(label="✨ Full restore $80", style=discord.ButtonStyle.success, row=2)
    async def fr(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        msgs=buy_item(p,"full_restore")
        self.store.save()
        await interaction.response.edit_message(content=chr(10).join(msgs)+chr(10)+chr(10)+status(p), view=ShopView(self.user_id, self.store))

    @discord.ui.button(label="🧪 Ammo prices", style=discord.ButtonStyle.primary, row=3)
    async def ammo_prices(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        lines = ["** Ammo Crate Costs: **"]
        for aname, adata in AMMO.items():
            lines.append(f"{aname}: ${adata['box_price']} for {adata['box_amount']} rounds ({adata['cost_per_attack']}/shot) - {adata['desc']}")
        lines.append("")
        lines.append(status(p))
        await interaction.response.edit_message(content=chr(10).join(lines), view=ShopView(self.user_id, self.store))

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
            cost_per = ammo["cost_per_attack"]
            is_equipped = player.ammo_name == ammo_name
            owned = ammo_name in player.owned_ammo
            if is_equipped:
                label = f"EQ {ammo_name} {cost_per}/shot"
                style = discord.ButtonStyle.success
            elif owned:
                label = f"OWNED {ammo_name} {cost_per}/shot"
                style = discord.ButtonStyle.primary
            else:
                label = f"LOCKED {ammo_name} {cost_per}/shot ${ammo['price']} Lvl{ammo['unlock_level']}"
                style = discord.ButtonStyle.secondary
            btn = discord.ui.Button(label=label[:80], style=style, row=i)
            async def cb(interaction, an=ammo_name):
                p=self.store.get(self.user_id)
                msgs=equip_ammo(p,an)
                self.store.save()
                info = AMMO[an]
                spare = p.spare_ammo.get(an, 0)
                lines = []
                lines.extend(msgs)
                lines.append("")
                lines.append(f"AMMO {an} FULL DETAILS")
                lines.append(f"Perk: {info['desc']}")
                lines.append(f"Cost per attack: {info['cost_per_attack']}")
                lines.append(f"Box price: ${info['box_price']} for {info['box_amount']} rounds")
                lines.append(f"Unlock: ${info['price']} at Level {info['unlock_level']}")
                lines.append(f"Spare: {spare}")
                if p.ammo_name == an:
                    lines.append("Equipped now!")
                lines.append("")
                lines.append(status(p))
                await interaction.response.edit_message(content=chr(10).join(lines), view=AmmoView(self.user_id, self.store))
            btn.callback = cb
            self.add_item(btn)
        cur = player.ammo_name
        cur_data = AMMO.get(cur, AMMO["Standard"])
        buy_label = f"Buy {cur} Box ${cur_data['box_price']} - {cur_data['box_amount']} rnds"
        btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.primary, row=6)
        async def buy_cb(interaction: discord.Interaction):
            p=self.store.get(self.user_id)
            cur_name = p.ammo_name
            cur_d = AMMO.get(cur_name, AMMO["Standard"])
            price = cur_d["box_price"]
            amount = cur_d["box_amount"]
            msgs=buy_item(p,"ammo")
            self.store.save()
            new_spare = p.spare_ammo.get(cur_name, 0)
            lines = []
            lines.extend(msgs)
            lines.append("")
            lines.append(f"Bought {cur_name} box ${price} for {amount} rounds Now {new_spare} spare")
            lines.append("")
            lines.append(status(p))
            await interaction.response.edit_message(content=chr(10).join(lines), view=AmmoView(self.user_id, self.store))
        btn_buy.callback = buy_cb
        self.add_item(btn_buy)
        btn_main = discord.ui.Button(label="Main menu", style=discord.ButtonStyle.secondary, row=6)
        async def main_cb(interaction: discord.Interaction):
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), embed=None, view=ZombieMenuView(self.user_id, self.store))
        btn_main.callback = main_cb
        self.add_item(btn_main)



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
            elif stat == "xp":
                lvl = player.star_xp_upgrades; cur = player.xp_bonus*100; cap="25%"
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
        self.add_item(make_star("xp","✨","XP Gain",1))
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

# --- ADMIN COMMANDS - ANY SERVER ADMIN CAN USE ---
def is_server_admin(interaction: discord.Interaction) -> bool:
    # DM check - no guild = not admin
    if interaction.guild is None:
        return False
    # Check if user has Administrator permission in this server
    try:
        perms = interaction.user.guild_permissions
        if perms.administrator:
            return True
        # Also allow Manage Guild as admin fallback
        if perms.manage_guild:
            return True
    except:
        pass
    return False

@bot.tree.command(name="addmoney", description="[ADMIN] Add money to a player")
@app_commands.describe(user="Player to give money to (leave empty for yourself)", amount="Amount to add (e.g. 5000)")
async def addmoney(interaction: discord.Interaction, amount: int, user: discord.User = None):
    if not is_server_admin(interaction):
        await interaction.response.send_message("❌ You need **Administrator** permission in this server to use this.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    target = user or interaction.user
    player = game_store.get(target.id)
    player.money += amount
    game_store.save()
    await interaction.followup.send(f"💰 **+${amount}** added to {target.mention} → Now has **${player.money}**", ephemeral=True)

@bot.tree.command(name="addstars", description="[ADMIN] Add stars to a player")
@app_commands.describe(user="Player to give stars to", amount="Amount to add")
async def addstars(interaction: discord.Interaction, amount: int, user: discord.User = None):
    if not is_server_admin(interaction):
        await interaction.response.send_message("❌ You need **Administrator** permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    target = user or interaction.user
    player = game_store.get(target.id)
    player.stars += amount
    game_store.save()
    await interaction.followup.send(f"⭐ **+{amount} stars** to {target.mention} → Now has **{player.stars}** ⭐", ephemeral=True)

@bot.tree.command(name="addxp", description="[ADMIN] Add XP to a player")
@app_commands.describe(user="Player to give XP to", amount="Amount to add")
async def addxp(interaction: discord.Interaction, amount: int, user: discord.User = None):
    if not is_server_admin(interaction):
        await interaction.response.send_message("❌ You need **Administrator** permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    target = user or interaction.user
    player = game_store.get(target.id)
    player.xp += amount
    # Recalc level based on xp (if your Survivor has level property auto)
    game_store.save()
    await interaction.followup.send(f"✨ **+{amount} XP** to {target.mention} → Level {player.level} | XP: {player.xp}", ephemeral=True)

@bot.tree.command(name="resetplayer", description="[ADMIN] Reset a player's progress")
@app_commands.describe(user="Player to reset")
async def resetplayer(interaction: discord.Interaction, user: discord.User):
    if not is_server_admin(interaction):
        await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    # Create fresh survivor
    from dataclasses import replace
    fresh = game_store.get(user.id)
    # Reset to defaults - we will create new Survivor instance
    new_player = fresh.__class__()  # fresh Survivor
    # Preserve user id via store logic
    game_store.players[str(user.id)] = new_player
    game_store.save()
    await interaction.followup.send(f"🔄 {user.mention} has been reset to level 1!", ephemeral=True)

@bot.tree.command(name="zombie_give", description="[ADMIN] Give money/stars/xp to restore a player")
@app_commands.describe(user="Player to restore", money="Money to give", stars="Stars to give", xp="XP to give")
async def zombie_give(interaction: discord.Interaction, user: discord.User, money: int = 0, stars: int = 0, xp: int = 0):
    if not is_server_admin(interaction):
        await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    player = game_store.get(user.id)
    player.money += money
    player.stars += stars
    player.xp += xp
    game_store.save()
    await interaction.followup.send(f"✅ Restored {user.mention}: +${money}, +{stars}⭐, +{xp} XP\nNow: ${player.money} | {player.stars}⭐ | Lvl {player.level} ({player.xp} XP)", ephemeral=True)

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
