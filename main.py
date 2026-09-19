"""Ultimate clean bot V6 FULL RESTORED - POSTGRES CONSTANT SAVE - every action saves instantly - zero loss"""
import os, sys, json, random, logging, time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone
import discord
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('zombie-bot')
from discord import app_commands

from storage import load_all_players, save_player, DB_PATH, SAVE_FILE, get_bot_admins, is_bot_admin, add_bot_admin, remove_bot_admin, verify_storage
print(f"[STORAGE] Using POSTGRES - CONSTANT SAVE ENABLED - V6 FULL RESTORED")

_purchase_locks: set[int] = set()


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
        value=f"`{p_bar}`\n🔫 {player.weapon_name} {player.magazine}/{player.magazine_size} ({player.get_spare()} spare) [{player.ammo_name}]\n◈ Void Bazooka: {player.void_bazooka_ammo} shot(s) ready | Lvl {player.void_weapon_level}/10\n◈ Perks: {_void_perk_status(player)}",
        inline=False
    )
    embed.add_field(
        name=f"💀 {e_name}: {e_hp} HP ({e_pct}%)",
        value=f"`{e_bar}`\n⚔️ ~{e_dmg} dmg",
        inline=False
    )
    if player.enemy and player.enemy.is_bloater:
        embed.add_field(name=f"💣 BLOATER - {player.enemy.bloater_timer} ATTACKS LEFT!", value=f"⏰ Kill it in {player.enemy.bloater_timer} attacks or take {int(BLOATER_EXPLODE_PCT*100)}% max HP damage! Solo wave - reward if you survive!", inline=False)
    if last_msgs:
        clean = [m for m in last_msgs if m and "HP restored" not in m and "Waves survived" not in m][:3]
        if clean:
            embed.add_field(name="⚔️ Last action", value="\n".join(clean)[:1024], inline=False)
    embed.set_footer(text=f"💰 ${player.money} | ⭐ {player.stars} | ✨ {player.xp} XP | {player.ammo_name} {player.magazine}/{player.magazine_size}")
    return embed



MAX_LEVEL = 500
MAX_PAINKILLERS_PER_RUN = 3
MAX_FULL_RESTORES_PER_RUN = 1
ZONES: dict[str, dict[str, Any]] = {
    "Graveyard": {"min_level": 1, "hp_mult": 0.9, "dmg_mult": 0.9, "money_mult": 2.0, "xp_mult": 1.6, "desc": "Foggy, quiet, and good for learning.", "weights": [60, 25, 12, 3], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.00, "Frostbite": 1.00, "Toxic": 1.00, "Shock": 1.00}},
    "Mega Death City": {"min_level": 50, "hp_mult": 1.8, "dmg_mult": 1.3, "money_mult": 3.5, "xp_mult": 2.0, "desc": "A concrete jungle with tougher, richer zombies.", "weights": [30, 30, 25, 15], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.20, "Frostbite": 0.90, "Toxic": 1.00, "Shock": 1.15}},
    "Frostbitten Outskirts": {"min_level": 100, "hp_mult": 3.2, "dmg_mult": 1.7, "money_mult": 5.0, "xp_mult": 2.4, "desc": "Freezing rain and frost armor - NOT for level 50s.", "weights": [20, 20, 35, 25], "ammo_mods": {"Standard": 1.00, "Bleed": 0.90, "Incendiary": 1.40, "Frostbite": 0.70, "Toxic": 1.00, "Shock": 1.15}},
    "Toxic Wasteland": {"min_level": 150, "hp_mult": 5.0, "dmg_mult": 2.1, "money_mult": 7.5, "xp_mult": 3.2, "desc": "A green haze where toxic rounds shine. Bring real gear.", "weights": [15, 15, 35, 35], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.10, "Frostbite": 1.00, "Toxic": 1.50, "Shock": 0.90}},
    "The Void": {"min_level": 200, "hp_mult": 6.5, "dmg_mult": 2.6, "money_mult": 10.0, "xp_mult": 4.5, "desc": "Endgame. Everything wants you dead. 3-4 shots? Not here.", "weights": [10, 10, 30, 50], "ammo_mods": {"Standard": 0.90, "Bleed": 1.10, "Incendiary": 1.15, "Frostbite": 1.10, "Toxic": 1.25, "Shock": 1.50}},
}
ZONE_ORDER = ["Graveyard", "Mega Death City", "Frostbitten Outskirts", "Toxic Wasteland", "The Void"]
# Bloater config - run ender
BLOATER_BASE = {"health": 280, "damage": 4, "money": 350, "xp": 120}
BLOATER_MAX_PER_ZONE = {
    "Graveyard": 1,
    "Mega Death City": 2,
    "Frostbitten Outskirts": 3,
    "Toxic Wasteland": 4,
    "The Void": 5,
}
BLOATER_MIN_WAVE = 5
BLOATER_FUSE = 5  # attacks before explosion
BLOATER_EXPLODE_PCT = 0.65  # 65% max HP
AMMO: dict[str, dict[str, Any]] = {
    "Standard": {"unlock_level": 1, "price": 0, "desc": "Reliable regular lead.", "effect": None, "cost_per_attack": 1, "box_price": 15, "box_amount": 24},
    "Bleed": {"unlock_level": 10, "price": 200, "desc": "25% bleed 15 dmg x3", "effect": "bleed", "cost_per_attack": 2, "box_price": 50, "box_amount": 24},
    "Incendiary": {"unlock_level": 35, "price": 600, "desc": "30% burn 20 dmg x3", "effect": "burn", "cost_per_attack": 3, "box_price": 100, "box_amount": 24},
    "Frostbite": {"unlock_level": 70, "price": 1200, "desc": "25% freeze halves dmg x4 + 10 dmg x2", "effect": "freeze", "cost_per_attack": 4, "box_price": 100, "box_amount": 24},
    "Toxic": {"unlock_level": 110, "price": 2500, "desc": "40% poison 18 dmg x5", "effect": "poison", "cost_per_attack": 5, "box_price": 150, "box_amount": 24},
    "Shock": {"unlock_level": 160, "price": 5000, "desc": "20% stun 1 turn + 20 dmg", "effect": "shock", "cost_per_attack": 6, "box_price": 185, "box_amount": 24},
}
WEAPONS: dict[str, dict[str, Any]] = {
    "Pistol": {"damage": 20, "mag": 12, "price": 0, "unlock_level": 1, "shots": 1},
    "Shotgun": {"damage": 45, "mag": 6, "price": 250, "unlock_level": 15, "shots": 1},
    "Rifle": {"damage": 25, "mag": 30, "price": 2500, "unlock_level": 30, "shots": 2},
    "SMG": {"damage": 15, "mag": 42, "price": 4000, "unlock_level": 60, "shots": 3},
    "Sawed-Off": {"damage": 70, "mag": 2, "price": 6000, "unlock_level": 90, "shots": 1},
    "Tactical Sniper": {"damage": 180, "mag": 1, "price": 15000, "unlock_level": 125, "shots": 1, "desc": "Heavy late-game single-shot sniper. Massive damage, but starts with a 1-round magazine and relies on Magazine upgrades for special ammo."},
}

# --- VOID WEAPON SYSTEM ---
# Void weapons are deliberately separate from the normal WEAPONS system.
# Their damage is NEVER modified by standard Damage upgrades.
VOID_WEAPONS: dict[str, dict[str, Any]] = {
    "Void Bazooka": {
        "damage": 700,
        "price": 25000,
        "unlock_level": 200,
        "boss_mult": 2.00,
        "level_10_boss_mult": 4.00,
        "desc": "Heavy single-target backup weapon. Massive damage to Bloaters and Void bosses.",
    },
}
VOID_UPGRADE_MAX = 10
VOID_BAZOOKA_DAMAGE_PER_LEVEL = 20
VOID_BAZOOKA_FREE_AMMO_PER_RUN = 1
VOID_BAZOOKA_AMMO_COST = 10

# --- VOID PERKS ---
# Three temporary, Essence-powered combat perks. Level 1 unlocks the perk;
# later levels improve its effect. Perks are intentionally separate from the
# normal upgrade tree and can also modify Void Bazooka attacks.
VOID_PERKS: dict[str, dict[str, Any]] = {
    "Void Infusion": {"unlock_cost": 40, "activation_cost": 3, "cooldown": 3, "base_bonus": 0.15, "bonus_per_level": 0.03, "max_bonus": 0.42},
    "Void Shield": {"unlock_cost": 50, "activation_cost": 4, "cooldown": 4, "base_bonus": 0.20, "bonus_per_level": 0.03, "max_bonus": 0.47},
    "Void Execution": {"unlock_cost": 65, "activation_cost": 5, "cooldown": 5, "base_bonus": 0.25, "bonus_per_level": 0.04, "max_bonus": 0.61},
}
VOID_PERK_UPGRADE_COSTS: dict[str, list[int]] = {
    "Void Infusion": [40, 25, 35, 45, 60, 75, 90, 110, 135, 165],
    "Void Shield": [50, 30, 45, 60, 80, 100, 125, 150, 180, 215],
    "Void Execution": [65, 40, 55, 75, 95, 120, 145, 175, 210, 250],
}
# Void Essence is endgame material, so it is intentionally scarce.
# Normal Void kills give a small amount; Bloaters and wave clears remain
# meaningful sources without making Essence accumulate too quickly.
VOID_ESSENCE_NORMAL_DROP_CHANCE = 0.25
VOID_ESSENCE_PER_VOID_KILL = 1
VOID_ESSENCE_PER_VOID_BLOATER = 4
VOID_ESSENCE_PER_VOID_WAVE = 1
VOID_ESSENCE_WAVE_START = 5


# --- DEATH LINES - SPLIT BY TYPE (BIG VARIETY - no repeats) ---
NORMAL_DEATH_LINES = [
    "Bro really thought he was the main character 💀 LMAO dead.",
    "Your K/D is so bad the zombies are laughing at you.",
    "Even the Walkers are embarrassed they killed YOU.",
    "You got folded like laundry, buddy. Stay down.",
    "Graveyard's full of heroes like you — oh wait, you're just food.",
    "Skill issue. Literally. Uninstall, survivor.",
    "The zombies didn't even have to try. You just sucked.",
    "Nice try, hero. The graveyard just got one plot fuller.",
    "You died faster than your WiFi drops. Impressive.",
    "Imagine training for years just to die to a Walker. Couldn't be me.",
    "The zombies sent a thank you card for the free meal.",
    "You fought like a stormtrooper. Blind and useless.",
    "My grandma fights better than you, and she's been dead for 10 years.",
    "You got clapped so hard the zombies had to respawn.",
    "That was the worst performance since your last rank game.",
    "You died so fast the death screen didn't even load properly.",
    "The Brute didn't even feel you. You were just tickling it.",
    "You got humbled by a zombie with no brain. Think about that.",
    "Bro got 1v1'd by a Walker and LOST. Log off.",
    "Your gameplay is so bad the zombies felt bad eating you.",
    "You just donated your loot to the zombie foundation. Thanks!",
    "You died like a tutorial NPC. Zero aura.",
    "The zombies are writing a book: 'How to kill YOU in 2 seconds'.",
    "You got turned into a highlight reel for the hoard.",
    "Even the Mutant is disappointed. You were that easy.",
    "You got packed up so quick I didn't even see it happen.",
    "You call that fighting? I call that free XP for zombies.",
    "You just made the zombies' day. Free lunch!",
    "The Graveyard has a VIP section and you're banned from it. Too bad.",
    "You died with full meds in your pocket. Classic.",
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
    "Bro forgot to reload in a zombie apocalypse. Genius move.",
    "You had ONE job: bring ammo. You failed it.",
    "Running out of ammo mid-fight? That's rookie hour, kid.",
    "You spent all your money on drip and forgot bullets. LMAO.",
    "CLICK CLICK BOOM... oh wait, just CLICK. You're dead.",
    "Imagine flexing a Sawed-Off with no shells. Embarrassing.",
    "You tried to scare them with an empty mag. They laughed.",
    "No bullets, no brain, no hope. The triple combo.",
    "You counted your money but not your bullets. Priorities.",
    "The zombies heard CLICK and knew dinner was served.",
    "You brought a knife to a gunfight and didn't even bring the knife.",
    "Your ammo counter hit 0 and so did your survival chance.",
    "Should've looted more, shot less. You did the opposite, dumbass.",
    "You ran out of ammo faster than you run from your problems.",
    "Empty mag, empty head. Perfect match.",
    "The shop sells ammo for a reason. You ignored it and died.",
    "You had 0 bullets and 100% confidence. Now you have 0 of both.",
    "Bro really thought intimidation would kill zombies. Cute.",
    "You conserved ammo so well you died with 0 kills. Pro strat.",
    "The zombies thank you for saving them ammo. You did their job.",
    "You played yourself. No ammo = no win. Simple math.",
    "Next time buy bullets, not excuses.",
]

FLEE_LINES = [
    "Ran away? Smartest play you've made all week, survivor.",
    "Fled like a coward, lived like a coward. Classic you.",
    "You ran so fast even the zombies got confused. Respect.",
    "Tactical retreat? Nah, you just panicked and bolted.",
    "At least you're good at ONE thing — running away.",
    "The hoard will remember you as 'that guy who ran'. Legend.",
    "Fleeing again? The graveyard's disappointed you're still alive.",
    "You fled like a legend! ...a legend of being scared.",
    "You ran away so fast you left your dignity behind.",
    "The zombies are still laughing at how fast you bolted.",
    "Retreat! Retreat! The bravest chicken in the apocalypse.",
    "You fled faster than you die. That's actually progress.",
    "The zombies didn't even chase you. You weren't worth it.",
    "You ran like your mom called you for dinner. Adorable.",
    "Escaped with your life but not your pride. Worth it?",
    "You lived to fight another day... and lose another day.",
    "The hoard watched you run and thought 'same, bro, same'.",
    "You hit the eject button so fast I got whiplash.",
    "Fleeing is a valid strat, but you made it look embarrassing.",
    "You ran like the rent was due and zombies were landlords.",
    "Congratulations, you survived by being a coward. Trophy?",
    "You fled like a pro. Too bad you fight like an amateur.",
    "The zombies let you go. You were too boring to eat.",
    "You escaped! The zombies are filing a missing person report: your skill.",
    "You lived, but at what cost? Your reputation, apparently.",
    "You ran so far you're back at level 1. Oh wait...",
    "Tactical retreat or just pure fear? We all know the answer.",
    "You yeeted out of there like your life depended on it. It did.",
    "Fleeing is smart, but you made it look like an Olympic sport.",
    "You survived, but the hoard is still cringing at your exit.",
]

def get_cocky_line() -> str:
    import random
    return random.choice(NORMAL_DEATH_LINES)

def get_no_ammo_line() -> str:
    import random
    return random.choice(NO_AMMO_DEATH_LINES)

def get_flee_line() -> str:
    import random
    return random.choice(FLEE_LINES)


ZOMBIES: dict[str, dict[str, int]] = {
    "Walker": {"health": 50, "damage": 10, "money": 18, "xp": 10},
    "Runner": {"health": 35, "damage": 18, "money": 32, "xp": 18},
    "Brute": {"health": 100, "damage": 15, "money": 65, "xp": 30},
    "Mutant": {"health": 150, "damage": 25, "money": 140, "xp": 70},
}
@dataclass
class Enemy:
    name: str; health: int; max_health: int; damage: int; money_reward: int; xp_reward: int; effects: dict[str, int] = field(default_factory=dict)
    is_bloater: bool = False
    is_void_boss: bool = False
    bloater_timer: int = 0  # fuse countdown for Bloater
@dataclass
class Survivor:
    max_health: int = 100; health: int = 100; money: int = 0; xp: int = 0; stars: int = 0
    weapon_name: str = "Pistol"; weapon_damage: int = 20; magazine_size: int = 12; magazine: int = 12
    spare_ammo: dict[str, int] = field(default_factory=lambda: {"Standard": 36})
    full_restores: int = 1; painkillers: int = 3; painkillers_used_this_run: int = 0; full_restores_used_this_run: int = 0
    run_money_earned: int = 0; run_xp_earned: int = 0; run_zombies_killed: int = 0; zone_name: str = "Graveyard"; ammo_name: str = "Standard"
    owned_ammo: list[str] = field(default_factory=lambda: ["Standard"]); owned_weapons: list[str] = field(default_factory=lambda: ["Pistol"])
    run_active: bool = False; wave: int = 0; zombies_remaining: int = 0; enemy: Enemy | None = None
    # --- Bloater tracking ---
    bloaters_spawned_this_run: int = 0
    bloater_cooldown: int = 0  # waves since last bloater to avoid back-to-back
    # --- NEW: permanent upgrade counters ---
    damage_upgrades: int = 0; health_upgrades: int = 0; mag_upgrades: int = 0
    crit_upgrades: int = 0; armor_upgrades: int = 0; scavenger_upgrades: int = 0
    # --- STAR UPGRADES (prestige) - CUSTOM 4 ---
    star_dodge_upgrades: int = 0; star_magical_upgrades: int = 0
    star_medic_upgrades: int = 0; star_pet_upgrades: int = 0; star_xp_upgrades: int = 0
    # --- VOID WEAPON PROGRESSION ---
    void_essence: int = 0; void_weapon_level: int = 0
    void_weapons_owned: list[str] = field(default_factory=list)
    void_bazooka_ammo: int = 0; void_bazooka_boss_fired: bool = False
    # --- VOID PERKS ---
    void_infusion_level: int = 0; void_shield_level: int = 0; void_execution_level: int = 0
    void_infusion_cooldown: int = 0; void_shield_cooldown: int = 0; void_execution_cooldown: int = 0
    void_infusion_active: bool = False; void_shield_active: bool = False; void_execution_active: bool = False
    # --- LEADERBOARDS ---
    highest_waves: dict[str, int] = field(default_factory=dict)
    highest_wave_dates: dict[str, str] = field(default_factory=dict)
    leaderboard_name: str = "Survivor"
    leaderboard_guilds: list[str] = field(default_factory=list)
    # Persistent flag so admin test runs stay excluded from leaderboards even across restarts.
    admin_test_mode: bool = False
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
        return 1.0 + self.scavenger_upgrades * 0.10
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
        allowed.setdefault("bloaters_spawned_this_run", 0); allowed.setdefault("bloater_cooldown", 0)
        allowed.setdefault("owned_ammo", ["Standard"]); allowed.setdefault("owned_weapons", ["Pistol"])
        allowed.setdefault("void_essence", 0)
        allowed.setdefault("void_weapon_level", 0)
        allowed.setdefault("void_weapons_owned", [])
        allowed.setdefault("void_bazooka_ammo", 0)
        allowed.setdefault("void_bazooka_boss_fired", False)
        allowed.setdefault("void_infusion_level", 0); allowed.setdefault("void_shield_level", 0); allowed.setdefault("void_execution_level", 0)
        allowed.setdefault("void_infusion_cooldown", 0); allowed.setdefault("void_shield_cooldown", 0); allowed.setdefault("void_execution_cooldown", 0)
        allowed.setdefault("void_infusion_active", False); allowed.setdefault("void_shield_active", False); allowed.setdefault("void_execution_active", False)
        allowed.setdefault("highest_waves", {})
        allowed.setdefault("highest_wave_dates", {})
        allowed.setdefault("leaderboard_name", data.get("leaderboard_name", "Survivor"))
        allowed.setdefault("leaderboard_guilds", [])
        allowed.setdefault("admin_test_mode", False)
        if "Pistol" not in allowed["owned_weapons"]: allowed["owned_weapons"].append("Pistol")
        if "stars" not in data: allowed["stars"] = max(0, level_for_xp(int(data.get("xp", 0))) - 1)
        return cls(**allowed)

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
    # V2: smoother late-game XP curve; keeps level 250 long-term without the sharp endgame wall.
    if level <= 5:
        return 50 + (level - 1) * 15
    elif level <= 10:
        return 110 + (level - 5) * 20
    elif level <= 50:
        return 200 + (level - 10) * 40 + (level - 1) * 10
    elif level <= 100:
        return 350 + (level - 10) * 50 + (level - 1) * 15
    elif level <= 150:
        return 550 + (level - 10) * 60 + (level - 1) * 20
    else:
        return 700 + (level - 10) * 60 + (level - 1) * 22

def level_for_xp(total_xp: int) -> int:
    level = 1
    earned = max(0, total_xp)
    while level < MAX_LEVEL and earned >= xp_to_next_level(level):
        earned -= xp_to_next_level(level)
        level += 1
    return min(level, MAX_LEVEL)

def level_progress(player: Survivor) -> tuple[int, int]:
    earned = max(0, player.xp)
    level = 1
    while level < MAX_LEVEL and earned >= xp_to_next_level(level):
        earned -= xp_to_next_level(level)
        level += 1
    if level >= MAX_LEVEL:
        return 0, 0
    return earned, xp_to_next_level(level)

def _should_spawn_bloater(player: Survivor) -> bool:
    """Decide if Bloater should spawn this enemy slot - balanced scaling"""
    if player.wave < BLOATER_MIN_WAVE:
        return False
    max_allowed = BLOATER_MAX_PER_ZONE.get(player.zone_name, 1)
    if player.bloaters_spawned_this_run >= max_allowed:
        return False
    if player.bloater_cooldown > 0:
        return False
    # Chance scales with wave: 5% at W5, +3% per wave, +2% per zone tier, cap 35%
    try:
        zone_idx = ZONE_ORDER.index(player.zone_name)
    except:
        zone_idx = 0
    base_chance = 0.05 + (player.wave - BLOATER_MIN_WAVE) * 0.03 + zone_idx * 0.02
    chance = min(0.35, base_chance)
    return random.random() < chance

def _make_bloater_enemy(player: Survivor) -> Enemy:
    zone = zone_for(player)
    # Bloater health scales but not insane: base 280 + wave*12 * hp_mult
    health = int(
        (BLOATER_BASE["health"] + (player.wave - 1) * 15)
        * zone["hp_mult"]
        * BLOATER_BOSS_HP_MULT
    )
    # Damage is low ~4 as requested, but scale slightly with zone
    dmg = int(BLOATER_BASE["damage"] * zone["dmg_mult"])
    dmg = max(1, min(dmg, 8))  # keep it 1-8 max
    money = int(BLOATER_BASE["money"] * zone["money_mult"] * 1.5)
    xp = int(BLOATER_BASE["xp"] * zone["xp_mult"] * 1.5)
    return Enemy(
        name="Bloater",
        health=health,
        max_health=health,
        damage=dmg,
        money_reward=money,
        xp_reward=xp,
        is_bloater=True,
        bloater_timer=BLOATER_FUSE
    )

def spawn_enemy(player: Survivor) -> Enemy:
    # Bloater check first - if eligible, spawn it as solo wave boss
    if _should_spawn_bloater(player):
        bloater = _make_bloater_enemy(player)
        player.bloaters_spawned_this_run += 1
        player.bloater_cooldown = 2  # no back-to-back bloaters
        # Solo wave: only bloater this round = reward
        player.zombies_remaining = 1
        return bloater

    zone = zone_for(player)
    name = random.choices(list(ZOMBIES), weights=zone["weights"])[0]
    base = ZOMBIES[name]
    health = int((base["health"] + (player.wave - 1) * 4) * zone["hp_mult"])
    damage = int((base["damage"] + (player.wave - 1) // 3) * zone["dmg_mult"])
    # Decrement bloater cooldown if any
    if player.bloater_cooldown > 0:
        player.bloater_cooldown -= 1
    return Enemy(name=name, health=health, max_health=health, damage=damage, money_reward=int(base["money"]*zone["money_mult"]), xp_reward=int(base["xp"]*zone["xp_mult"]))

def void_perk_level(player: Survivor, perk_name: str) -> int:
    field = {
        "Void Infusion": "void_infusion_level",
        "Void Shield": "void_shield_level",
        "Void Execution": "void_execution_level",
    }[perk_name]
    return max(0, min(10, int(getattr(player, field, 0))))

def void_perk_bonus(player: Survivor, perk_name: str) -> float:
    perk = VOID_PERKS[perk_name]
    lvl = void_perk_level(player, perk_name)
    if lvl <= 0:
        return 0.0
    return min(perk["max_bonus"], perk["base_bonus"] + (lvl - 1) * perk["bonus_per_level"])

def get_void_perk_cost(player: Survivor, perk_name: str) -> int:
    lvl = void_perk_level(player, perk_name)
    costs = VOID_PERK_UPGRADE_COSTS[perk_name]
    return costs[lvl] if lvl < len(costs) else 999999999

def upgrade_void_perk(player: Survivor, perk_name: str) -> list[str]:
    if player.run_active:
        return ["⚠️ Can't upgrade Void perks during a run! Flee first."]
    if player.level < VOID_WEAPONS["Void Bazooka"]["unlock_level"]:
        return [f"🔒 Void perks unlock at level {VOID_WEAPONS['Void Bazooka']['unlock_level']}."]
    lvl = void_perk_level(player, perk_name)
    if lvl >= 10:
        return [f"🔥 **{perk_name} is MAXED at Level 10!**"]
    cost = get_void_perk_cost(player, perk_name)
    if player.void_essence < cost:
        return [f"❌ Need ◈{cost} Void Essence; you have ◈{player.void_essence}."]
    player.void_essence -= cost
    field = {"Void Infusion":"void_infusion_level", "Void Shield":"void_shield_level", "Void Execution":"void_execution_level"}[perk_name]
    setattr(player, field, lvl + 1)
    bonus = int(void_perk_bonus(player, perk_name) * 100)
    return [f"◈ **{perk_name} upgraded to Level {lvl + 1}!** Effect → **+{bonus}%** | ◈{player.void_essence} Essence left."]

def activate_void_perk(player: Survivor, perk_name: str) -> list[str]:
    if not player.run_active or player.enemy is None:
        return ["⚠️ Void perks can only be activated during a Void run."]
    if player.zone_name != "The Void":
        return ["❌ Void perks only work inside **The Void**."]
    lvl = void_perk_level(player, perk_name)
    if lvl <= 0:
        return [f"🔒 **{perk_name}** is locked. Unlock it in the Void shop."]
    cooldown_field = {"Void Infusion":"void_infusion_cooldown", "Void Shield":"void_shield_cooldown", "Void Execution":"void_execution_cooldown"}[perk_name]
    active_field = {"Void Infusion":"void_infusion_active", "Void Shield":"void_shield_active", "Void Execution":"void_execution_active"}[perk_name]
    if getattr(player, cooldown_field) > 0:
        return [f"⏳ **{perk_name}** cooldown: {getattr(player, cooldown_field)} zombie(s) remaining."]
    if getattr(player, active_field):
        return [f"⚠️ **{perk_name}** is already armed."]
    if perk_name == "Void Execution" and player.enemy.health > player.enemy.max_health * 0.50:
        return ["⚠️ **Void Execution** only arms when the enemy is at **50% HP or lower**."]
    cost = VOID_PERKS[perk_name]["activation_cost"]
    if player.void_essence < cost:
        return [f"❌ Need ◈{cost} Void Essence to activate **{perk_name}**; you have ◈{player.void_essence}."]
    player.void_essence -= cost
    setattr(player, active_field, True)
    bonus = int(void_perk_bonus(player, perk_name) * 100)
    return [f"◈ **{perk_name} ARMED!** Next eligible effect: **+{bonus}%**. Cost ◈{cost}. Cooldown after use: {VOID_PERKS[perk_name]['cooldown']} kills."]

def _consume_void_offense_bonus(player: Survivor, enemy: Enemy) -> tuple[float, str]:
    multiplier = 1.0
    labels = []
    if player.void_infusion_active:
        bonus = void_perk_bonus(player, "Void Infusion")
        multiplier += bonus
        labels.append(f"Infusion +{int(bonus*100)}%")
        player.void_infusion_active = False
        player.void_infusion_cooldown = VOID_PERKS["Void Infusion"]["cooldown"]
    if player.void_execution_active:
        bonus = void_perk_bonus(player, "Void Execution")
        multiplier += bonus
        labels.append(f"Execution +{int(bonus*100)}%")
        player.void_execution_active = False
        player.void_execution_cooldown = VOID_PERKS["Void Execution"]["cooldown"]
    return multiplier, " | ".join(labels)

def _void_perk_status(player: Survivor) -> str:
    parts = []
    for name, field in [("Infusion", "void_infusion_level"), ("Shield", "void_shield_level"), ("Execution", "void_execution_level")]:
        lvl = getattr(player, field, 0)
        parts.append(f"{name} L{lvl}" if lvl else f"{name} 🔒")
    return " • ".join(parts)

def start_run(player: Survivor) -> list[str]:
    if player.run_active:
        return ["⚠️ Already in a run!"]

    player.health = player.max_health
    player.painkillers_used_this_run = 0
    player.full_restores_used_this_run = 0
    player.run_money_earned = 0
    player.run_xp_earned = 0
    player.run_zombies_killed = 0
    player.bloaters_spawned_this_run = 0
    player.bloater_cooldown = 0

    # The Void Bazooka is a dedicated backup weapon: one ready shot per run.
    # Initialise this BEFORE the no-normal-ammo check so a Void player with
    # zero primary ammo can still start and use the free Bazooka shot.
    player.void_bazooka_ammo = (
        VOID_BAZOOKA_FREE_AMMO_PER_RUN
        if "Void Bazooka" in player.void_weapons_owned and player.zone_name == "The Void"
        else 0
    )
    player.void_bazooka_boss_fired = False
    player.void_infusion_cooldown = 0
    player.void_shield_cooldown = 0
    player.void_execution_cooldown = 0
    player.void_infusion_active = False
    player.void_shield_active = False
    player.void_execution_active = False
    # Normal runs are eligible for leaderboard records. /setwave temporarily
    # marks a run as an admin test and prevents those test clears from scoring.
    player.admin_test_mode = False

    if player.magazine == 0:
        spare = player.get_spare()
        if spare > 0:
            load_amt = min(player.magazine_size, spare)
            player.magazine = load_amt
            player.spare_ammo[player.ammo_name] = spare - load_amt

    player.wave = 1
    player.zombies_remaining = 3
    player.run_active = True
    player.enemy = spawn_enemy(player)

    # A free Void Bazooka shot is a valid way to start a run even when the
    # player has no normal ammo. Only show the overwhelmed state when there is
    # genuinely no way to attack.
    if player.get_spare() <= 0 and player.magazine <= 0 and player.void_bazooka_ammo <= 0:
        return [
            f"⚠️ You started with NO {player.ammo_name} ammo! The hoard smells blood...",
            f"Wave {player.wave}: **{player.enemy.name}** ({player.enemy.health} HP) - you're about to get overwhelmed!",
        ]

    cost = AMMO[player.ammo_name]["cost_per_attack"]
    bazooka_note = " • 💥 Free Bazooka shot ready" if player.void_bazooka_ammo > 0 else ""
    return [
        f"🧟 **Run started in {player.zone_name}** | Using **{player.ammo_name}** ({cost}/shot){bazooka_note}",
        f"Wave {player.wave}: **{player.enemy.name}** ({player.enemy.health} HP)",
    ]

def recover_stuck_run(player: Survivor) -> list[str]:
    """Repair an active run that was persisted without a current enemy.

    This can happen if a command/view is interrupted between changing run state
    and spawning/saving the encounter. The player stays on the same wave; we
    simply create a fresh enemy so the run can continue normally.
    """
    if not player.run_active:
        return []
    if player.enemy is not None:
        return []
    if player.wave < 1:
        player.wave = 1
    if player.zombies_remaining <= 0:
        player.zombies_remaining = max(3, player.wave + 2)
    player.enemy = spawn_enemy(player)
    return [
        f"🛠️ **Run recovered!** Your saved Wave **{player.wave}** had no active enemy.",
        f"🧟 **{player.enemy.name}** has spawned with **{player.enemy.health} HP**. Your run can continue!",
    ]


def action_help(player: Survivor) -> str:
    if player.enemy is None:
        return "Choose your next move."
    cost = AMMO[player.ammo_name]["cost_per_attack"]
    if player.enemy.is_bloater:
        return f"💣 BLOATER {player.enemy.bloater_timer} attacks left! {player.enemy.health} HP | 🔫 {player.ammo_name} {player.magazine}/{player.magazine_size} | 🧟 {player.enemy.name} 4 dmg"
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
    shield_used = False
    if player.void_shield_active:
        shield_bonus = void_perk_bonus(player, "Void Shield")
        damage = max(1, int(damage * (1.0 - shield_bonus)))
        player.void_shield_active = False
        player.void_shield_cooldown = VOID_PERKS["Void Shield"]["cooldown"]
        shield_used = True
    player.health = max(0, player.health - damage)
    if enemy.effects.get("freeze", 0):
        enemy.effects["freeze"] -= 1
        if enemy.effects["freeze"] <= 0:
            del enemy.effects["freeze"]
        result = [f"🧊 Frozen! {enemy.name} hits for {damage} dmg." + (f" 🛡️ Void Shield absorbed {int(shield_bonus*100)}%." if shield_used else "")]
    else:
        result = [f"💥 {enemy.name} hits for {damage} dmg." + (f" 🛡️ Void Shield absorbed {int(shield_bonus*100)}%." if shield_used else "")]
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
            base = {"bleed": 15, "burn": 20, "poison": 18, "freeze": 10}[effect]
            mod_name = {"bleed": "Bleed", "burn": "Incendiary", "poison": "Toxic", "freeze": "Frostbite"}[effect]
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
    # FIXED XP SCALING - Feedback #3
    # Wave scaling: +8% XP per wave - Wave 20 = 2.6x, Wave 30 = 3.4x
    wave_mult = 1.0 + (player.wave * 0.08)
    # Zone mult already in enemy.xp_reward, but add wave
    # Star XP bonus: +10% base +1% per level, max 25%
    xp_bonus_mult = 1.0 + player.xp_bonus
    # Final XP: base (already includes zone_mult) * wave_mult * xp_bonus
    xp_gain = int(enemy.xp_reward * wave_mult * xp_bonus_mult)
    
    money_gain = int(enemy.money_reward * player.scavenger_bonus)
    player.money += money_gain
    player.xp += xp_gain
    player.run_money_earned += money_gain
    player.run_xp_earned += xp_gain
    player.run_zombies_killed += 1
    # Void perk cooldowns are measured in zombies defeated.
    player.void_infusion_cooldown = max(0, player.void_infusion_cooldown - 1)
    player.void_shield_cooldown = max(0, player.void_shield_cooldown - 1)
    player.void_execution_cooldown = max(0, player.void_execution_cooldown - 1)

    # Void Essence is earned only in The Void. Normal kills have a 25% chance
    # to drop 1 Essence; Bloaters always give +4 Essence.
    if player.zone_name == "The Void":
        if enemy.is_bloater:
            essence_gain = VOID_ESSENCE_PER_VOID_BLOATER
        elif random.random() < VOID_ESSENCE_NORMAL_DROP_CHANCE:
            essence_gain = VOID_ESSENCE_PER_VOID_KILL
        else:
            essence_gain = 0
        if essence_gain > 0:
            player.void_essence += essence_gain
            messages_essence = f" • ◈ +{essence_gain} Void Essence"
        else:
            messages_essence = ""
    else:
        messages_essence = ""
    player.zombies_remaining -= 1
    messages = [f"✅ **{enemy.name} defeated!** +${money_gain} (Base ${enemy.money_reward} + {int((player.scavenger_bonus-1)*100)}% Loot) • +{xp_gain} XP (x{wave_mult:.1f} wave x{xp_bonus_mult:.1f} bonus){messages_essence}"] if player.scavenger_bonus > 1.0 else [f"✅ **{enemy.name} defeated!** +${money_gain} • +{xp_gain} XP (Base {enemy.xp_reward} x{wave_mult:.1f} wave x{xp_bonus_mult:.1f} bonus){messages_essence}"]
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
        # FIX: Wave bonus now also respects Loot upgrade
        # Check if this was a bloater solo wave - give extra reward
        was_bloater = enemy.is_bloater if hasattr(enemy, 'is_bloater') else False
        base_bonus = int(10 * player.wave * zone_for(player)["money_mult"])
        if was_bloater:
            base_bonus = int(base_bonus * 2.5)  # big reward for surviving bloater
        bonus = int(base_bonus * player.scavenger_bonus)
        player.money += bonus
        player.run_money_earned += bonus
        # Void waves 1-4 give no wave-clear Essence. From wave 5 onward,
        # every completed Void wave gives +1 Essence.
        if player.zone_name == "The Void" and player.wave >= VOID_ESSENCE_WAVE_START:
            player.void_essence += VOID_ESSENCE_PER_VOID_WAVE
            messages.append(f"◈ **Void Essence +{VOID_ESSENCE_PER_VOID_WAVE}** for clearing Void wave {player.wave}!")
        # Leaderboards record ONLY fully completed waves. Admin /setwave test runs
        # are deliberately excluded so high-wave testing cannot pollute real records.
        if not getattr(player, "admin_test_mode", False):
            record_completed_wave(player, player.wave)
        if getattr(player, "leaderboard_name", None) is None:
            player.leaderboard_name = "Survivor"
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + (10 if was_bloater else 5)
        player.wave += 1
        player.zombies_remaining = player.wave + 2
        # New enemy/boss encounter: the once-per-boss Bazooka restriction resets.
        player.void_bazooka_boss_fired = False
        player.health = min(player.max_health, player.health + (15 if was_bloater else 5))
        if was_bloater:
            messages.append(f"💣 **BLOATER SURVIVED! SOLO WAVE REWARD!** +${bonus} • +10 {player.ammo_name} ammo • +15 HP! Wave {player.wave} - {player.zombies_remaining} zombies! 🎉")
        else:
            messages.append(f"🌊 **Wave cleared!** +${bonus} • +5 {player.ammo_name} ammo • +5 HP. Wave {player.wave} - {player.zombies_remaining} zombies!")
    player.enemy = spawn_enemy(player)
    messages.append(f"🧟 **{player.enemy.name}** appears! {player.enemy.health} HP")
    return messages

def record_completed_wave(player: Survivor, completed_wave: int, guild_id: int | None = None, display_name: str | None = None) -> bool:
    """Record only fully completed waves. Returns True when a personal record improves."""
    if completed_wave <= 0:
        return False
    zone = player.zone_name
    old = int(player.highest_waves.get(zone, 0))
    if display_name:
        player.leaderboard_name = display_name[:32]
    if guild_id is not None:
        gid = str(guild_id)
        if gid not in player.leaderboard_guilds:
            player.leaderboard_guilds.append(gid)
    if completed_wave > old:
        player.highest_waves[zone] = int(completed_wave)
        player.highest_wave_dates[zone] = time.strftime("%Y-%m-%d")
        return True
    return False

def _leaderboard_rows(store: "GameStore", zone_name: str, guild_id: int | None = None) -> list[tuple[str, int, str]]:
    rows = []
    gid = str(guild_id) if guild_id is not None else None
    for player in store.players.values():
        wave = int(player.highest_waves.get(zone_name, 0))
        if wave <= 0:
            continue
        if gid is not None and gid not in {str(x) for x in player.leaderboard_guilds}:
            continue
        name = player.leaderboard_name or "Survivor"
        date = player.highest_wave_dates.get(zone_name, "—")
        rows.append((name, wave, date))
    rows.sort(key=lambda x: (-x[1], x[0].lower()))
    return rows

def leaderboard_rank(store: "GameStore", player: Survivor, zone_name: str, guild_id: int | None = None) -> int | None:
    target = int(player.highest_waves.get(zone_name, 0))
    if target <= 0:
        return None
    rows = _leaderboard_rows(store, zone_name, guild_id)
    for i, (name, wave, date) in enumerate(rows, 1):
        if name == player.leaderboard_name and wave == target and date == player.highest_wave_dates.get(zone_name, "—"):
            return i
    return None

def leaderboard_text(store: "GameStore", zone_name: str, guild_id: int | None = None, limit: int = 10) -> str:
    scope = "Server" if guild_id is not None else "Global"
    rows = _leaderboard_rows(store, zone_name, guild_id)[:limit]
    if not rows:
        return f"No completed-wave records yet for **{zone_name}**."
    lines = [f"**{scope} • {zone_name}**", ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, wave, date) in enumerate(rows, 1):
        icon = medals[i-1] if i <= 3 else f"**{i}.**"
        lines.append(f"{icon} **{name}** — Wave **{wave}** · {date}")
    return "\n".join(lines)

def personal_records_text(player: Survivor) -> str:
    if not player.highest_waves:
        return "**👤 My Records**\n\nNo completed-wave records yet. Start a run and finish a wave!"
    lines = ["**👤 My Records**", ""]
    for zone in ZONES:
        wave = int(player.highest_waves.get(zone, 0))
        if wave > 0:
            date = player.highest_wave_dates.get(zone, "—")
            lines.append(f"{zone}: **Wave {wave}** · {date}")
    return "\n".join(lines)


def take_action(player: Survivor, action: str, heal_item: str | None = None) -> list[str]:
    if not player.run_active or player.enemy is None:
        return ["Not in a run. Use Start run."]

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
    if action in {"void_infusion", "void_shield", "void_execution"}:
        perk_name = {"void_infusion":"Void Infusion", "void_shield":"Void Shield", "void_execution":"Void Execution"}[action]
        return activate_void_perk(player, perk_name)
    if action == "void_bazooka":
        # Dedicated single-target backup attack. It does not consume normal ammo,
        # does not use standard weapon damage, and does not receive standard damage upgrades.
        if player.zone_name != "The Void":
            return ["❌ The Void Bazooka can only be fired inside **The Void**."]
        if "Void Bazooka" not in player.void_weapons_owned:
            return ["🔒 You do not own the **Void Bazooka** yet. Buy it in the Void shop."]
        bazooka = VOID_WEAPONS["Void Bazooka"]
        is_boss_target = enemy.is_bloater or getattr(enemy, "is_void_boss", False)
        # A boss can only be hit by the Bazooka once per encounter.
        # Normal enemies can be hit repeatedly as long as the player can pay for ammo.
        if is_boss_target and player.void_bazooka_boss_fired:
            return ["⚠️ **Void Bazooka already fired at this boss!** Finish it with your primary weapon."]
        # One free round is loaded at the start of every Void run. After that,
        # each additional shot costs 10 Void Essence.
        if player.void_bazooka_ammo > 0:
            player.void_bazooka_ammo -= 1
            ammo_cost = 0
        elif player.void_essence >= VOID_BAZOOKA_AMMO_COST:
            player.void_essence -= VOID_BAZOOKA_AMMO_COST
            ammo_cost = VOID_BAZOOKA_AMMO_COST
        else:
            return [f"❌ **No Void Bazooka ammo!** Extra shots cost ◈{VOID_BAZOOKA_AMMO_COST} Void Essence."]
        if is_boss_target:
            player.void_bazooka_boss_fired = True
        void_level = max(0, min(VOID_UPGRADE_MAX, player.void_weapon_level))
        raw_damage = int(bazooka["damage"] + void_level * VOID_BAZOOKA_DAMAGE_PER_LEVEL)
        boss_mult = bazooka["level_10_boss_mult"] if void_level >= VOID_UPGRADE_MAX else bazooka["boss_mult"]
        multiplier = boss_mult if is_boss_target else 1.0
        perk_multiplier, perk_text = _consume_void_offense_bonus(player, enemy)
        bazooka_damage = int(raw_damage * multiplier * perk_multiplier)
        enemy.health = max(0, enemy.health - bazooka_damage)
        boss_text = f" ×{multiplier:.1f} BOSS DAMAGE" if is_boss_target else ""
        ammo_text = "FREE RUN AMMO" if ammo_cost == 0 else f"-◈{ammo_cost} Essence"
        perk_suffix = f" • ⚡ {perk_text}" if perk_text else ""
        messages.append(f"💥 **VOID BAZOOKA!** Hit **{enemy.name} for {bazooka_damage} dmg**! (Base {raw_damage}{boss_text}) ◈ Void Lvl {void_level}/{VOID_UPGRADE_MAX} • {ammo_text}{perk_suffix}")
        # No standard crit, pet, ammo effect, or standard weapon upgrade applies.
    elif action == "attack":
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
        perk_multiplier, perk_text = _consume_void_offense_bonus(player, enemy)
        total_dmg = 0
        total_crits = 0
        hit_details = []
        for shot_i in range(shots):
            dmg = int(player.weapon_damage * mod * perk_multiplier)
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
        perk_txt = f" ⚡ **{perk_text}**" if perk_text else ""
        if shots > 1:
            messages.append(f"🔫 **{shots}x** {player.weapon_name} Hit **{enemy.name} for {total_dmg}** ({'+'.join(map(str, hit_details))}){crit_txt}{magical_txt}{perk_txt} using {player.ammo_name} ({base_cost}x{shots}={cost} ammo){mod_txt}")
        else:
            messages.append(f"🔫 Hit **{enemy.name} for {total_dmg}**{crit_txt}{magical_txt}{perk_txt} using {player.ammo_name} ({cost}/shot){mod_txt}")
        
        # PET ATTACK CHECK
        if player.pet_chance > 0 and random.random() < player.pet_chance:
            pet_dmg = player.pet_damage
            enemy.health = max(0, enemy.health - pet_dmg)
            messages.append(f"🐺 **Wolf bites {enemy.name} for {pet_dmg} dmg!** ({player.pet_chance*100:.0f}% chance)")

        # BLOATER TICKING BOMB LOGIC - 5 attacks then 65% max HP explosion
        if enemy.is_bloater and enemy.health > 0:
            enemy.bloater_timer -= 1
            if enemy.bloater_timer > 0:
                messages.append(f"⏰ **BLOATER TICKING!** {enemy.bloater_timer} attacks left before it EXPLODES! 💣")
            else:
                # BOOM
                explode_dmg = int(player.max_health * BLOATER_EXPLODE_PCT)
                # Armor reduces explosion a bit
                explode_dmg = max(1, explode_dmg - player.armor_reduction)
                player.health = max(0, player.health - explode_dmg)
                messages.append(f"💥 **BLOATER EXPLODED!** Deals {explode_dmg} dmg! ({int(BLOATER_EXPLODE_PCT*100)}% of max HP!)")
                # Bloater dies in explosion
                enemy.health = 0
                if player.health <= 0:
                    # Player dies from explosion
                    player.health = player.max_health
                    player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
                    player.magazine = 0
                    player.run_active = False
                    player.enemy = None
                    msgs = [
                        f"💀 **BLOATER BLEW YOU UP!** {get_cocky_line()}",
                        f"⏰ You had {BLOATER_FUSE} attacks and failed. {explode_dmg} dmg explosion ended you.",
                        f"🌊 Waves: {player.wave} | 🧟 Kills: {player.run_zombies_killed} | 💰 ${player.run_money_earned} | ✨ {player.run_xp_earned} XP"
                    ]
                    msgs.extend(_grant_end_of_run_rewards(player))
                    return messages + msgs

        effect = ammo_data["effect"]
        chances = {"bleed": 0.25, "burn": 0.30, "freeze": 0.25, "poison": 0.40, "shock": 0.20}
        if effect and random.random() < chances[effect]:
            durations = {"bleed": 3, "burn": 3, "freeze": 4, "poison": 5, "shock": 1}
            enemy.effects[effect] = durations[effect]
            messages.append(f"💥 {player.ammo_name} procs **{effect}**!")
            # Shock also does instant 20 dmg
            if effect == "shock":
                shock_dmg = int(20 * ammo_modifier(player, "Shock"))
                enemy.health = max(0, enemy.health - shock_dmg)
                messages.append(f"⚡ Shock deals {shock_dmg} dmg!")
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
        messages.append(f"🏃 {get_flee_line()} Kept ${player.run_money_earned} • {player.run_xp_earned} XP this run. Full healed!")
        messages.extend(_grant_end_of_run_rewards(player))
        return messages
    else:
        return ["Attack, reload, heal, or flee."]
    if enemy.health <= 0:
        messages.extend(_finish_enemy(player))
    else:
        messages.extend(_enemy_damage(player))
    return messages

def buy_ammo_boxes(player: Survivor, ammo_type: str, boxes: int = 1) -> list[str]:
    """Bulk buy ammo boxes - like Fisher bait +1 +10 +100 +1000"""
    if player.run_active:
        return ["⚠️ Can't shop in a run! Flee first."]
    if ammo_type not in AMMO:
        ammo_type = player.ammo_name
    box_price = AMMO[ammo_type]["box_price"]
    box_amount = AMMO[ammo_type]["box_amount"]
    total_price = box_price * boxes
    total_rounds = box_amount * boxes
    if player.money < total_price:
        return [f"❌ Need ${total_price} for {boxes}x {ammo_type} box ({total_rounds} rounds), you have ${player.money}"]
    player.money -= total_price
    player.spare_ammo[ammo_type] = player.spare_ammo.get(ammo_type, 0) + total_rounds
    if boxes == 1:
        return [f"📦 Bought {ammo_type} box +{total_rounds}. {player.spare_ammo[ammo_type]} spare now. ${player.money} left."]
    else:
        return [f"📦 Bought {boxes}x {ammo_type} boxes +{total_rounds} rounds. {player.spare_ammo[ammo_type]} spare now. ${player.money} left."]

def buy_item(player: Survivor, item: str) -> list[str]:
    if player.run_active:
        return ["⚠️ Can't shop in a run! Flee first."]
    if item == "ammo":
        return buy_ammo_boxes(player, player.ammo_name, 1)
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
    # Two-stage scaling: strong early/mid-game growth, then a flatter late-game curve.
    # The first 10 upgrade levels keep the existing progression. From level 10
    # onward, each stat uses a gentler multiplier so late-game upgrades stay
    # expensive without becoming effectively unreachable.
    early_mults = {
        "damage": 1.50,
        "health": 1.40,
        "mag": 1.50,
        "crit": 1.60,
        "armor": 1.50,
        "scavenger": 1.65,
    }
    late_mults = {
        "damage": 1.28,
        "health": 1.25,
        "mag": 1.28,
        "crit": 1.28,
        "armor": 1.28,
        "scavenger": 1.25,
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

    # cost = base * early_mult^min(count, 10) * late_mult^max(count-10, 0)
    early_levels = min(count, 10)
    late_levels = max(count - 10, 0)
    return int(
        bases[stat]
        * (early_mults[stat] ** early_levels)
        * (late_mults[stat] ** late_levels)
    )



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
        return [f"💰 Loot bonus → **+{int((player.scavenger_bonus-1)*100)}%** (+10% per lvl). ${player.money} left. Lvl {player.scavenger_upgrades}"]
    else:
        # Refund if unknown
        player.money += cost
        return [f"❓ Unknown upgrade '{stat}'. Try: health, damage, mag, crit, armor, scavenger"]



def get_star_upgrade_cost(player: Survivor, stat: str) -> int:
    """Star upgrades: 5 to unlock, then pattern 3,3,4,4,5,5,6,6..."""
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
    # Lvl 0 = unlock cost 5
    if lvl == 0:
        return 5
    # After unlock, pattern 3,3,4,4,5,5,6,6...
    # lvl 1 -> 3, lvl 2 -> 3, lvl 3 -> 4, lvl 4 -> 4, lvl 5 ->5, lvl6->5 etc
    # index = lvl-1, cost = 3 + (index // 2)
    index = lvl - 1
    cost = 3 + (index // 2)
    return cost



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




def status(player: Survivor, display_name: str = "Survivor") -> str:
    """Fisher-style inventory with real player name wired in"""
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
    
    ammo_icons = {"Standard": "🔹", "Bleed": "🩸", "Incendiary": "🔥", "Frostbite": "❄️", "Toxic": "☠️", "Shock": "⚡"}
    
    ammo_lines = []
    for ammo_name in ["Standard", "Bleed", "Incendiary", "Frostbite", "Toxic", "Shock"]:
        count = player.spare_ammo.get(ammo_name, 0)
        if ammo_name in player.owned_ammo or count > 0 or ammo_name == player.ammo_name:
            icon = ammo_icons.get(ammo_name, "🔹")
            ammo_lines.append(f"{count} {icon} {ammo_name}")
    
    if not ammo_lines:
        ammo_lines = ["0 🔹 No ammo"]
    
    lines = [
        f"**Inventory of {display_name}**",
        f"",
        f"Balance: **${player.money}** | Stars: **{player.stars}**",
        f"Level **{player.level}** — {earned}/{needed} XP to next level.",
        f"Equipped Weapon: **{player.weapon_name}**",
        f"Equipped Ammo type: **{player.ammo_name}**",
        f"Mag size: **{player.magazine_size}** ({player.magazine}/{player.magazine_size} loaded)",
        f"Zone: **{player.zone_name}**",
        f"",
        f"**Ammo inventory:**",
    ]
    lines.extend(ammo_lines)
    lines.append(f"")
    lines.append(f"**Meds inventory:**")
    lines.append(f"{player.full_restores} ✨ Full Restore")
    lines.append(f"{player.painkillers} 💊 Painkillers")
    
    return "\n".join(lines)

def status_detailed(player: Survivor, display_name: str = "Survivor") -> str:
    """Detailed view for inventory/stats menu"""
    earned, needed = level_progress(player)
    lines = [
        f"**📊 {display_name} — Lvl {player.level}**",
        f"❤️ HP: {player.health}/{player.max_health} (+{player.health_upgrades*20})",
        f"💥 Dmg: {player.weapon_damage} (+{player.damage_upgrades*3}) | 📦 Mag: {player.magazine_size} (+{player.mag_upgrades})",
        f"🎯 Crit: {int(player.crit_chance*100)}% | 🛡️ Armor: -{player.armor_reduction} | 💰 Loot: +{int((player.scavenger_bonus-1)*100)}%",
        f"💰 ${player.money} | ⭐ {player.stars} | ✨ {player.xp} XP ({earned}/{needed})",
        f"🔫 {player.weapon_name} [{player.ammo_name}] | 📦 Spare: {player.get_spare()}",
         f"◈ Void Essence: {player.void_essence} | Void Bazooka: {'Owned' if 'Void Bazooka' in player.void_weapons_owned else 'Locked'} | Void Lvl {player.void_weapon_level}/10",
        f"🎒 Ammo: {', '.join([f'{k}:{v}' for k,v in player.spare_ammo.items() if v>0]) or 'Empty'}",
        f"💊 Painkillers: {player.painkillers} | ✨ Restores: {player.full_restores}",
        f"🗺️ Zone: {player.zone_name} | Guns: {', '.join(player.owned_weapons)}",
    ]
    return "\n".join(lines)

def get_status(player: Survivor, display_name: str = "Survivor") -> str:
    return status(player, display_name)

def get_detailed_status(player: Survivor, display_name: str = "Survivor") -> str:
    return status_detailed(player, display_name)





class GameStore:
    """CONSTANT SAVE - every player action triggers an instant persistent save.

    A PostgreSQL/load failure is never treated as an empty game.
    """
    def __init__(self):
        self.players = {}
        self._save_count = 0
        self.load()

    @staticmethod
    def _player_dict(player):
        try:
            return player.to_dict()
        except Exception:
            return asdict(player)

    def get(self, user_id: int):
        key = str(user_id)
        if key not in self.players:
            player = Survivor()
            if not save_player(key, self._player_dict(player)):
                raise RuntimeError(f"Could not persist new player {key}")
            self.players[key] = player
            self._save_count += 1
        return self.players[key]

    def save_one(self, key: str):
        key = str(key)
        p = self.players.get(key)
        if p is None:
            return
        if not save_player(key, self._player_dict(p)):
            raise RuntimeError(f"Could not save player {key}")
        self._save_count += 1

    async def save_one_async(self, key: str):
        import asyncio
        key = str(key)
        p = self.players.get(key)
        if p is None:
            return
        ok = await asyncio.to_thread(save_player, key, self._player_dict(p))
        if not ok:
            raise RuntimeError(f"Could not save player {key}")
        self._save_count += 1

    def save(self):
        if not self.players:
            print("[AUTOSAVE] REFUSING SAVE: no players are loaded")
            return
        failed = []
        for k, p in self.players.items():
            if not save_player(k, self._player_dict(p)):
                failed.append(k)
        if failed:
            raise RuntimeError(f"Failed to save players: {', '.join(failed[:10])}")
        self._save_count += len(self.players)
        print(f"[AUTOSAVE] Saved {len(self.players)} players to Postgres - all safe")

    async def save_async(self):
        import asyncio
        if not self.players:
            print("[AUTOSAVE] REFUSING ASYNC SAVE: no players are loaded")
            return
        items = list(self.players.items())
        results = await asyncio.gather(
            *(asyncio.to_thread(save_player, k, self._player_dict(p)) for k, p in items),
            return_exceptions=True,
        )
        failed = []
        for (k, _), result in zip(items, results):
            if result is not True:
                failed.append(k)
        if failed:
            raise RuntimeError(f"Failed to save players: {', '.join(failed[:10])}")
        self._save_count += len(items)

    def load(self):
        # Critical: never convert a database failure into {}.
        verify_storage()
        raw = load_all_players()
        loaded = {}
        for k, v in raw.items():
            if not isinstance(v, dict):
                raise RuntimeError(f"Invalid stored data for player {k}")
            try:
                loaded[str(k)] = Survivor.from_dict(v)
            except Exception as e:
                raise RuntimeError(f"Corrupt player save {k}: {e}") from e
        self.players = loaded
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
    def __init__(self, user_id: int, store: GameStore, display_name: str = "Survivor", timeout: float = 180):
        # Handle case where display_name is passed as timeout positionally (old bug compat)
        if isinstance(display_name, (int, float)) and timeout == 180:
            # display_name is actually timeout value
            timeout = float(display_name)
            display_name = "Survivor"
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.store = store
        self.display_name = display_name
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            try:
                await interaction.response.send_message("Not your game! Use /zombie", ephemeral=True)
            except:
                pass
            return False
        return True


class RunEndedView(PlayerView):
    """End of run screen that disappears when you press any button"""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", end_embed: discord.Embed = None):
        super().__init__(user_id, store, display_name, timeout=180)
        self.end_embed = end_embed

        btn_continue = discord.ui.Button(label="🏠 Main Menu", style=discord.ButtonStyle.success, row=0)
        async def cont_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            name = getattr(self, "display_name", "Survivor")
            await interaction.response.edit_message(content=status(p, display_name=name), embed=None, view=ZombieMenuView(self.user_id, self.store, display_name=name))
        btn_continue.callback = cont_cb
        self.add_item(btn_continue)

        # Shopping is preparation-only. Do not even expose the Shop button while
        # a run is active; the purchase functions also enforce this server-side.
        if not is_active:
            btn_shop = discord.ui.Button(label="🛒 Shop", style=discord.ButtonStyle.primary, row=0)
            async def shop_cb(interaction: discord.Interaction):
                p = self.store.get(self.user_id)
                if p.run_active:
                    await interaction.response.edit_message(
                        content=None,
                        embed=combat_embed(p, ["🚫 **Shopping is locked during a run.** Flee or finish the run first."]),
                        view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")),
                    )
                    return
                hub = ShopHubView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
                await interaction.response.edit_message(content=hub.get_shop_text(p), embed=None, view=hub)
            btn_shop.callback = shop_cb
            self.add_item(btn_shop)

        btn_again = discord.ui.Button(label="▶️ Start Run", style=discord.ButtonStyle.primary, row=0)
        async def again_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            msgs = start_run(p)
            self.store.save()
            embed = combat_embed(p, msgs)
            await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
        btn_again.callback = again_cb
        self.add_item(btn_again)



class LeaderboardView(PlayerView):
    """Compact leaderboard browser: Global, Server, and personal records."""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", guild_id: int | None = None, zone_name: str | None = None, timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        self.guild_id = guild_id
        self.zone_name = zone_name or store.get(user_id).zone_name
        self.clear_items()

        zone_options = list(ZONES.keys())
        for idx, zone in enumerate(zone_options[:5]):
            btn = discord.ui.Button(label=("📍 " if zone == self.zone_name else "") + zone[:70], style=discord.ButtonStyle.primary if zone == self.zone_name else discord.ButtonStyle.secondary, row=0)
            async def zone_cb(interaction, zn=zone):
                p = self.store.get(self.user_id)
                p.leaderboard_name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
                if interaction.guild:
                    if str(interaction.guild.id) not in p.leaderboard_guilds:
                        p.leaderboard_guilds.append(str(interaction.guild.id))
                self.zone_name = zn
                await interaction.response.edit_message(content=self.render_global(p), view=LeaderboardView(self.user_id, self.store, self.display_name, self.guild_id, zn))
            btn.callback = zone_cb
            self.add_item(btn)

        # The sixth zone is not a button if Discord row capacity is tight; The Void is shown via navigation buttons below.
        if len(zone_options) > 5:
            zn = zone_options[5]
            btn = discord.ui.Button(label=("📍 " if zn == self.zone_name else "") + zn[:70], style=discord.ButtonStyle.primary if zn == self.zone_name else discord.ButtonStyle.secondary, row=1)
            async def zone6_cb(interaction, zn=zn):
                p = self.store.get(self.user_id)
                p.leaderboard_name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
                if interaction.guild and str(interaction.guild.id) not in p.leaderboard_guilds:
                    p.leaderboard_guilds.append(str(interaction.guild.id))
                await interaction.response.edit_message(content=self.render_global(p, zn), view=LeaderboardView(self.user_id, self.store, self.display_name, self.guild_id, zn))
            btn.callback = zone6_cb
            self.add_item(btn)

        global_btn = discord.ui.Button(label="🌎 Global", style=discord.ButtonStyle.success, row=2)
        async def global_cb(interaction):
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=self.render_global(p), view=LeaderboardView(self.user_id,self.store,self.display_name,self.guild_id,self.zone_name))
        global_btn.callback=global_cb; self.add_item(global_btn)

        server_btn = discord.ui.Button(label="🏠 Server", style=discord.ButtonStyle.success, row=2, disabled=self.guild_id is None)
        async def server_cb(interaction):
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=self.render_server(p), view=LeaderboardView(self.user_id,self.store,self.display_name,self.guild_id,self.zone_name))
        server_btn.callback=server_cb; self.add_item(server_btn)

        records_btn = discord.ui.Button(label="👤 My Records", style=discord.ButtonStyle.success, row=2)
        async def records_cb(interaction):
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=personal_records_text(p), view=LeaderboardView(self.user_id,self.store,self.display_name,self.guild_id,self.zone_name))
        records_btn.callback=records_cb; self.add_item(records_btn)

        back_btn=discord.ui.Button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=3)
        async def back_cb(interaction):
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=status(p, display_name=self.display_name), embed=None, view=ZombieMenuView(self.user_id,self.store,display_name=self.display_name))
        back_btn.callback=back_cb; self.add_item(back_btn)

    def render_global(self, player=None, zone_name=None):
        p=player or self.store.get(self.user_id); zn=zone_name or self.zone_name
        return leaderboard_text(self.store, zn, None)

    def render_server(self, player=None):
        p=player or self.store.get(self.user_id)
        if self.guild_id is None:
            return "**🏠 Server Leaderboard**\n\nUse this inside a Discord server."
        return leaderboard_text(self.store, self.zone_name, self.guild_id)


class ZombieMenuView(PlayerView):
    def __init__(self, user_id: int, store, display_name: str = "Survivor"):
        super().__init__(user_id, store, display_name)
        self.display_name = display_name
        player = self.store.get(user_id)
        
        is_active = getattr(player, 'run_active', False) and player.enemy is not None
        label = f"▶️ Continue Run (W{player.wave})" if is_active else "▶️ Start Run"

        # ROW 0: Start + Shop (primary actions)
        btn_start = discord.ui.Button(label=label, style=discord.ButtonStyle.success, row=0)
        async def start_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            if p.run_active:
                if p.enemy is None:
                    msgs = recover_stuck_run(p)
                    self.store.save_one(str(self.user_id))
                    embed = combat_embed(p, msgs)
                    await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                    return
                embed = combat_embed(p, [f"🔄 Resumed your run! Wave {p.wave} | {p.zombies_remaining} zombies left"])
                await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                return
            msgs = start_run(p)
            self.store.save()
            embed = combat_embed(p, msgs)
            await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
        btn_start.callback = start_cb
        self.add_item(btn_start)

        btn_shop = discord.ui.Button(label="🛒 Shop", style=discord.ButtonStyle.primary, row=0)
        async def shop_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            hub = ShopHubView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            await interaction.response.edit_message(content=hub.get_shop_text(p), embed=None, view=hub)
        btn_shop.callback = shop_cb
        self.add_item(btn_shop)

        # ROW 1: Zones
        btn_zones = discord.ui.Button(label="🗺️ Zones", style=discord.ButtonStyle.secondary, row=1)
        async def zones_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            lines = [
                "**Zone Shop**",
                "",
                f"Your level: **{p.level}** | Current: **{p.zone_name}**",
                "---",
            ]
            for zn, zd in ZONES.items():
                unlocked = p.level >= zd["min_level"]
                sel = " ← SELECTED" if zn == p.zone_name else ""
                status_icon = "✅" if unlocked else f"🔒 Lvl {zd['min_level']}"
                lines.append(f"🗺️ **{zn}** {status_icon}{sel}")
                lines.append(f"{zd['desc']} | Money x{zd['money_mult']} | XP x{zd['xp_mult']}")
                lines.append("")
            await interaction.response.edit_message(content="\n".join(lines), embed=None, view=ZoneView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
        btn_zones.callback = zones_cb
        self.add_item(btn_zones)

        btn_lb = discord.ui.Button(label="🏆 Leaderboards", style=discord.ButtonStyle.primary, row=1)
        async def lb_cb(interaction: discord.Interaction):
            p=self.store.get(self.user_id)
            name=getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            p.leaderboard_name=name[:32]
            gid=interaction.guild.id if interaction.guild else None
            if gid is not None and str(gid) not in p.leaderboard_guilds:
                p.leaderboard_guilds.append(str(gid))
            self.store.save_one(str(self.user_id))
            await interaction.response.edit_message(content=leaderboard_text(self.store, p.zone_name, None), embed=None, view=LeaderboardView(self.user_id,self.store,display_name=name,guild_id=gid,zone_name=p.zone_name))
        lb_cb.__name__ = "leaderboards_cb"
        self.add_item(btn_lb)
        btn_lb.callback = lb_cb

        # Ammo and permanent upgrades are accessed through the main Shop now.
        # They are intentionally not shown as separate buttons on the main menu.

        # ROW 2: Refresh
        btn_refresh = discord.ui.Button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)
        async def refresh_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            name = getattr(self, "display_name", "Survivor")
            try:
                name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
                self.display_name = name
            except:
                pass
            await interaction.response.edit_message(content=status(p, display_name=name), embed=None, view=ZombieMenuView(self.user_id, self.store, display_name=name))
        btn_refresh.callback = refresh_cb
        self.add_item(btn_refresh)


class CombatView(PlayerView):
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        # Void-only controls stay out of ordinary-zone combat instead of
        # cluttering the UI with buttons that cannot be used there.
        player = self.store.get(user_id)
        if player.zone_name != "The Void":
            for item in list(self.children):
                if getattr(item, "label", "") in {
                    "💥 Void Bazooka", "⚡ Infusion", "🛡️ Shield", "☠️ Execution"
                }:
                    self.remove_item(item)

    @discord.ui.button(label="🔫 Attack", style=discord.ButtonStyle.danger, row=0)
    async def attack(self, interaction: discord.Interaction, _b):
        # Defer immediately to avoid "This interaction failed" - we have 3s limit
        await interaction.response.defer()
        player = self.store.get(self.user_id)
        msgs = take_action(player, "attack")
        # Async save - doesn't block event loop, prevents DB lock timeouts
        await self.store.save_one_async(str(self.user_id))
        if not player.run_active:
            embed = discord.Embed(
                title="☠️ Run Ended",
                description="\n".join(msgs),
                color=discord.Color.red()
            )
            embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
            embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
            embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
            embed.set_footer(text=f"HP restored to {player.max_health}/{player.max_health} • Press any button to continue")
            await interaction.edit_original_response(content=None, embed=embed, view=RunEndedView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), end_embed=embed))
        else:
            embed = combat_embed(player, msgs)
            await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="💥 Void Bazooka", style=discord.ButtonStyle.secondary, row=1)
    async def void_bazooka(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        player=self.store.get(self.user_id)
        msgs=take_action(player, "void_bazooka")
        await self.store.save_one_async(str(self.user_id))
        if not player.run_active:
            embed=discord.Embed(title="☠️ Run Ended", description="\n".join(msgs), color=discord.Color.red())
            embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
            embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
            embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
            embed.set_footer(text=f"HP restored to {player.max_health}/{player.max_health} • Press any button to continue")
            await interaction.edit_original_response(content=None, embed=embed, view=RunEndedView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), end_embed=embed))
        else:
            embed=combat_embed(player,msgs)
            await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor")))

    @discord.ui.button(label="⚡ Infusion", style=discord.ButtonStyle.success, row=2)
    async def void_infusion(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        player=self.store.get(self.user_id); msgs=take_action(player, "void_infusion")
        await self.store.save_one_async(str(self.user_id))
        await interaction.edit_original_response(content=None, embed=combat_embed(player, msgs), view=CombatView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor")))

    @discord.ui.button(label="🛡️ Shield", style=discord.ButtonStyle.success, row=2)
    async def void_shield(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        player=self.store.get(self.user_id); msgs=take_action(player, "void_shield")
        await self.store.save_one_async(str(self.user_id))
        await interaction.edit_original_response(content=None, embed=combat_embed(player, msgs), view=CombatView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor")))

    @discord.ui.button(label="☠️ Execution", style=discord.ButtonStyle.success, row=2)
    async def void_execution(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        player=self.store.get(self.user_id); msgs=take_action(player, "void_execution")
        await self.store.save_one_async(str(self.user_id))
        await interaction.edit_original_response(content=None, embed=combat_embed(player, msgs), view=CombatView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor")))

    @discord.ui.button(label="🔄 Reload", style=discord.ButtonStyle.primary, row=0)
    async def reload(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        player = self.store.get(self.user_id)
        msgs = take_action(player, "reload")
        await self.store.save_one_async(str(self.user_id))
        if not player.run_active:
            embed = discord.Embed(
                title="☠️ Run Ended",
                description="\n".join(msgs),
                color=discord.Color.red()
            )
            embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
            embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
            embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
            embed.set_footer(text=f"HP restored to {player.max_health}/{player.max_health} • Press any button to continue")
            await interaction.edit_original_response(content=None, embed=embed, view=RunEndedView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), end_embed=embed))
        else:
            embed = combat_embed(player, msgs)
            await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="💊 Heal", style=discord.ButtonStyle.success, row=0)
    async def heal(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        embed = combat_embed(player, ["Choose heal item"])
        await interaction.response.edit_message(content=None, embed=embed, view=HealView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="🏃 Flee", style=discord.ButtonStyle.secondary, row=0)
    async def flee(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        player = self.store.get(self.user_id)
        msgs = take_action(player, "flee")
        await self.store.save_one_async(str(self.user_id))
        if not player.run_active:
            embed = discord.Embed(
                title="🏃 Escaped!",
                description="\n".join(msgs),
                color=discord.Color.blue()
            )
            embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
            embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
            embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
            embed.set_footer(text=f"HP restored to {player.max_health}/{player.max_health} • Press any button to continue")
            await interaction.edit_original_response(content=None, embed=embed, view=RunEndedView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), end_embed=embed))
        else:
            embed = combat_embed(player, msgs)
            await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="🏠 Main Menu", style=discord.ButtonStyle.secondary, row=3)
    async def main_menu(self, interaction: discord.Interaction, _b):
        # Always provide a safe exit from combat. This does not abandon the run;
        # it simply returns to the menu so the player can resume it later.
        await interaction.response.defer()
        player = self.store.get(self.user_id)
        if player.run_active and player.enemy is None:
            msgs = recover_stuck_run(player)
            self.store.save_one(str(self.user_id))
        else:
            msgs = []
        name = getattr(self, "display_name", "Survivor")
        content = status(player, display_name=name)
        if msgs:
            content += "\n\n" + "\n".join(msgs)
        await interaction.edit_original_response(content=content, embed=None, view=ZombieMenuView(self.user_id, self.store, display_name=name))

    @discord.ui.button(label="🛠️ Recover Run", style=discord.ButtonStyle.secondary, row=3)
    async def recover_run(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        player = self.store.get(self.user_id)
        msgs = recover_stuck_run(player)
        if not msgs:
            msgs = ["✅ Your run is already healthy — an enemy is active."]
        await self.store.save_one_async(str(self.user_id))
        embed = combat_embed(player, msgs)
        await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))




class HealView(PlayerView):
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.clear_items()
        pk_left = 3 - player.painkillers_used_this_run
        pk_label = f"💊 Painkillers ({player.painkillers}x - {pk_left} left this run)"
        pk_btn = discord.ui.Button(label=pk_label[:80], style=discord.ButtonStyle.success, row=0)
        async def pk_cb(interaction):
            try:
                await interaction.response.defer()
            except:
                pass
            p=self.store.get(self.user_id)
            msgs=take_action(p,"heal","painkillers")
            try:
                await self.store.save_one_async(str(self.user_id))
            except:
                self.store.save_one(str(self.user_id))
            embed = combat_embed(p, msgs)
            try:
                await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            except Exception as e:
                print(f"Heal CB error: {e}")
        pk_btn.callback = pk_cb
        self.add_item(pk_btn)

        fr_left = 1 - player.full_restores_used_this_run
        fr_label = f"✨ Full restore ({player.full_restores}x - {fr_left} left)"
        fr_btn = discord.ui.Button(label=fr_label[:80], style=discord.ButtonStyle.success, row=0)
        async def fr_cb(interaction):
            try:
                await interaction.response.defer()
            except:
                pass
            p=self.store.get(self.user_id)
            msgs=take_action(p,"heal","full_restore")
            try:
                await self.store.save_one_async(str(self.user_id))
            except:
                self.store.save_one(str(self.user_id))
            embed = combat_embed(p, msgs)
            try:
                await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            except Exception as e:
                print(f"Heal CB error: {e}")
        fr_btn.callback = fr_cb
        self.add_item(fr_btn)

        back_btn = discord.ui.Button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=1)
        async def back_cb(interaction):
            try:
                p=self.store.get(self.user_id)
                embed = combat_embed(p, [action_help(p)])
                await interaction.response.edit_message(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            except Exception as e:
                print(f"Heal back error: {e}")
                try:
                    await interaction.response.defer()
                    p=self.store.get(self.user_id)
                    embed = combat_embed(p, [action_help(p)])
                    await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                except:
                    pass
        back_btn.callback = back_cb
        self.add_item(back_btn)




class ShopHubView(PlayerView):
    """Fisher-style Shop Categories hub"""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        # No auto buttons, we add manually via decorators + callbacks below

    def get_shop_text(self, player):
        lines = [
            "**Shop Categories**",
            "",
            f"🔫 **/shop weapons** - Shop for different weapons.",
            f"🧪 **/shop ammo** - Purchase ammo and special rounds.",
            f"💊 **/shop meds** - Purchase meds for heals.",
            f"⬆️ **/shop upgrades** - Purchase various permanent upgrades.",
            f"⭐ **/shop stars** - Shop for star prestige upgrades.",
            f"◈ **Void Upgrades** - Void weapon progression and the Void Bazooka.",
            "",
            f"Balance: **${player.money}** | Stars: **{player.stars}**",
            f"Level **{player.level}** | Zone: **{player.zone_name}**",
        ]
        return "\n".join(lines)

    @discord.ui.button(label="🔫", style=discord.ButtonStyle.primary, row=0)
    async def weapons_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        if p.run_active:
            await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            return
        await interaction.response.edit_message(content=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="🧪", style=discord.ButtonStyle.primary, row=0)
    async def ammo_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        if p.run_active:
            await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Ammo shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            return
        await interaction.response.edit_message(content=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="💊", style=discord.ButtonStyle.primary, row=0)
    async def meds_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        if p.run_active:
            await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Med shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            return
        await interaction.response.edit_message(content=MedsShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=MedsShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.primary, row=0)
    async def upgrades_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        if p.run_active:
            await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            return
        await interaction.response.edit_message(content=UpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=UpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.primary, row=1)
    async def stars_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        if p.run_active:
            await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            return
        await interaction.response.edit_message(content=StarUpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=StarUpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="◈", style=discord.ButtonStyle.primary, row=1)
    async def void_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        if p.run_active:
            await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            return
        view = VoidUpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
        await interaction.response.edit_message(content=None, embed=view.get_shop_embed(p), view=view)

    @discord.ui.button(label="Return", style=discord.ButtonStyle.secondary, row=2)
    async def ret(self, interaction: discord.Interaction, _b):
        name = getattr(self, "display_name", "Survivor")
        # Try to get real name from interaction
        try:
            name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            self.display_name = name
        except:
            pass
        p=self.store.get(self.user_id)
        await interaction.response.edit_message(content=status(p, display_name=name), embed=None, view=ZombieMenuView(self.user_id, self.store, display_name=name))

# Keep backward compat alias
ShopView = ShopHubView


class WeaponShopView(PlayerView):
    """Fisher-style Weapon Shop"""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_weapon: str = None, timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.selected_weapon = selected_weapon or player.weapon_name
        self.clear_items()

        for i, wname in enumerate(["Pistol", "Shotgun", "Rifle", "SMG", "Sawed-Off", "Tactical Sniper"]):
            if wname not in WEAPONS:
                continue
            owned = wname in player.owned_weapons
            is_sel = wname == self.selected_weapon
            emoji = "🔫"
            if is_sel:
                label = f"{emoji} {wname} ✅"
                style = discord.ButtonStyle.success
            elif owned:
                label = f"{emoji} {wname}"
                style = discord.ButtonStyle.primary
            else:
                w = WEAPONS[wname]
                label = f"{emoji} {wname} 🔒 Lvl{w['unlock_level']}"
                style = discord.ButtonStyle.secondary
            btn = discord.ui.Button(label=label[:80], style=style, row=0 if i < 3 else 1)
            async def cb(interaction, wn=wname):
                p=self.store.get(self.user_id)
                if wn not in p.owned_weapons:
                    msgs = buy_item(p, wn)
                    self.store.save()
                content = self.get_shop_text(p, selected_override=wn, extra_msgs=None)
                await interaction.response.edit_message(content=content, view=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_weapon=wn))
            btn.callback = cb
            self.add_item(btn)

        # Buy button for selected
        wdata = WEAPONS.get(self.selected_weapon, {"price": 0})
        buy_label = f"Buy {self.selected_weapon} ${wdata['price']}"
        if self.selected_weapon in player.owned_weapons:
            buy_label = f"Equip {self.selected_weapon}"
        btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.primary, row=2)
        async def buy_cb(interaction):
            p=self.store.get(self.user_id)
            msgs = buy_item(p, self.selected_weapon)
            self.store.save()
            content = self.get_shop_text(p, selected_override=self.selected_weapon, extra_msgs=msgs)
            await interaction.response.edit_message(content=content, view=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_weapon=self.selected_weapon))
        btn_buy.callback = buy_cb
        self.add_item(btn_buy)

        hub_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=3)
        async def hub_cb(interaction):
            p=self.store.get(self.user_id)
            hub = ShopHubView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            await interaction.response.edit_message(content=hub.get_shop_text(p), view=hub)
        hub_btn.callback = hub_cb
        self.add_item(hub_btn)

        main_btn = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=3)
        async def main_cb(interaction):
            name = getattr(self, "display_name", "Survivor")
            try:
                name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            except:
                pass
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=status(p, display_name=name), view=ZombieMenuView(self.user_id, self.store, display_name=name))
        main_btn.callback = main_cb
        self.add_item(main_btn)

    def get_shop_text(self, player, selected_override=None, extra_msgs=None):
        sel = selected_override or getattr(self, "selected_weapon", player.weapon_name)
        lines = []
        if extra_msgs:
            lines.extend(extra_msgs)
            lines.append("")
        lines.append("**Weapon Shop**")
        lines.append("")
        lines.append("Weapons are permanent and increase your damage.")
        lines.append("")
        lines.append(f"Your balance: **${player.money:,}**")
        lines.append(f"Selected: 🔫 **{sel}**")
        lines.append("---")
        for wname in ["Pistol", "Shotgun", "Rifle", "SMG", "Sawed-Off", "Tactical Sniper"]:
            if wname not in WEAPONS:
                continue
            w = WEAPONS[wname]
            owned = wname in player.owned_weapons
            is_sel = wname == sel
            marker = " ← SELECTED" if is_sel else ""
            status_str = "Owned" if owned else f"LOCKED Level {w['unlock_level']} - ${w['price']}"
            if owned:
                status_str = f"Owned - Dmg {w.get('damage', '?')} | Mag {w.get('mag_size', w.get('mag', '?'))}"
            lines.append(f"🔫 **{wname}**{marker}")
            lines.append(f"{status_str}")
            lines.append(f"{w.get('desc','')}")
            lines.append("")
        locked = [w for w in WEAPONS if w not in player.owned_weapons and w != "Pistol"]
        if locked:
            nxt = locked[0]
            lines.append(f"Next Weapon: 🔫 **{nxt}**")
            lines.append(f"UNLOCKED AT LEVEL {WEAPONS[nxt]['unlock_level']}!")
            lines.append("")
        lines.append(f"Selected: **{sel}** - ${WEAPONS.get(sel, {'price':0})['price']}")
        return "\n".join(lines)


class AmmoShopView(PlayerView):
    """Fisher Bait Shop clone - list + select + bulk buy +1 +10 +100 +1000"""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_ammo: str = None, timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.selected_ammo = selected_ammo or player.ammo_name
        
        self.clear_items()
        
        emoji_map = {"Standard": "🔹", "Bleed": "🩸", "Incendiary": "🔥", "Frostbite": "❄️", "Toxic": "☠️", "Shock": "⚡"}
        for i, ammo_name in enumerate(AMMO):
            emoji = emoji_map.get(ammo_name, "🔹")
            spare = player.spare_ammo.get(ammo_name, 0)
            owned = ammo_name in player.owned_ammo
            is_sel = ammo_name == self.selected_ammo
            if is_sel:
                label = f"{emoji} {ammo_name} ({spare}) ✅"
                style = discord.ButtonStyle.success
            elif owned:
                label = f"{emoji} {ammo_name} ({spare})"
                style = discord.ButtonStyle.primary
            else:
                label = f"{emoji} {ammo_name} 🔒"
                style = discord.ButtonStyle.secondary
            btn = discord.ui.Button(label=label[:80], style=style, row=0 if i < 3 else 1)
            async def cb(interaction, an=ammo_name):
                p=self.store.get(self.user_id)
                if p.run_active:
                    await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Ammo shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                    return
                msgs = []
                success = True
                if an not in p.owned_ammo:
                    msgs = equip_ammo(p, an)
                    # Check if equip failed (message starts with ❌ or Need or unlocks)
                    if msgs and any(x.startswith('❌') or 'Need $' in x or 'unlocks at level' in x.lower() for x in msgs):
                        success = False
                    self.store.save()
                else:
                    # Already owned, try to equip
                    msgs = equip_ammo(p, an)
                    if msgs and any('Already using' not in m and ('❌' in m or 'can\'t' in m.lower()) for m in msgs):
                        # If it's already using, it's success
                        if any('Already using' in m for m in msgs):
                            success = True
                        else:
                            # Check if error
                            if any(m.startswith('❌') for m in msgs):
                                success = False
                    self.store.save()
                
                if success:
                    self.selected_ammo = an
                    content = self.get_shop_text(p, extra_msgs=msgs)
                    await interaction.response.edit_message(content=content, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_ammo=an))
                else:
                    # Equip failed, keep old selection but show error
                    content = self.get_shop_text(p, extra_msgs=msgs)
                    await interaction.response.edit_message(content=content, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_ammo=self.selected_ammo))
            btn.callback = cb
            self.add_item(btn)
        
        box_price = AMMO[self.selected_ammo]["box_price"]
        for qty, row in [(1,2), (10,2), (100,3), (1000,3)]:
            total = box_price * qty
            label = f"+{qty} (${total:,})"
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary, row=row)
            async def bulk_cb(interaction, q=qty, ammo=self.selected_ammo):
                p=self.store.get(self.user_id)
                if p.run_active:
                    await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Ammo shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                    return
                msgs = buy_ammo_boxes(p, ammo, q)
                self.store.save()
                content = self.get_shop_text(p, selected_override=ammo, extra_msgs=msgs)
                await interaction.response.edit_message(content=content, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_ammo=ammo))
            btn.callback = bulk_cb
            self.add_item(btn)
        
        hub_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=4)
        async def hub_cb(interaction):
            p=self.store.get(self.user_id)
            hub = ShopHubView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            await interaction.response.edit_message(content=hub.get_shop_text(p), view=hub)
        hub_btn.callback = hub_cb
        self.add_item(hub_btn)

        main_btn = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=4)
        async def main_cb(interaction):
            name = getattr(self, "display_name", "Survivor")
            try:
                name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            except:
                pass
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=status(p, display_name=name), view=ZombieMenuView(self.user_id, self.store, display_name=name))
        main_btn.callback = main_cb
        self.add_item(main_btn)

    def get_shop_text(self, player, selected_override=None, extra_msgs=None):
        sel = selected_override or getattr(self, "selected_ammo", player.ammo_name)
        ammo_icons = {"Standard": "🔹", "Bleed": "🩸", "Incendiary": "🔥", "Frostbite": "❄️", "Toxic": "☠️", "Shock": "⚡"}
        lines = []
        if extra_msgs:
            lines.extend(extra_msgs)
            lines.append("")
        lines.append("**Ammo Shop**")
        lines.append("")
        lines.append(f"Ammo is consumed **PER SHOT** so make sure to stock up.")
        lines.append("")
        lines.append(f"Your balance: **${player.money:,}**")
        lines.append(f"Selected: {ammo_icons.get(sel,'🔹')} **{sel}** ({player.spare_ammo.get(sel,0)})")
        lines.append("---")
        for ammo_name in AMMO:
            ammo = AMMO[ammo_name]
            spare = player.spare_ammo.get(ammo_name, 0)
            owned = ammo_name in player.owned_ammo or ammo_name == "Standard"
            icon = ammo_icons.get(ammo_name, "🔹")
            if not owned:
                lines.append(f"{icon} **{ammo_name} ({spare})**")
                lines.append(f"LOCKED - Level {ammo['unlock_level']} + ${ammo['price']} to unlock. {ammo['desc']} - {ammo['cost_per_attack']}/shot")
                lines.append("")
                continue
            sel_marker = " ← SELECTED" if ammo_name == sel else ""
            lines.append(f"{icon} **{ammo_name} ({spare})**{sel_marker}")
            lines.append(f"{ammo['desc']} | Cost {ammo['cost_per_attack']}/shot | Box ${ammo['box_price']} for {ammo['box_amount']} rounds")
            lines.append("")
        locked = [a for a in AMMO if a not in player.owned_ammo]
        if locked:
            next_ammo = locked[0]
            lines.append(f"Next Ammo: {ammo_icons.get(next_ammo,'🔹')} **{next_ammo}**")
            lines.append(f"UNLOCKED AT LEVEL {AMMO[next_ammo]['unlock_level']}!")
            lines.append("")
        lines.append(f"Selected box: **{sel}** - ${AMMO[sel]['box_price']} per box ({AMMO[sel]['box_amount']} rounds)")
        return "\n".join(lines)


class MedsShopView(PlayerView):
    """Fisher-style Meds Shop with bulk buy"""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_med: str = "painkillers", timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.selected_med = selected_med
        self.clear_items()

        # Med type selector
        meds = [("painkillers", "💊 Painkillers", player.painkillers, 15), ("full_restore", "✨ Full Restore", player.full_restores, 80)]
        for i, (mid, mname, count, price) in enumerate(meds):
            is_sel = mid == self.selected_med
            label = f"{mname} ({count}) {'✅' if is_sel else ''}"
            style = discord.ButtonStyle.success if is_sel else discord.ButtonStyle.primary
            btn = discord.ui.Button(label=label[:80], style=style, row=0)
            async def cb(interaction, m=mid):
                self.selected_med = m
                p=self.store.get(self.user_id)
                content = self.get_shop_text(p, selected_override=m)
                await interaction.response.edit_message(content=content, view=MedsShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_med=m))
            btn.callback = cb
            self.add_item(btn)

        # Bulk buy for selected med
        sel_price = 15 if self.selected_med == "painkillers" else 80
        for qty, row in [(1,1), (10,1), (100,2), (1000,2)]:
            total = sel_price * qty
            # Painkillers give +2 per purchase, so adjust label
            label = f"+{qty} (${total:,})"
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary, row=row)
            async def bulk_cb(interaction, q=qty, med=self.selected_med):
                p = self.store.get(self.user_id)
                if p.run_active:
                    await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Med shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                    return
                total_cost = (15 if med == "painkillers" else 80) * q

                if p.money < total_cost:
                    msgs = [f"❌ Need ${total_cost} for {q}x {med}, you have ${p.money}"]
                else:
                    # The old callback purchased the items once with buy_item()
                    # and then purchased them a second time in a second loop.
                    # This performs exactly one bulk transaction.
                    p.money -= total_cost
                    if med == "painkillers":
                        p.painkillers += 2 * q
                        bought = 2 * q
                        msgs = [f"💊 Bought {q}x Painkillers +{bought} | Now {p.painkillers}x | ${p.money} left"]
                    else:
                        p.full_restores += q
                        bought = q
                        msgs = [f"✨ Bought {q}x Full Restore +{bought} | Now {p.full_restores}x | ${p.money} left"]
                    self.store.save_one(str(self.user_id))
                content = self.get_shop_text(p, selected_override=med, extra_msgs=msgs)
                await interaction.response.edit_message(content=content, view=MedsShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_med=med))
            btn.callback = bulk_cb
            self.add_item(btn)

        hub_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=3)
        async def hub_cb(interaction):
            p=self.store.get(self.user_id)
            hub = ShopHubView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            await interaction.response.edit_message(content=hub.get_shop_text(p), view=hub)
        hub_btn.callback = hub_cb
        self.add_item(hub_btn)

        main_btn = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=3)
        async def main_cb(interaction):
            name = getattr(self, "display_name", "Survivor")
            try:
                name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            except:
                pass
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=status(p, display_name=name), view=ZombieMenuView(self.user_id, self.store, display_name=name))
        main_btn.callback = main_cb
        self.add_item(main_btn)

    def get_shop_text(self, player, selected_override=None, extra_msgs=None):
        sel = selected_override or getattr(self, "selected_med", "painkillers")
        lines = []
        if extra_msgs:
            lines.extend(extra_msgs)
            lines.append("")
        lines.append("**Meds Shop**")
        lines.append("")
        lines.append("Meds are consumed **PER RUN** so make sure to stock up.")
        lines.append("")
        lines.append(f"Your balance: **${player.money:,}**")
        sel_name = "Painkillers" if sel == "painkillers" else "Full Restore"
        sel_count = player.painkillers if sel == "painkillers" else player.full_restores
        sel_icon = "💊" if sel == "painkillers" else "✨"
        lines.append(f"Selected: {sel_icon} **{sel_name}** ({sel_count})")
        lines.append("---")
        lines.append(f"💊 **Painkillers ({player.painkillers})** {'← SELECTED' if sel == 'painkillers' else ''}")
        lines.append("Heals 40 HP in run. Max 3 uses per run. +2 per purchase ($15).")
        lines.append("")
        lines.append(f"✨ **Full Restore ({player.full_restores})** {'← SELECTED' if sel == 'full_restore' else ''}")
        lines.append("Fully heals HP in run. Max 1 use per run. +1 per purchase ($80).")
        lines.append("")
        lines.append(f"Selected: **{sel_name}** - ${15 if sel == 'painkillers' else 80} each")
        return "\n".join(lines)


class UpgradeView(PlayerView):
    """Fisher-style Upgrades Shop"""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_up: str = "health", timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.selected_up = selected_up
        self.clear_items()

        upgrades = [
            ("health", "❤️ Health", "+20 HP"),
            ("damage", "💥 Damage", "+3 Dmg"),
            ("mag", "📦 Mag", "+1 Mag"),
            ("crit", "🎯 Crit", "+2%"),
            ("armor", "🛡️ Armor", "-2 Dmg"),
            ("scavenger", "💰 Loot", "+10%"),
        ]
        for i, (uid, uname, plus) in enumerate(upgrades):
            is_sel = uid == self.selected_up
            cost = get_upgrade_cost(player, uid)
            lvl = getattr(player, f"{uid}_upgrades", 0) if uid != "scavenger" else player.scavenger_upgrades
            label = f"{uname.split()[1]} ({lvl}) {'✅' if is_sel else ''}"
            style = discord.ButtonStyle.success if is_sel else discord.ButtonStyle.primary
            btn = discord.ui.Button(label=label[:80], style=style, row=0 if i < 3 else 1)
            async def cb(interaction, u=uid):
                self.selected_up = u
                p=self.store.get(self.user_id)
                content = self.get_shop_text(p, selected_override=u)
                await interaction.response.edit_message(content=content, view=UpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_up=u))
            btn.callback = cb
            self.add_item(btn)

        # Single buy button for selected upgrade - no bulk as requested
        cost = get_upgrade_cost(player, self.selected_up)
        buy_label = f"Buy {self.selected_up.capitalize()} ${cost}"
        btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.success, row=2)
        async def buy_cb(interaction):
            # FIX #1: Prevent double-click race - locks per user
            if self.user_id in _purchase_locks:
                try:
                    await interaction.response.defer()
                except:
                    pass
                return
            _purchase_locks.add(self.user_id)
            try:
                p=self.store.get(self.user_id)
                msgs = upgrade(p, self.selected_up)
                self.store.save()
                content = self.get_shop_text(p, selected_override=self.selected_up, extra_msgs=msgs)
                await interaction.response.edit_message(content=content, view=UpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_up=self.selected_up))
            finally:
                _purchase_locks.discard(self.user_id)
        btn_buy.callback = buy_cb
        self.add_item(btn_buy)

        hub_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=3)
        async def hub_cb(interaction):
            p=self.store.get(self.user_id)
            hub = ShopHubView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            await interaction.response.edit_message(content=hub.get_shop_text(p), view=hub)
        hub_btn.callback = hub_cb
        self.add_item(hub_btn)

        main_btn = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=4)
        async def main_cb(interaction):
            name = getattr(self, "display_name", "Survivor")
            try:
                name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            except:
                pass
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=status(p, display_name=name), view=ZombieMenuView(self.user_id, self.store, display_name=name))
        main_btn.callback = main_cb
        self.add_item(main_btn)

    def get_shop_text(self, player, selected_override=None, extra_msgs=None):
        sel = selected_override or getattr(self, "selected_up", "health")
        lines = []
        if extra_msgs:
            lines.extend(extra_msgs)
            lines.append("")
        lines.append("**Money Upgrades Shop**")
        lines.append("")
        lines.append("Upgrades are permanent and make you stronger.")
        lines.append("")
        lines.append(f"Your balance: **${player.money:,}** | Stars: **{player.stars}**")
        # Selected
        emoji_map = {"health": "❤️", "damage": "💥", "mag": "📦", "crit": "🎯", "armor": "🛡️", "scavenger": "💰"}
        lines.append(f"Selected: {emoji_map.get(sel,'⬆️')} **{sel.capitalize()}**")
        lines.append("---")
        for uid, uname, plus in [("health","❤️ Health","+20 HP"),("damage","💥 Damage","+3 Dmg"),("mag","📦 Mag","+1 Mag"),("crit","🎯 Crit","+2% Crit"),("armor","🛡️ Armor","-2 Dmg taken"),("scavenger","💰 Loot","+10% Money")]:
            cost = get_upgrade_cost(player, uid)
            lvl = getattr(player, f"{uid}_upgrades", 0) if uid != "scavenger" else player.scavenger_upgrades
            sel_mark = " ← SELECTED" if uid == sel else ""
            lines.append(f"{uname} ({lvl}){sel_mark}")
            lines.append(f"{plus} per level - Cost ${cost} - Lvl {lvl}")
            lines.append("")
        lines.append(f"Next: {sel} Lvl {getattr(player, f'{sel}_upgrades', 0)+1 if sel != 'scavenger' else player.scavenger_upgrades+1} for ${get_upgrade_cost(player, sel)}")
        return "\n".join(lines)


class StarUpgradeView(PlayerView):
    """Fisher-style Star Upgrades - same layout"""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_star: str = "dodge", timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.selected_star = selected_star
        self.clear_items()

        stars = [
            ("dodge", "💨 Dodge", "30% cap"),
            ("magical", "✨ Magical", "20% cap"),
            ("medic", "💊 Medic", "7% cap"),
            ("pet", "🐺 Pet", "10% cap"),
            ("xp", "✨ XP Gain", "25% cap"),
        ]
        for i, (sid, sname, cap) in enumerate(stars):
            is_sel = sid == self.selected_star
            cost = get_star_upgrade_cost(player, sid)
            # get lvl
            if sid == "dodge":
                lvl = player.star_dodge_upgrades; cur = player.dodge_chance*100
            elif sid == "magical":
                lvl = player.star_magical_upgrades; cur = player.magical_bullet_chance*100
            elif sid == "medic":
                lvl = player.star_medic_upgrades; cur = player.medic_chance*100
            elif sid == "pet":
                lvl = player.star_pet_upgrades; cur = player.pet_chance*100
            else:
                lvl = player.star_xp_upgrades; cur = player.xp_bonus*100
            label = f"{sname.split()[1]} {cur:.0f}% {'✅' if is_sel else ''}"
            style = discord.ButtonStyle.success if is_sel else discord.ButtonStyle.primary
            btn = discord.ui.Button(label=label[:80], style=style, row=0 if i < 3 else 1)
            async def cb(interaction, s=sid):
                self.selected_star = s
                p=self.store.get(self.user_id)
                content = self.get_shop_text(p, selected_override=s)
                await interaction.response.edit_message(content=content, view=StarUpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_star=s))
            btn.callback = cb
            self.add_item(btn)

        # Single buy button for selected star - no bulk as requested
        cost = get_star_upgrade_cost(player, self.selected_star)
        buy_label = f"Buy {self.selected_star.capitalize()} ⭐{cost}"
        btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.success, row=2)
        async def buy_cb(interaction):
            # FIX #1: Prevent double-click race for star upgrades
            if self.user_id in _purchase_locks:
                try:
                    await interaction.response.defer()
                except:
                    pass
                return
            _purchase_locks.add(self.user_id)
            try:
                p=self.store.get(self.user_id)
                msgs = upgrade_star(p, self.selected_star)
                self.store.save()
                content = self.get_shop_text(p, selected_override=self.selected_star, extra_msgs=msgs)
                await interaction.response.edit_message(content=content, view=StarUpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_star=self.selected_star))
            finally:
                _purchase_locks.discard(self.user_id)
        btn_buy.callback = buy_cb
        self.add_item(btn_buy)

        hub_btn = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=3)
        async def hub_cb(interaction):
            p=self.store.get(self.user_id)
            hub = ShopHubView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            await interaction.response.edit_message(content=hub.get_shop_text(p), view=hub)
        hub_btn.callback = hub_cb
        self.add_item(hub_btn)

        main_btn = discord.ui.Button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=4)
        async def main_cb(interaction):
            name = getattr(self, "display_name", "Survivor")
            try:
                name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            except:
                pass
            p=self.store.get(self.user_id)
            await interaction.response.edit_message(content=status(p, display_name=name), view=ZombieMenuView(self.user_id, self.store, display_name=name))
        main_btn.callback = main_cb
        self.add_item(main_btn)

    def get_shop_text(self, player, selected_override=None, extra_msgs=None):
        sel = selected_override or getattr(self, "selected_star", "dodge")
        lines = []
        if extra_msgs:
            lines.extend(extra_msgs)
            lines.append("")
        lines.append("**⭐ STAR PRESTIGE Shop**")
        lines.append("")
        lines.append("Rare prestige perks from leveling up. Stars are earned from waves.")
        lines.append("")
        lines.append(f"Your stars: **⭐{player.stars}** | Balance: **${player.money:,}** | Level **{player.level}**")
        emoji_map = {"dodge":"💨","magical":"✨","medic":"💊","pet":"🐺","xp":"✨"}
        lines.append(f"Selected: {emoji_map.get(sel,'⭐')} **{sel.capitalize()}** → Next: ⭐{get_star_upgrade_cost(player, sel)}")
        lines.append("---")
        descs = {
            "dodge": "Dodge enemy attacks completely. 10% base +0.5% per lvl, cap 30%. Makes you untouchable late game.",
            "magical": "Chance to NOT consume ammo on attack. 5% base +0.5% per lvl, cap 20%. Saves bullets with expensive ammo.",
            "medic": "Chance to not consume meds + chance for med drop on wave clear. 2% base +0.25% per lvl, cap 7%. Best for sustain.",
            "pet": "Wolf companion bites zombies for 25% weapon dmg. 5% base +1% per lvl, cap 10% chance. Extra free damage.",
            "xp": "Bonus XP from all sources. 10% base +1% per lvl, cap 25%. Levels you faster for more stars.",
        }
        for sid, sname, cap in [("dodge","💨 Dodge","30%"),("magical","✨ Magical Bullet","20%"),("medic","💊 Medic","7%"),("pet","🐺 Wolf Pet","10%"),("xp","✨ XP Boost","25%")]:
            if sid == "dodge":
                lvl = player.star_dodge_upgrades; cur = player.dodge_chance*100
                per = "+0.5% per level"
            elif sid == "magical":
                lvl = player.star_magical_upgrades; cur = player.magical_bullet_chance*100
                per = "+0.5% per level"
            elif sid == "medic":
                lvl = player.star_medic_upgrades; cur = player.medic_chance*100
                per = "+0.25% per level"
            elif sid == "pet":
                lvl = player.star_pet_upgrades; cur = player.pet_chance*100
                per = "+1% per level"
            else:
                lvl = player.star_xp_upgrades; cur = player.xp_bonus*100
                per = "+1% per level"
            sel_mark = " ← SELECTED" if sid == sel else ""
            cost = get_star_upgrade_cost(player, sid)
            lines.append(f"{sname} (Lvl {lvl}) - **{cur:.1f}%**{sel_mark}")
            lines.append(f"{descs[sid]}")
            lines.append(f"Cap {cap} | {per} | Cost ⭐{cost} | Next Lvl {lvl+1}")
            lines.append("")
        lines.append(f"Selected: **{sel.capitalize()}** → Buy for ⭐{get_star_upgrade_cost(player, sel)}")
        return "\n".join(lines)




class VoidUpgradeView(PlayerView):
    """Clean, compact Void progression page."""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float = 180):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.clear_items()

        owned = "Void Bazooka" in player.void_weapons_owned
        lvl = max(0, min(VOID_UPGRADE_MAX, player.void_weapon_level))
        if lvl >= VOID_UPGRADE_MAX:
            baz_label = "💥 Bazooka MAX"
        else:
            baz_label = "💥 Void Bazooka" + (" ✅" if owned else " 🔒")
        btn = discord.ui.Button(label=baz_label, style=discord.ButtonStyle.success if owned else discord.ButtonStyle.primary, row=0)
        async def bazooka_select(interaction):
            p=self.store.get(self.user_id); msgs=[]
            if "Void Bazooka" not in p.void_weapons_owned:
                if p.level < VOID_WEAPONS["Void Bazooka"]["unlock_level"]:
                    msgs=[f"🔒 Unlocks at Level {VOID_WEAPONS['Void Bazooka']['unlock_level']}." ]
                elif p.zone_name != "The Void":
                    msgs=["🗺️ Travel to **The Void** to obtain it."]
                elif p.money < VOID_WEAPONS["Void Bazooka"]["price"]:
                    msgs=[f"❌ Need ${VOID_WEAPONS['Void Bazooka']['price']:,}."]
                else:
                    p.money -= VOID_WEAPONS["Void Bazooka"]["price"]
                    p.void_weapons_owned.append("Void Bazooka")
                    msgs=["💥 **Void Bazooka acquired!**"]
                    self.store.save()
            view=VoidUpgradeView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))
            await interaction.response.edit_message(content=None, embed=view.get_shop_embed(p,msgs), view=view)
        btn.callback=bazooka_select; self.add_item(btn)

        cost=get_void_upgrade_cost(player)
        up_label = "⬆️ Bazooka MAX" if lvl >= VOID_UPGRADE_MAX else f"⬆️ Upgrade Bazooka • ◈{cost:,}"
        btn_up=discord.ui.Button(label=up_label, style=discord.ButtonStyle.success, row=1, disabled=(lvl>=VOID_UPGRADE_MAX))
        async def upgrade_cb(interaction):
            if self.user_id in _purchase_locks:
                await interaction.response.defer(); return
            _purchase_locks.add(self.user_id)
            try:
                p=self.store.get(self.user_id); msgs=upgrade_void_weapon(p); self.store.save()
                view=VoidUpgradeView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))
                await interaction.response.edit_message(content=None, embed=view.get_shop_embed(p,msgs), view=view)
            finally:
                _purchase_locks.discard(self.user_id)
        btn_up.callback=upgrade_cb; self.add_item(btn_up)

        perk_specs=[("Void Infusion","⚡"),("Void Shield","🛡️"),("Void Execution","☠️")]
        for perk_name,icon in perk_specs:
            plvl=void_perk_level(player,perk_name)
            if plvl>=10:
                label=f"{icon} {perk_name.split()[-1]} MAX"
            else:
                label=f"{icon} {perk_name.split()[-1]} L{plvl} • ◈{get_void_perk_cost(player,perk_name)}"
            b=discord.ui.Button(label=label[:80], style=discord.ButtonStyle.success if plvl else discord.ButtonStyle.primary, row=2)
            async def perk_cb(interaction,pn=perk_name):
                if self.user_id in _purchase_locks:
                    await interaction.response.defer(); return
                _purchase_locks.add(self.user_id)
                try:
                    p=self.store.get(self.user_id); msgs=upgrade_void_perk(p,pn); self.store.save()
                    view=VoidUpgradeView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))
                    await interaction.response.edit_message(content=None, embed=view.get_shop_embed(p,msgs), view=view)
                finally:
                    _purchase_locks.discard(self.user_id)
            b.callback=perk_cb; self.add_item(b)

        back=discord.ui.Button(label="⬅️ Back",style=discord.ButtonStyle.secondary,row=3)
        async def back_cb(interaction):
            p=self.store.get(self.user_id); hub=ShopHubView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))
            await interaction.response.edit_message(content=hub.get_shop_text(p),embed=None,view=hub)
        back.callback=back_cb; self.add_item(back)

        main=discord.ui.Button(label="🏠 Main Menu",style=discord.ButtonStyle.secondary,row=3)
        async def main_cb(interaction):
            p=self.store.get(self.user_id); name=getattr(interaction.user,"display_name",None) or getattr(interaction.user,"global_name",None) or interaction.user.name
            await interaction.response.edit_message(content=status(p,display_name=name),embed=None,view=ZombieMenuView(self.user_id,self.store,display_name=name))
        main.callback=main_cb; self.add_item(main)

    def get_shop_embed(self, player, extra_msgs=None):
        baz=VOID_WEAPONS["Void Bazooka"]
        lvl=max(0,min(VOID_UPGRADE_MAX,player.void_weapon_level))
        dmg=baz["damage"]+lvl*VOID_BAZOOKA_DAMAGE_PER_LEVEL
        boss_mult=baz["level_10_boss_mult"] if lvl>=VOID_UPGRADE_MAX else baz["boss_mult"]
        embed=discord.Embed(title="🌑 The Void",description=f"◈ **Essence:** {player.void_essence:,}\n💰 **Balance:** ${player.money:,}\n🎚️ **Level:** {player.level}",color=discord.Color.dark_purple())
        if extra_msgs:
            embed.add_field(name="Result",value="\n".join(extra_msgs)[:1024],inline=False)
        owned="Void Bazooka" in player.void_weapons_owned
        if not owned:
            baz_text=f"🔒 Unlocks at **Level {baz['unlock_level']}**\n💰 Purchase: **${baz['price']:,}**"
        else:
            baz_text=f"Level **{lvl}/{VOID_UPGRADE_MAX}** • Damage **{dmg}**\n💀 Bloaters/Bosses: **×{boss_mult:.1f}**\n🎁 1 free shot/run • ◈{VOID_BAZOOKA_AMMO_COST}/extra shot"
        embed.add_field(name="💥 Void Bazooka",value=baz_text,inline=False)
        perk_lines=[]
        for pn,icon in (("Void Infusion","⚡"),("Void Shield","🛡️"),("Void Execution","☠️")):
            plvl=void_perk_level(player,pn); spec=VOID_PERKS[pn]; bonus=int(void_perk_bonus(player,pn)*100)
            if pn=="Void Infusion": effect=f"+{bonus}% next attack"
            elif pn=="Void Shield": effect=f"-{bonus}% next hit"
            else: effect=f"+{bonus}% vs ≤50% HP"
            cost="MAX" if plvl>=10 else f"◈{get_void_perk_cost(player,pn)}"
            perk_lines.append(f"{icon} **{pn.split()[-1]}** L{plvl}/10 • {effect} • Next {cost}")
        embed.add_field(name="⚡ Void Perks",value="\n".join(perk_lines),inline=False)
        embed.set_footer(text="Perks work in The Void and can modify the Bazooka.")
        return embed

    def get_shop_text(self, player, extra_msgs=None):
        # Kept for compatibility with older callers.
        e=self.get_shop_embed(player,extra_msgs)
        parts=[f"**{e.title}**",e.description or ""]
        for f in e.fields: parts.append(f"**{f.name}**\n{f.value}")
        if e.footer.text: parts.append(e.footer.text)
        return "\n\n".join(parts)


def get_void_upgrade_cost(player: Survivor) -> int:
    """Escalating Void Essence cost for the 10-level Void weapon track."""
    costs = [10, 20, 35, 55, 80, 110, 150, 200, 275, 375]
    lvl=max(0,min(VOID_UPGRADE_MAX,player.void_weapon_level))
    return costs[lvl] if lvl < VOID_UPGRADE_MAX else 999999999


def upgrade_void_weapon(player: Survivor) -> list[str]:
    if player.run_active:
        return ["⚠️ Can't upgrade during a run! Flee first."]
    if player.level < VOID_WEAPONS["Void Bazooka"]["unlock_level"]:
        return [f"🔒 Void upgrades unlock at level {VOID_WEAPONS['Void Bazooka']['unlock_level']}."]
    if "Void Bazooka" not in player.void_weapons_owned:
        return ["🔒 Buy the **Void Bazooka** first."]
    if player.void_weapon_level >= VOID_UPGRADE_MAX:
        return [f"🔥 **Void Bazooka is MAXED at Level 10!** ×{VOID_WEAPONS["Void Bazooka"]["level_10_boss_mult"]:.1f} boss damage is active."]
    cost=get_void_upgrade_cost(player)
    if player.void_essence < cost:
        return [f"❌ Need ◈{cost} Void Essence; you have ◈{player.void_essence}."]
    player.void_essence -= cost
    player.void_weapon_level += 1
    dmg=VOID_WEAPONS["Void Bazooka"]["damage"] + player.void_weapon_level*VOID_BAZOOKA_DAMAGE_PER_LEVEL
    if player.void_weapon_level == VOID_UPGRADE_MAX:
        return [f"🔥 **VOID BAZOOKA LEVEL 10!** Damage → **{dmg}** | Boss/Bloater damage → **×{VOID_WEAPONS["Void Bazooka"]["level_10_boss_mult"]:.1f}**! ◈{player.void_essence} Essence left."]
    return [f"◈ **Void Bazooka upgraded to Level {player.void_weapon_level}!** Damage → **{dmg}** (+{VOID_BAZOOKA_DAMAGE_PER_LEVEL}) | ◈{player.void_essence} Essence left."]


class ZoneView(PlayerView):
    def __init__(self, user_id, store, display_name: str = "Survivor", timeout: float = 180):
        super().__init__(user_id, store, display_name)
        for i, zone_name in enumerate(ZONES):
            btn = discord.ui.Button(label=zone_name, style=discord.ButtonStyle.primary, row=i//2)
            async def cb(interaction, zn=zone_name):
                p=self.store.get(self.user_id); msgs=change_zone(p,zn); self.store.save()
                await interaction.response.edit_message(content="\n".join(msgs)+"\n\n"+status(p, display_name=getattr(self, "display_name", "Survivor")), view=ZoneView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            btn.callback = cb
            self.add_item(btn)
    @discord.ui.button(label="🏠 Main menu", style=discord.ButtonStyle.secondary, row=2)
    async def main(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(content=status(self.store.get(self.user_id), display_name=getattr(self, "display_name", "Survivor")), view=ZombieMenuView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))




class StarterBot(discord.Client):

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        # Keep the global commands registered, but guild-sync them in on_ready
        # so Discord servers see new slash commands immediately instead of
        # waiting for Discord's global command propagation.
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} global commands")
        try:
            self.loop.create_task(background_autosave())
            print("[AUTOSAVE] Background autosave every 60s STARTED - double protection")
        except Exception as e:
            print(f"[AUTOSAVE] Failed start: {e}")

bot = StarterBot()

@bot.event
async def on_ready():
    # Guild-scoped slash commands update immediately. This mirrors the global
    # command tree into every server the bot is currently in, which makes new
    # commands such as /give admin appear without the usual global-command
    # propagation delay.
    if getattr(bot, "_guild_commands_synced", False):
        return

    total = 0
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            total += len(synced)
            print(f"[SLASH] Synced {len(synced)} commands to guild {guild.id} ({guild.name})")
        except Exception as e:
            print(f"[SLASH] Failed guild sync for {guild.id} ({guild.name}): {e}")

    bot._guild_commands_synced = True
    print(f"[SLASH] Guild command sync complete: {total} commands across {len(bot.guilds)} guild(s)")


@bot.event
async def on_guild_join(guild: discord.Guild):
    # Also sync immediately if the bot is added to a new server later.
    try:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"[SLASH] Synced {len(synced)} commands to new guild {guild.id} ({guild.name})")
    except Exception as e:
        print(f"[SLASH] Failed new-guild sync for {guild.id} ({guild.name}): {e}")


@bot.tree.command(name="zombie", description="Zombie Survival - main menu")
async def zombie_cmd(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        player = game_store.get(interaction.user.id)
        name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
        player.leaderboard_name = name[:32]
        if interaction.guild and str(interaction.guild.id) not in player.leaderboard_guilds:
            player.leaderboard_guilds.append(str(interaction.guild.id))
        recovery_msgs = []
        if player.run_active and player.enemy is None:
            recovery_msgs = recover_stuck_run(player)
            print(f"[RECOVERY] /zombie repaired player {interaction.user.id}: {recovery_msgs}")
        game_store.save_one(str(interaction.user.id))
        print(f"[CMD] /zombie by {interaction.user.id} name={name} level={player.level}")
        content = status(player, display_name=name)
        if recovery_msgs:
            content += "\n\n" + "\n".join(recovery_msgs)
        view = ZombieMenuView(interaction.user.id, game_store, display_name=name)
        await interaction.followup.send(content=content, view=view)
        print(f"[CMD] /zombie sent OK for {interaction.user.id}")
    except Exception as e:
        print(f"[CMD ERROR] /zombie failed: {e}")
        import traceback
        traceback.print_exc()
        try:
            await interaction.followup.send(f"❌ Bot error: {e}\n```{traceback.format_exc()[:1500]}```", ephemeral=True)
        except:
            pass

@bot.tree.command(name="leaderboard", description="View Zombie Survival leaderboards")
@app_commands.describe(scope="Global, server, or personal records", zone="Zone to view")
@app_commands.choices(scope=[app_commands.Choice(name="Global",value="global"),app_commands.Choice(name="Server",value="server"),app_commands.Choice(name="My Records",value="personal")])
async def leaderboard_cmd(interaction: discord.Interaction, scope: str = "global", zone: str | None = None):
    await interaction.response.defer()
    p=game_store.get(interaction.user.id)
    name=getattr(interaction.user,"display_name",None) or getattr(interaction.user,"global_name",None) or interaction.user.name
    p.leaderboard_name=name[:32]
    gid=interaction.guild.id if interaction.guild else None
    if gid is not None and str(gid) not in p.leaderboard_guilds:
        p.leaderboard_guilds.append(str(gid))
    if zone not in ZONES:
        zone=p.zone_name
    game_store.save_one(str(interaction.user.id))
    if scope == "personal":
        content=personal_records_text(p)
    elif scope == "server":
        content=leaderboard_text(game_store,zone,gid) if gid is not None else "**🏠 Server Leaderboard**\n\nUse this command inside a server."
    else:
        content=leaderboard_text(game_store,zone,None)
    await interaction.followup.send(content=content,view=LeaderboardView(interaction.user.id,game_store,display_name=name,guild_id=gid,zone_name=zone))

@bot.tree.command(name="zombie_start", description="Start a zombie run")
async def zombie_start_cmd(interaction: discord.Interaction):
    await interaction.response.defer()  # Prevent timeout - fixes "didn't respond in time"
    player = game_store.get(interaction.user.id)
    player.leaderboard_name = (getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name)[:32]
    if interaction.guild and str(interaction.guild.id) not in player.leaderboard_guilds:
        player.leaderboard_guilds.append(str(interaction.guild.id))
    game_store.save_one(str(interaction.user.id))
    if player.run_active:
        recovery_msgs = recover_stuck_run(player) if player.enemy is None else []
        if recovery_msgs:
            await game_store.save_one_async(str(interaction.user.id))
            embed = combat_embed(player, recovery_msgs)
        else:
            embed = combat_embed(player, [f"Already in run! Wave {player.wave}"])
        await interaction.followup.send(embed=embed, view=CombatView(interaction.user.id, game_store))
        return
    msgs = start_run(player)
    game_store.save()
    embed = combat_embed(player, msgs)
    await interaction.followup.send(embed=embed, view=CombatView(interaction.user.id, game_store))

# --- ADMIN COMMANDS ---
# Server admins can grant the bot's admin commands to specific players.
# Delegated bot-admins are stored by storage.py and survive bot restarts.
def is_server_admin(interaction: discord.Interaction) -> bool:
    # DM check - no guild = not a server admin
    if interaction.guild is None:
        return False
    try:
        perms = interaction.user.guild_permissions
        if perms.administrator:
            return True
        # Also allow Manage Guild as an admin fallback
        if perms.manage_guild:
            return True
    except Exception:
        pass
    return False


def has_admin_commands(interaction: discord.Interaction) -> bool:
    """True for real Discord server admins OR delegated bot admins."""
    if interaction.guild is None:
        return False
    if is_server_admin(interaction):
        return True
    try:
        return bool(is_bot_admin(interaction.user.id))
    except Exception as e:
        print(f"[ADMIN] Failed delegated-admin check for {interaction.user.id}: {e}")
        return False


def admin_denied_message() -> str:
    return "❌ You need **Administrator** permission in this server (or delegated bot-admin access)."


# /give admin @player
# IMPORTANT: only a real Discord server admin can grant/revoke delegated access.
give_group = app_commands.Group(name="give", description="[ADMIN] Grant bot permissions")


@give_group.command(name="admin", description="[ADMIN] Give bot admin commands to a player")
@app_commands.describe(user="Player who should receive the bot admin commands")
async def give_admin(interaction: discord.Interaction, user: discord.Member):
    if not is_server_admin(interaction):
        await interaction.response.send_message(
            "❌ Only a **Discord Server Administrator** can give bot admin access.",
            ephemeral=True,
        )
        return

    if interaction.guild is None:
        await interaction.response.send_message("❌ This command can only be used inside a server.", ephemeral=True)
        return

    try:
        already_admin = bool(is_bot_admin(user.id))
    except Exception as e:
        print(f"[ADMIN] Failed delegated-admin lookup for {user.id}: {e}")
        already_admin = False

    if already_admin:
        await interaction.response.send_message(
            f"ℹ️ {user.mention} already has **bot admin commands**.",
            ephemeral=True,
        )
        return

    try:
        result = add_bot_admin(user.id)
        # Support storage implementations that return a success flag, while
        # also treating a None return as success (common for simple setters).
        if result is False:
            raise RuntimeError("storage.add_bot_admin returned False")
    except Exception as e:
        print(f"[ADMIN] Failed to grant bot admin to {user.id}: {e}")
        await interaction.response.send_message(
            f"❌ Could not give bot admin access to {user.mention}.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"✅ {user.mention} now has **bot admin commands**.\n"
        f"They do **not** become a Discord server administrator; they only gain this bot's admin commands.",
        ephemeral=True,
    )


# Register the /give command group with Discord.
bot.tree.add_command(give_group)


@bot.tree.command(name="setwave", description="[ADMIN] Set a player's current test wave")
@app_commands.describe(wave="Wave to jump to (1-10000)", user="Player to set (leave empty for yourself)")
async def setwave(interaction: discord.Interaction, wave: int, user: discord.User = None):
    # Defer immediately so even a slow PostgreSQL/admin lookup cannot leave
    # Discord showing the command as permanently "thinking...".
    await interaction.response.defer(ephemeral=True)

    try:
        if not has_admin_commands(interaction):
            await interaction.followup.send(admin_denied_message(), ephemeral=True)
            return

        if wave < 1 or wave > 10000:
            await interaction.followup.send(
                "❌ Wave must be between **1 and 10,000**.", ephemeral=True
            )
            return

        target = user or interaction.user
        player = game_store.get(target.id)

        # If the player is not currently running, initialise a normal run first.
        # Then jump directly to the requested wave and create a fresh encounter.
        if not player.run_active:
            start_run(player)

        player.run_active = True
        player.wave = int(wave)
        player.zombies_remaining = 3
        player.enemy = None
        player.bloater_cooldown = 0
        player.bloaters_spawned_this_run = 0
        player.void_bazooka_boss_fired = False
        player.void_infusion_cooldown = 0
        player.void_shield_cooldown = 0
        player.void_execution_cooldown = 0
        player.void_infusion_active = False
        player.void_shield_active = False
        player.void_execution_active = False
        # Admin test runs never write leaderboard records.
        player.admin_test_mode = True
        player.enemy = spawn_enemy(player)

        # Keep the save synchronous for consistency with the rest of the bot,
        # but it now happens after the interaction has already been deferred.
        game_store.save_one(str(target.id))

        embed = combat_embed(
            player,
            [
                f"🧪 **ADMIN TEST MODE** — jumped {target.mention} to **Wave {player.wave}**.",
                f"🧟 **{player.enemy.name}** appears with **{player.enemy.health} HP**.",
                "🏆 Waves completed in this test run **will NOT affect leaderboards**.",
            ],
        )
        await interaction.followup.send(
            embed=embed,
            view=CombatView(target.id, game_store),
            ephemeral=True,
        )
    except Exception as e:
        print(f"[ADMIN] /setwave failed: {type(e).__name__}: {e}")
        try:
            await interaction.followup.send(
                f"❌ **/setwave failed:** `{type(e).__name__}`\n"
                "Check the Railway logs for the full error.",
                ephemeral=True,
            )
        except Exception as followup_error:
            print(f"[ADMIN] /setwave error response failed: {followup_error}")


@bot.tree.command(name="addmoney", description="[ADMIN] Add money to a player")
@app_commands.describe(user="Player to give money to (leave empty for yourself)", amount="Amount to add (e.g. 5000)")
async def addmoney(interaction: discord.Interaction, amount: int, user: discord.User = None):
    if not has_admin_commands(interaction):
        await interaction.response.send_message(admin_denied_message(), ephemeral=True)
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
    if not has_admin_commands(interaction):
        await interaction.response.send_message(admin_denied_message(), ephemeral=True)
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
    if not has_admin_commands(interaction):
        await interaction.response.send_message(admin_denied_message(), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    target = user or interaction.user
    player = game_store.get(target.id)
    player.xp += amount
    game_store.save()
    await interaction.followup.send(f"✨ **+{amount} XP** to {target.mention} → Level {player.level} | XP: {player.xp}", ephemeral=True)


@bot.tree.command(name="resetplayer", description="[ADMIN] Reset a player's progress")
@app_commands.describe(user="Player to reset")
async def resetplayer(interaction: discord.Interaction, user: discord.User):
    if not has_admin_commands(interaction):
        await interaction.response.send_message(admin_denied_message(), ephemeral=True)
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
    if not has_admin_commands(interaction):
        await interaction.response.send_message(admin_denied_message(), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    player = game_store.get(user.id)
    player.money += money
    player.stars += stars
    player.xp += xp
    game_store.save()
    await interaction.followup.send(f"✅ Restored {user.mention}: +${money}, +{stars}⭐, +{xp} XP\nNow: ${player.money} | {player.stars}⭐ | Lvl {player.level} ({player.xp} XP)", ephemeral=True)

@bot.tree.command(name="addvoidessence", description="[ADMIN] Add Void Essence to a player")
@app_commands.describe(user="Player to give Void Essence to", amount="Amount of Void Essence to add")
async def addvoidessence(interaction: discord.Interaction, amount: int, user: discord.User = None):
    if not has_admin_commands(interaction):
        await interaction.response.send_message(admin_denied_message(), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    target=user or interaction.user
    player=game_store.get(target.id)
    player.void_essence=max(0, player.void_essence + amount)
    game_store.save()
    await interaction.followup.send(f"◈ **+{amount} Void Essence** added to {target.mention} → Now has **◈{player.void_essence}**", ephemeral=True)


def main():
    import os, sys
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN missing")
        sys.exit(1)
    print(f"Token found {token[:10]}... Starting V6 FULL RESTORED + 3 FEEDBACK FIXES - star lock / ammo save / XP scaling")
    bot.run(token, log_handler=None)

if __name__ == "__main__":
    main()
