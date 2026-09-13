"""Monolithic zombie bot - single file, no bot/ folder needed - FIXES ModuleNotFoundError"""
import os, sys, json, random, logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone

import discord
from discord import app_commands

# === STORAGE (from storage.py) ===
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

def load_all_players() -> Dict[str, Any]:
    try:
        conn = _get_conn()
        cur = conn.execute("SELECT user_id, data FROM players")
        result = {}
        for uid, jdata in cur.fetchall():
            try:
                result[uid] = json.loads(jdata)
            except:
                logging.warning(f"Corrupt data for {uid}")
        conn.close()
        print(f"[STORAGE] Loaded {len(result)} players from {DB_PATH}")
        return result
    except Exception as e:
        print(f"[STORAGE] Load failed: {e}")
        return {}

def save_player(user_id: str, player_dict: dict):
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO players (user_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (str(user_id), json.dumps(player_dict))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[STORAGE] Save failed: {e}")

SAVE_FILE = DB_PATH


# === ZOMBIE SURVIVAL - RESTORED ===
"""Turn-based Discord zombie survival - FIXED H-01 profiles never silently lost"""
import json, random, logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
try:
    from .storage import load_all_players, save_player, DB_PATH
except ImportError:
    try:
        from storage import load_all_players, save_player, DB_PATH
    except ImportError:
        from bot.storage import load_all_players, save_player, DB_PATH
SAVE_FILE = DB_PATH
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
    run_money_earned: int = 0; run_xp_earned: int = 0; zone_name: str = "Graveyard"; ammo_name: str = "Standard"
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
        player.run_active = False
        player.enemy = None
        player.health = player.max_health
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        result.append(f"💀 **You died!** {get_cocky_line()} Rewards saved.")
        result.extend(_grant_end_of_run_rewards(player))
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
        cost = int(ammo_data["cost_per_attack"])
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
        dmg = int(player.weapon_damage * mod)
        is_crit = random.random() < player.crit_chance
        if is_crit:
            dmg = int(dmg * 2)
        enemy.health = max(0, enemy.health - dmg)
        mod_txt = f" (Zone {int(mod*100)}%)" if mod != 1.0 else ""
        crit_txt = " **CRIT!**" if is_crit else ""
        magical_txt = " ✨ **MAGICAL! Free shot!**" if is_magical else ""
        messages.append(f"🔫 Hit **{enemy.name} for {dmg}**{crit_txt}{magical_txt} using {player.ammo_name} ({cost}/shot){mod_txt}")
        
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
        if player.money < 40:
            return [f"❌ Need $40, you have ${player.money}"]
        player.money -= 40
        player.painkillers += 2
        return [f"💊 Bought painkillers +2. ${player.money} left."]
    if item == "full_restore":
        if player.money < 120:
            return [f"❌ Need $120, you have ${player.money}"]
        player.money -= 120
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


def get_star_upgrade_cost(player: Survivor, stat: str) -> int:
    """Custom star costs: 5 to unlock, then 1 or 3 per level"""
    stat = stat.lower().strip()
    alias = {
        "dodge": "dodge", "dodge_chance": "dodge", "evade": "dodge",
        "magical": "magical", "magical_bullet": "magical", "magic": "magical", "bullet": "magical", "ammo_saver": "magical",
        "medic": "medic", "medic_drop": "medic", "heal_drop": "medic",
        "pet": "pet", "pet_attack": "pet", "wolf": "pet", "dog": "pet",
    }
    canonical = alias.get(stat, stat)
    if canonical == "dodge":
        if player.star_dodge_upgrades == 0:
            return 5
        return 1
    elif canonical == "magical":
        if player.star_magical_upgrades == 0:
            return 5
        return 1
    elif canonical == "medic":
        if player.star_medic_upgrades == 0:
            return 5
        return 1
    elif canonical == "pet":
        if player.star_pet_upgrades == 0:
            return 5
        return 3
    return 999

def upgrade_star(player: Survivor, stat: str) -> list[str]:
    if player.run_active:
        return ["Can't upgrade during a run!"]
    stat = stat.lower().strip()
    alias = {
        "dodge": "dodge", "dodge_chance": "dodge", "evade": "dodge",
        "magical": "magical", "magical_bullet": "magical", "magic": "magical", "bullet": "magical", "ammo_saver": "magical",
        "medic": "medic", "medic_drop": "medic", "heal_drop": "medic",
        "pet": "pet", "pet_attack": "pet", "wolf": "pet", "dog": "pet",
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
        player.run_active = False
        player.enemy = None
        player.health = player.max_health
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        result.append(f"💀 **You died!** {get_cocky_line()} Rewards saved.")
        result.extend(_grant_end_of_run_rewards(player))
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
        cost = int(ammo_data["cost_per_attack"])
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
        dmg = int(player.weapon_damage * mod)
        is_crit = random.random() < player.crit_chance
        if is_crit:
            dmg = int(dmg * 2)
        enemy.health = max(0, enemy.health - dmg)
        mod_txt = f" (Zone {int(mod*100)}%)" if mod != 1.0 else ""
        crit_txt = " **CRIT!**" if is_crit else ""
        magical_txt = " ✨ **MAGICAL! Free shot!**" if is_magical else ""
        messages.append(f"🔫 Hit **{enemy.name} for {dmg}**{crit_txt}{magical_txt} using {player.ammo_name} ({cost}/shot){mod_txt}")
        
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
        if player.money < 40:
            return [f"❌ Need $40, you have ${player.money}"]
        player.money -= 40
        player.painkillers += 2
        return [f"💊 Bought painkillers +2. ${player.money} left."]
    if item == "full_restore":
        if player.money < 120:
            return [f"❌ Need $120, you have ${player.money}"]
        player.money -= 120
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


def get_star_upgrade_cost(player: Survivor, stat: str) -> int:
    """Custom star costs: 5 to unlock, then 1 or 3 per level"""
    stat = stat.lower().strip()
    alias = {
        "dodge": "dodge", "dodge_chance": "dodge", "evade": "dodge",
        "magical": "magical", "magical_bullet": "magical", "magic": "magical", "bullet": "magical", "ammo_saver": "magical",
        "medic": "medic", "medic_drop": "medic", "heal_drop": "medic",
        "pet": "pet", "pet_attack": "pet", "wolf": "pet", "dog": "pet",
    }
    canonical = alias.get(stat, stat)
    if canonical == "dodge":
        if player.star_dodge_upgrades == 0:
            return 5
        return 1
    elif canonical == "magical":
        if player.star_magical_upgrades == 0:
            return 5
        return 1
    elif canonical == "medic":
        if player.star_medic_upgrades == 0:
            return 5
        return 1
    elif canonical == "pet":
        if player.star_pet_upgrades == 0:
            return 5
        return 3
    return 999

def upgrade_star(player: Survivor, stat: str) -> list[str]:
    if player.run_active:
        return ["Can't upgrade during a run!"]
    stat = stat.lower().strip()
    alias = {
        "dodge": "dodge", "dodge_chance": "dodge", "evade": "dodge",
        "magical": "magical", "magical_bullet": "magical", "magic": "magical", "bullet": "magical", "ammo_saver": "magical",
        "medic": "medic", "medic_drop": "medic", "heal_drop": "medic",
        "pet": "pet", "pet_attack": "pet", "wolf": "pet", "dog": "pet",
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

# === ZOMBIE UI (from zombie_ui.py) ===
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
        embed.add_field(
            name="💰 Total Money Earned",
            value=f"**${player.money}**",
            inline=True,
        )
        embed.add_field(
            name="✨ Total XP Earned",
            value=f"**{player.xp} XP** (Lvl {player.level})",
            inline=True,
        )
        if run_money or run_xp:
            embed.add_field(
                name="📊 This Run",
                value=f"💵 +${run_money} • 🌟 +{run_xp} XP\n❤️ {player.health}/{player.max_health} HP restored",
                inline=False,
            )
        else:
            embed.add_field(name="Status", value=f"❤️ {player.health}/{player.max_health} HP restored", inline=False)
        embed.set_footer(text="Start another run or shop in main menu.")
        return embed

    embed = discord.Embed(
        title=f"🧟 WAVE {player.wave} • {player.zombies_remaining} left",
        color=discord.Color.from_rgb(237, 66, 69),
        description="\n".join(m for m in messages if m) or "Lock, load, and choose.",
    )
    embed.add_field(
        name=f"❤️ YOU — {player.health}/{player.max_health} HP",
        value=f"{_health_bar(player.health, player.max_health)} **{player.health}/{player.max_health}**\n🔫 `{player.magazine}/{player.magazine_size}` + {player.spare_ammo} spare",
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
        description=f"Health: **{player.health}/{player.max_health} HP** {_health_bar(player.health, player.max_health)}\nHealing does **not** consume your turn.",
    )
    pain_status = "✅ Ready" if player.painkillers > 0 and pain_left > 0 and player.health < player.max_health else "❌ Unavailable"
    embed.add_field(name=f"💊 Painkillers • {pain_status}", value=f"**{player.painkillers} owned**\n`{pain_left} uses left this run`\nHeals ~{player.max_health//4} HP", inline=True)
    full_status = "✅ Ready" if player.full_restores > 0 and full_left > 0 and player.health < player.max_health else "❌ Unavailable"
    embed.add_field(name=f"✨ Full Restore • {full_status}", value=f"**{player.full_restores} owned**\n`{full_left} use left this run`\nFull heal", inline=True)
    if player.health >= player.max_health:
        embed.set_footer(text="Already full HP!")
    else:
        embed.set_footer(text=f"{pain_left} painkiller uses + {full_left} restore uses left")
    return embed

def status_detail_embed(player: object) -> discord.Embed:
    embed = discord.Embed(title="📊 Survivor Intel", color=discord.Color.from_rgb(88, 101, 242))
    embed.add_field(name="🔫 Loadout", value=f"**{player.weapon_name}** • {player.ammo_name} ammo\nLevel {player.level} • {player.stars} ⭐", inline=False)
    embed.add_field(name=f"🌍 {player.zone_name}", value=ammo_effectiveness_text(player), inline=False)
    embed.add_field(name="📦 Resources", value=f"💰 ${player.money} • ✨ {player.xp} XP\n❤️ {player.health}/{player.max_health} HP", inline=False)
    return embed

def shop_embed(player: object, last_messages: list[str] | None = None) -> discord.Embed:
    """NEW: Shop embed that ALWAYS shows current money - fixes your bug"""
    embed = discord.Embed(
        title="🛒 Armory Shop",
        color=discord.Color.from_rgb(87, 242, 135),
        description="\n".join(last_messages) if last_messages else "Buy gear. Money deducts instantly.",
    )
    embed.add_field(name="💰 Your Money", value=f"**${player.money}**", inline=True)
    embed.add_field(name="📦 Ammo", value=f"{player.spare_ammo} spare + {player.magazine}/{player.magazine_size} mag", inline=True)
    embed.add_field(name="💊 Heals", value=f"{player.painkillers} painkillers • {player.full_restores} restores", inline=True)
    embed.set_footer(text="Prices deduct immediately - no need to switch menus.")
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
    @discord.ui.button(label="▶️ Start run", style=discord.ButtonStyle.success, row=0)
    async def start_run_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        messages = start_run(player)
        self.store.save()
        await interaction.response.edit_message(content=None, embed=combat_embed(messages, player), view=CombatView(self.user_id, self.store))

    @discord.ui.button(label="⚔️ Combat", style=discord.ButtonStyle.danger, row=0)
    async def combat(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        if player.run_active:
            await interaction.response.edit_message(content=None, embed=combat_embed([], player), view=CombatView(self.user_id, self.store))
        else:
            messages = start_run(player)
            self.store.save()
            await interaction.response.edit_message(content=None, embed=combat_embed(messages, player), view=CombatView(self.user_id, self.store))

    @discord.ui.button(label="🛒 Shop", style=discord.ButtonStyle.primary, row=0)
    async def shop(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=None, embed=shop_embed(player), view=ShopView(self.user_id, self.store))

    @discord.ui.button(label="🗺️ Zones", style=discord.ButtonStyle.primary, row=0)
    async def zones(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(player), view=ZoneView(self.user_id, self.store))

    @discord.ui.button(label="🔬 Ammo lab", style=discord.ButtonStyle.primary, row=1)
    async def ammo(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(player), view=AmmoView(self.user_id, self.store))

    @discord.ui.button(label="⬆️ Upgrades", style=discord.ButtonStyle.success, row=1)
    async def upgrades(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        player = self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(player), view=UpgradeView(self.user_id, self.store))

    @discord.ui.button(label="🔄 Refresh status", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_status(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))

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
        choices = [("❤️ Max health · 1 star", "health"), ("💥 Weapon damage · 1 star", "damage"), ("📦 Magazine size · 1 star", "magazine")]
        for label, value in choices:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.success, row=0)
            async def callback(interaction: discord.Interaction, selected: str = value) -> None:
                await self._upgrade(interaction, selected)
            button.callback = callback
            self.add_item(button)
        back = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=1)
        async def back_callback(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(content=status(self.store.get(self.user_id)), view=ZombieMenuView(self.user_id, self.store))
        back.callback = back_callback
        self.add_item(back)
    async def _upgrade(self, interaction: discord.Interaction, stat: str) -> None:
        player = self.store.get(self.user_id)
        messages = upgrade(player, stat)
        self.store.save()
        await interaction.response.edit_message(content=status(self.store.get(self.user_id)) + "\n\n" + "\n".join(messages), view=UpgradeView(self.user_id, self.store))

# === BOT MAIN (from main.py) ===
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
    )


@zombie.command(name="status", description="Show your survivor status.")
async def zombie_status(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        status(game_store.get(interaction.user.id)),
        view=ZombieMenuView(interaction.user.id, game_store),
    )


@zombie.command(name="menu", description="Open selectable zombie survival menus.")
async def zombie_menu(interaction: discord.Interaction) -> None:
    """Open the interactive select-menu game interface."""
    await interaction.response.send_message(
        status(game_store.get(interaction.user.id)),
        view=ZombieMenuView(interaction.user.id, game_store),
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


@zombie.command(name="upgrade", description="Buy permanent upgrades with money.")
@app_commands.describe(stat="The stat to upgrade")
@app_commands.choices(
    stat=[
        app_commands.Choice(name="Max health +20", value="health"),
        app_commands.Choice(name="Weapon damage +3", value="damage"),
        app_commands.Choice(name="Magazine size +1", value="mag"),
        app_commands.Choice(name="Crit chance +2%", value="crit"),
        app_commands.Choice(name="Armor -2 dmg", value="armor"),
        app_commands.Choice(name="Loot +5% money", value="scavenger"),
    ]
)
async def zombie_upgrade(interaction: discord.Interaction, stat: app_commands.Choice[str]) -> None:
    player = game_store.get(interaction.user.id)
    messages = upgrade(player, stat.value)
    game_store.save()
    await interaction.response.send_message("\n".join(messages))


bot.tree.add_command(zombie)


# --- ADMIN ONLY TEST COMMANDS - LOCKED TO YOUR ID 1548647360123502613 ---
ADMIN_ID = 1548647360123502613

def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.id == ADMIN_ID

@bot.tree.command(name="addmoney", description="[ADMIN] Add money - admin only")
@app_commands.describe(amount="Amount to add")
async def addmoney(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin-only test command.", ephemeral=True)
        return
    player = game_store.get(interaction.user.id)
    player.money += amount
    game_store.save()
    await interaction.response.send_message(f"💰 **+${amount} added** → You now have **${player.money}**\nGo test the 6 upgrades!", ephemeral=True)

@bot.tree.command(name="addstars", description="[ADMIN] Add stars - admin only")
@app_commands.describe(amount="Amount")
async def addstars(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin-only.", ephemeral=True)
        return
    player = game_store.get(interaction.user.id)
    player.stars += amount
    game_store.save()
    await interaction.response.send_message(f"⭐ **+{amount} stars** → You now have **{player.stars}** flex", ephemeral=True)

@bot.tree.command(name="addxp", description="[ADMIN] Add XP - admin only")
@app_commands.describe(amount="Amount")
async def addxp(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin-only.", ephemeral=True)
        return
    player = game_store.get(interaction.user.id)
    player.xp += amount
    game_store.save()
    await interaction.response.send_message(f"✨ **+{amount} XP** → Level {player.level} | XP: {player.xp}", ephemeral=True)

@bot.tree.command(name="setmoney", description="[ADMIN] Set money to exact amount - admin only")
@app_commands.describe(amount="Set money to this amount")
async def setmoney(interaction: discord.Interaction, amount: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin-only.", ephemeral=True)
        return
    player = game_store.get(interaction.user.id)
    player.money = amount
    game_store.save()
    await interaction.response.send_message(f"💰 Money set to **${player.money}**", ephemeral=True)

@bot.tree.command(name="resetme", description="[ADMIN] Reset yourself to level 1 - admin only")
async def resetme(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admin-only.", ephemeral=True)
        return
    from bot.zombie_survival import Survivor
    game_store.players[str(interaction.user.id)] = Survivor()
    game_store.save()
    await interaction.response.send_message("🔄 **Reset to level 1!** Use /addmoney to test again.", ephemeral=True)
# --- END ADMIN COMMANDS ---





def main():
    import os, sys
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN not set")
        sys.exit(1)
    print(f"Token found {token[:12]}... Starting")
    bot.run(token, log_handler=None)

if __name__ == "__main__":
    main()
