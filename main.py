"""Ultimate clean bot V6 FULL RESTORED - POSTGRES CONSTANT SAVE - every action saves instantly - zero loss"""
import os, sys, json, random, logging, time, uuid, asyncio
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone, timedelta
import discord
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('zombie-bot')
from discord import app_commands

OWNER_ID = 572053060969299977
XP_BOOST_DURATION_SECONDS = 24 * 60 * 60
CASH_BOOST_DURATION_SECONDS = 24 * 60 * 60
GLOBAL_XP_BOOST_UNTIL: str | None = None
GLOBAL_CASH_BOOST_UNTIL: str | None = None

from storage import load_all_players, save_player, DB_PATH, SAVE_FILE, get_bot_admins, is_bot_admin, add_bot_admin, remove_bot_admin, verify_storage
print(f"[STORAGE] Using POSTGRES - CONSTANT SAVE ENABLED - V6 FULL RESTORED")

_purchase_locks: set[int] = set()


def schedule_shop_save(store, user_id: int):
    """Persist a shop mutation without making the Discord UI wait on PostgreSQL I/O.

    Shop callbacks update the in-memory Survivor first, schedule the durable save,
    and then edit the Discord message. GameStore.save_one_async() still snapshots
    under the per-player action lock and serializes database writes with save_lock(),
    so this changes response latency without removing the persistence safeguards.
    """
    import asyncio

    async def _save():
        try:
            await store.save_one_async(str(user_id))
        except Exception as e:
            print(f"[SHOP SAVE ERROR] {user_id}: {e}")

    try:
        asyncio.create_task(_save())
    except RuntimeError as e:
        # Normally the Discord event loop is running. If it is not, surface the
        # problem rather than silently pretending the save was scheduled.
        print(f"[SHOP SAVE SCHEDULE ERROR] {user_id}: {e}")



def make_bar(current: int, max_val: int, length: int = 12) -> str:
    if max_val <= 0:
        return "░" * length
    pct = max(0, min(1, current / max_val))
    filled = int(pct * length)
    return "█" * filled + "░" * (length - filled)

def _display_enemy_name_for_zone(player, enemy):
    """Normalize legacy enemy names for active runs after zone-name updates."""
    if enemy is None:
        return "No enemy"
    if getattr(enemy, "is_bloater", False):
        return enemy.name

    current_map = ZONE_ENEMY_NAMES.get(player.zone_name, {})
    for zone_map in ZONE_ENEMY_NAMES.values():
        for archetype, display_name in zone_map.items():
            if enemy.name == archetype or enemy.name == display_name:
                return current_map.get(archetype, enemy.name)
    return enemy.name


def combat_embed(player, last_msgs=None):
    import discord
    p_bar = make_bar(player.health, player.max_health, 12)
    p_pct = int(player.health / player.max_health * 100) if player.max_health else 0
    if player.enemy:
        e_bar = make_bar(player.enemy.health, player.enemy.max_health, 12)
        e_pct = int(player.enemy.health / player.enemy.max_health * 100) if player.enemy.max_health else 0
        e_name = _display_enemy_name_for_zone(player, player.enemy)
        player.enemy.name = e_name
        e_hp = f"{player.enemy.health}/{player.enemy.max_health}"
        e_dmg = player.enemy.damage
    else:
        e_bar = "░"*12
        e_pct = 0
        e_name = "No enemy"
        e_hp = "0/0"
        e_dmg = 0
    embed = make_embed(
        title=f"🧟 {player.zone_name} — WAVE {player.wave} | {player.zombies_remaining} zombies left",
        color=discord.Color.from_rgb(200, 50, 50) if p_pct < 30 else discord.Color.from_rgb(50, 180, 80)
    )
    survivor_lines = [
        f"`{p_bar}`",
        f"🔫 {player.weapon_name} {player.magazine}/{effective_magazine_size(player)} ({player.get_spare()} spare) [{player.ammo_name}]",
    ]
    if player.zone_name == "The Void":
        survivor_lines.append(f"◈ Bazooka: {player.void_bazooka_ammo} shot(s) ready | Lvl {player.void_weapon_level}/10")
        survivor_lines.append("◈ **Void Perks:** Use the **Void Perks** button below to view effects and activate them.")
    embed.add_field(
        name=f"❤️ You: {player.health}/{player.max_health} HP ({p_pct}%)",
        value="\n".join(survivor_lines),
        inline=False
    )
    embed.add_field(
        name=f"💀 {e_name}: {e_hp} HP ({e_pct}%)",
        value=f"`{e_bar}`\n⚔️ ~{e_dmg} dmg",
        inline=False
    )
    if player.enemy and player.enemy.is_bloater:
        embed.add_field(name=f"💣 BLOATER - {player.enemy.bloater_timer} ATTACKS LEFT!", value=f"⏰ Kill it in {player.enemy.bloater_timer} attacks or take {int(BLOATER_EXPLODE_PCT*100)}% max HP damage! Solo wave - reward if you survive!", inline=False)
    if player.enemy and player.enemy.is_zone_boss:
        phase = " 🔥 FINAL PHASE" if ((player.enemy.boss_key == "Erased" and player.enemy.health <= player.enemy.max_health * 0.20) or (player.enemy.boss_key == "Undertaker" and player.enemy.health <= player.enemy.max_health * 0.25)) else ""
        embed.add_field(name=f"👑 {player.enemy.name}{phase}", value=_boss_status_text(player.enemy), inline=False)
    if last_msgs:
        clean = [m for m in last_msgs if m and "HP restored" not in m and "Waves survived" not in m][:3]
        if clean:
            embed.add_field(name="⚔️ Last action", value="\n".join(clean)[:1024], inline=False)
    set_embed_footer(embed, text=f"💰 ${player.money} | ⭐ {player.stars} | ✨ {player.xp} XP | {player.ammo_name} {player.magazine}/{effective_magazine_size(player)}")
    return embed



MAX_LEVEL = 500
COMBAT_MEDIC_PAINKILLERS_PER_RUN = (3, 4, 4, 5, 5, 6, 6)
COMBAT_MEDIC_FULL_RESTORES_PER_RUN = (1, 1, 1, 1, 1, 2, 2)
COMBAT_MEDIC_COSTS = (5000, 25000, 75000, 180000, 250000, 400000)
COMBAT_MEDIC_MAX_LEVEL = 6

# Backward-compatible aliases for code/UI that still refers to the base limits.
MAX_PAINKILLERS_PER_RUN = COMBAT_MEDIC_PAINKILLERS_PER_RUN[0]
MAX_FULL_RESTORES_PER_RUN = COMBAT_MEDIC_FULL_RESTORES_PER_RUN[0]
ZONES: dict[str, dict[str, Any]] = {
    "Graveyard": {"min_level": 1, "hp_mult": 1.0, "dmg_mult": 0.9, "money_mult": 2.0, "xp_mult": 1.6, "desc": "The dead don’t stay buried.", "weights": [60, 25, 12, 3], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.00, "Frostbite": 1.00, "Toxic": 1.00, "Shock": 1.00}},
    "Mega Death City": {"min_level": 50, "hp_mult": 1.8, "dmg_mult": 1.3, "money_mult": 3.5, "xp_mult": 2.0, "desc": "The city belongs to the dead.", "weights": [30, 30, 25, 15], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.20, "Frostbite": 0.90, "Toxic": 1.00, "Shock": 1.15}},
    "Frostbitten Outskirts": {"min_level": 100, "hp_mult": 2.8, "dmg_mult": 1.7, "money_mult": 5.0, "xp_mult": 2.4, "desc": "The cold is the least of your problems.", "weights": [20, 20, 35, 25], "ammo_mods": {"Standard": 1.00, "Bleed": 0.90, "Incendiary": 1.40, "Frostbite": 0.70, "Toxic": 1.00, "Shock": 1.15}},
    "Toxic Wasteland": {"min_level": 150, "hp_mult": 3.7, "dmg_mult": 2.1, "money_mult": 7.5, "xp_mult": 3.2, "desc": "The land itself wants you dead.", "weights": [15, 15, 35, 35], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.10, "Frostbite": 1.00, "Toxic": 1.50, "Shock": 0.90}},
    "The Void": {"min_level": 200, "hp_mult": 6.5, "dmg_mult": 2.6, "money_mult": 10.0, "xp_mult": 4.5, "desc": "Nothing should exist here.", "weights": [10, 10, 30, 50], "ammo_mods": {"Standard": 0.90, "Bleed": 1.10, "Incendiary": 1.15, "Frostbite": 1.10, "Toxic": 1.25, "Shock": 1.50}},
}
ZONE_ORDER = ["Graveyard", "Mega Death City", "Frostbitten Outskirts", "Toxic Wasteland", "The Void"]
WAVE_STAR_CHANCE = {"Graveyard": 0.05, "Mega Death City": 0.07, "Frostbitten Outskirts": 0.10, "Toxic Wasteland": 0.13, "The Void": 0.16}
# Bloater config - run ender
BLOATER_BASE = {"health": 280, "damage": 4, "money": 350, "xp": 120}
BLOATER_MIN_WAVE = 5
# Chance resets after every Bloater, then ramps upward on later eligible waves.
# Different zones start higher and ramp faster, while the 35% cap always leaves
# normal zombies in the pool.
BLOATER_ZONE_START_CHANCE = {
    "Graveyard": 0.05,
    "Mega Death City": 0.07,
    "Frostbitten Outskirts": 0.09,
    "Toxic Wasteland": 0.11,
    "The Void": 0.13,
}
BLOATER_ZONE_CHANCE_STEP = {
    "Graveyard": 0.03,
    "Mega Death City": 0.04,
    "Frostbitten Outskirts": 0.05,
    "Toxic Wasteland": 0.06,
    "The Void": 0.07,
}
BLOATER_MAX_CHANCE = 0.35
BLOATER_FUSE = 5  # attacks before explosion
BLOATER_EXPLODE_PCT = 0.65  # 65% max HP
BLOATER_BOSS_HP_MULT = 1.5  # Bloaters are mini-bosses in every zone
AMMO: dict[str, dict[str, Any]] = {
    "Standard": {"unlock_level": 1, "price": 0, "desc": "Reliable regular lead.", "effect": None, "cost_per_attack": 1, "box_price": 15, "box_amount": 24},
    "Bleed": {"unlock_level": 10, "price": 200, "desc": "25% bleed 15 dmg x3", "effect": "bleed", "cost_per_attack": 2, "box_price": 50, "box_amount": 24},
    "Incendiary": {"unlock_level": 35, "price": 600, "desc": "30% burn 20 dmg x3", "effect": "burn", "cost_per_attack": 3, "box_price": 100, "box_amount": 24},
    "Frostbite": {"unlock_level": 70, "price": 1200, "desc": "25% freeze halves dmg x4 + 10 dmg x2", "effect": "freeze", "cost_per_attack": 4, "box_price": 100, "box_amount": 24},
    "Toxic": {"unlock_level": 110, "price": 2500, "desc": "40% poison 18 dmg x5", "effect": "poison", "cost_per_attack": 5, "box_price": 150, "box_amount": 24},
    "Shock": {"unlock_level": 160, "price": 5000, "desc": "20% stun 1 turn + 30 dmg", "effect": "shock", "cost_per_attack": 6, "box_price": 185, "box_amount": 24},
}
WEAPONS: dict[str, dict[str, Any]] = {
    "Pistol": {
        "damage": 20, "mag": 12, "price": 0, "unlock_level": 1, "shots": 1,
        "desc": "Reliable sidearm with balanced damage, a 12-round magazine, and steady performance."
    },
    "Shotgun": {
        "damage": 45, "mag": 6, "price": 250, "unlock_level": 15, "shots": 1,
        "desc": "Heavy close-range weapon with powerful single shots and a small magazine."
    },
    "Rifle": {
        "damage": 25, "mag": 30, "price": 2500, "unlock_level": 30, "shots": 2,
        "desc": "Versatile automatic rifle that fires 2 rounds per attack and carries a large magazine."
    },
    "SMG": {
        "damage": 15, "mag": 42, "price": 4000, "unlock_level": 60, "shots": 3,
        "desc": "Fast-firing weapon that unleashes 3 rounds per attack, trading per-shot damage for volume."
    },
    "Sawed-Off": {
        "damage": 70, "mag": 2, "price": 6000, "unlock_level": 90, "shots": 1,
        "desc": "Brutal short-range shotgun delivering massive single-shot damage from a 2-round magazine."
    },
    "Tactical Sniper": {
        "damage": 180, "mag": 1, "price": 15000, "unlock_level": 125, "shots": 1,
        "desc": "Heavy late-game single-shot sniper. Massive damage, but starts with a 1-round magazine and relies on Magazine upgrades for special ammo."
    },
}

WEAPON_UPGRADE_BASE_COSTS: dict[str, int] = {"damage": 250, "mag": 350, "crit": 400, "double_tap": 5000}
DOUBLE_TAP_COSTS = (5000, 10000, 20000, 35000, 55000, 85000, 125000, 180000, 260000, 375000)
DOUBLE_TAP_WEAPON_MULT: dict[str, float] = {
    "Pistol": 1.00, "Shotgun": 1.20, "Rifle": 1.45,
    "SMG": 1.65, "Sawed-Off": 1.90, "Tactical Sniper": 2.25,
}
DOUBLE_TAP_MAX_LEVEL = 10
WEAPON_DAMAGE_MAX_LEVEL = 200
WEAPON_MAG_MAX_LEVEL = 200
WEAPON_CRIT_MAX_CHANCE = 0.40
# Crit progression is 2% at level 1, then +0.5% per level.
WEAPON_CRIT_MAX_LEVEL = 77
WEAPON_DAMAGE_PER_UPGRADE: dict[str, int] = {
    "Pistol": 3,
    "Shotgun": 3,
    "Rifle": 4,
    "SMG": 4,
    "Sawed-Off": 6,
    "Tactical Sniper": 7,
}
WEAPON_UPGRADE_RARITY_MULT: dict[str, float] = {
    "Pistol": 1.00, "Shotgun": 1.12, "Rifle": 1.25, "SMG": 1.38, "Sawed-Off": 1.52, "Tactical Sniper": 1.70,
}
WEAPON_UPGRADE_EARLY_MULT: dict[str, float] = {"damage": 1.50, "mag": 1.50, "crit": 1.60}
WEAPON_UPGRADE_LATE_MULT: dict[str, float] = {"damage": 1.28, "mag": 1.28, "crit": 1.28}

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

# Zone-specific enemy names. The four entries still use the exact same
# underlying Walker/Runner/Brute/Mutant stats and spawn weights.
ZONE_ENEMY_NAMES: dict[str, dict[str, str]] = {
    "Graveyard": {
        "Walker": "Infected",
        "Runner": "Crawler",
        "Brute": "Crypt Guard",
        "Mutant": "Wraith",
    },
    "Mega Death City": {
        "Walker": "Walker",
        "Runner": "Runner",
        "Brute": "Brute",
        "Mutant": "Mutant",
    },
    "Frostbitten Outskirts": {
        "Walker": "Frost Walker",
        "Runner": "Snow Crawler",
        "Brute": "Frost Brute",
        "Mutant": "Glacier Beast",
    },
    "Toxic Wasteland": {
        "Walker": "Toxic Walker",
        "Runner": "Blightborn",
        "Brute": "Toxic Brute",
        "Mutant": "Bio-Titan",
    },
    "The Void": {
        "Walker": "Void Walker",
        "Runner": "Shadowborn",
        "Brute": "Null Brute",
        "Mutant": "Tormented Soul",
    },
}
EMBED_FOOTER_TEXT = "Created by Freak - Royal Reapers"

def make_embed(*args, **kwargs):
    embed = discord.Embed(*args, **kwargs)
    set_embed_footer(embed, text=EMBED_FOOTER_TEXT)
    return embed


def set_embed_footer(embed, text: str | None = None):
    if text:
        embed.set_footer(text=f"{text} • {EMBED_FOOTER_TEXT}")
    else:
        embed.set_footer(text=EMBED_FOOTER_TEXT)


@dataclass
class Enemy:
    name: str; health: int; max_health: int; damage: int; money_reward: int; xp_reward: int; effects: dict[str, int] = field(default_factory=dict)
    is_bloater: bool = False
    is_zone_boss: bool = False
    boss_key: str = ""
    is_void_boss: bool = False  # backward-compatible alias for Void boss checks
    bloater_timer: int = 0  # fuse countdown for Bloater
    boss_attacks_taken: int = 0  # successful player attack actions against this boss
    boss_bounty_triggers: int = 0  # Kingpin: qualifying 500+ damage actions
    boss_bonus_cash: int = 0  # Kingpin bounty payout accumulated on kill
@dataclass
class Survivor:
    max_health: int = 100; health: int = 100; money: int = 0; xp: int = 0; stars: int = 0
    weapon_name: str = "Pistol"; equipped_weapon: str = "Pistol"; weapon_damage: int = 20; magazine_size: int = 12; magazine: int = 12
    spare_ammo: dict[str, int] = field(default_factory=lambda: {"Standard": 36})
    full_restores: int = 1; painkillers: int = 3; painkillers_used_this_run: int = 0; full_restores_used_this_run: int = 0
    run_money_earned: int = 0; run_xp_earned: int = 0; run_zombies_killed: int = 0; zone_name: str = "Graveyard"; ammo_name: str = "Standard"
    owned_ammo: list[str] = field(default_factory=lambda: ["Standard"]); owned_weapons: list[str] = field(default_factory=lambda: ["Pistol"])
    run_active: bool = False; wave: int = 0; zombies_remaining: int = 0; enemy: Enemy | None = None
    # Unique run session ID prevents stale, never-expiring combat messages from acting on a newer run.
    run_id: str = ""
    # --- Bloater tracking ---
    # Kept for save compatibility/history; Bloater spawning is now chance-based
    # with only a one-wave anti-consecutive safeguard.
    bloaters_spawned_this_run: int = 0
    bloater_cooldown: int = 0
    bloater_chance_steps: int = 0  # failed eligible rolls since the last Bloater
    # Bloater decisions are locked to a wave so recovery/re-spawn calls cannot
    # roll the Bloater chance multiple times for the same wave.
    bloater_roll_wave: int = 0
    bloater_wave_result: bool = False
    # --- UNIVERSAL MONEY UPGRADES ---
    health_upgrades: int = 0; armor_upgrades: int = 0; scavenger_upgrades: int = 0
    # --- INDIVIDUAL WEAPON UPGRADES (cash, per weapon) ---
    weapon_upgrades: dict[str, dict[str, int]] = field(default_factory=dict)
    combat_medic_level: int = 0
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
    # Daily Survivor Crate cooldown (UTC ISO timestamp of last claim).
    daily_claimed_at: str | None = None
    # Owner-only temporary 2x XP boost for this player.
    xp_boost_until: str | None = None
    # Global 2x XP/cash expiries are persisted on the Owner record.
    global_xp_boost_until: str | None = None
    # Owner-only temporary 2x Cash boost for this player.
    cash_boost_until: str | None = None
    # Global 2x Cash boost is persisted on the Owner record.
    global_cash_boost_until: str | None = None
    # Persistent flag so admin test runs stay excluded from leaderboards even across restarts.
    admin_test_mode: bool = False
    @property
    def level(self) -> int: return level_for_xp(self.xp)
    def get_spare(self, ammo_type: str | None = None) -> int: return self.spare_ammo.get(ammo_type or self.ammo_name, 0)
    @property
    def max_painkillers_per_run(self) -> int:
        return COMBAT_MEDIC_PAINKILLERS_PER_RUN[self.combat_medic_level]

    @property
    def max_full_restores_per_run(self) -> int:
        return COMBAT_MEDIC_FULL_RESTORES_PER_RUN[self.combat_medic_level]

    @property
    def double_tap_chance(self) -> float:
        level = self.weapon_upgrade_level("double_tap")
        return min(0.01 * level, 0.10)
    def _ensure_weapon_upgrades(self):
        if not isinstance(self.weapon_upgrades, dict):
            self.weapon_upgrades = {}
        for weapon_name in WEAPONS:
            current = self.weapon_upgrades.get(weapon_name)
            if not isinstance(current, dict):
                current = {}
            self.weapon_upgrades[weapon_name] = {
                "damage": max(0, min(WEAPON_DAMAGE_MAX_LEVEL, int(current.get("damage", 0) or 0))),
                "mag": max(0, min(WEAPON_MAG_MAX_LEVEL, int(current.get("mag", 0) or 0))),
                "crit": max(0, min(WEAPON_CRIT_MAX_LEVEL, int(current.get("crit", 0) or 0))),
                "double_tap": max(0, min(DOUBLE_TAP_MAX_LEVEL, int(current.get("double_tap", 0) or 0))),
            }

    def weapon_upgrade_level(self, stat: str, weapon_name: str | None = None) -> int:
        self._ensure_weapon_upgrades()
        return int(self.weapon_upgrades.get(weapon_name or self.weapon_name, {}).get(stat, 0))

    def recalc_stats(self):
        """Recalculate equipped weapon stats from that weapon's own upgrades."""
        if self.weapon_name not in WEAPONS:
            self.weapon_name = self.equipped_weapon if self.equipped_weapon in WEAPONS else "Pistol"
        self.equipped_weapon = self.weapon_name
        self._ensure_weapon_upgrades()
        base = WEAPONS.get(self.weapon_name, WEAPONS["Pistol"])
        damage_per_upgrade = WEAPON_DAMAGE_PER_UPGRADE.get(self.weapon_name, 3)
        self.weapon_damage = base["damage"] + self.weapon_upgrade_level("damage") * damage_per_upgrade
        shots = int(base.get("shots", 1))
        self.magazine_size = base["mag"] + self.weapon_upgrade_level("mag") * shots
        self.max_health = 100 + self.health_upgrades * 20

    @property
    def crit_chance(self) -> float:
        level = self.weapon_upgrade_level("crit")
        if level <= 0:
            return 0.0
        return min(0.02 + (level - 1) * 0.005, 0.40)
    @property
    def armor_reduction(self) -> int:
        return self.armor_upgrades * 2
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
        # weapon_name is the persistent equipped weapon. Keep an explicit
        # alias too so older/newer saves cannot silently fall back to Pistol
        # when a run is resumed after a restart.
        d = asdict(self)
        d["equipped_weapon"] = self.weapon_name
        d["__version"] = 5
        return d
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Survivor":
        data = dict(data)
        if data.get("zone_name") not in ZONES: data["zone_name"] = "Graveyard"
        if data.get("ammo_name") not in AMMO: data["ammo_name"] = "Standard"

        # Preserve the player's equipped weapon across run resumes/restarts.
        # Prefer the explicit equipped_weapon field when present, then the
        # existing weapon_name field. Only fall back to a valid owned weapon
        # (or Pistol) if the saved weapon is actually missing/invalid.
        saved_weapon = data.get("equipped_weapon")
        if saved_weapon not in WEAPONS:
            saved_weapon = data.get("weapon_name")
        owned_saved = data.get("owned_weapons", ["Pistol"])
        if not isinstance(owned_saved, list):
            owned_saved = ["Pistol"]
        if saved_weapon not in WEAPONS:
            saved_weapon = next((w for w in owned_saved if w in WEAPONS), "Pistol")
        data["weapon_name"] = saved_weapon
        data["equipped_weapon"] = saved_weapon
        # Test-mode migration: the old global weapon upgrades are intentionally
        # not converted. New weapon-specific levels start at zero.
        if "health_upgrades" not in data:
            data["health_upgrades"] = max(0, (data.get("max_health",100)-100)//20)
        if not isinstance(data.get("weapon_upgrades"), dict):
            data["weapon_upgrades"] = {}
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

        if "armor_upgrades" not in data:
            data["armor_upgrades"] = 0
        if "scavenger_upgrades" not in data:
            data["scavenger_upgrades"] = 0
        enemy_data = data.get("enemy")
        if isinstance(enemy_data, dict):
            enemy_allowed = {k: v for k, v in enemy_data.items() if k in Enemy.__dataclass_fields__}
            enemy_allowed.setdefault("effects", {})
            if not isinstance(enemy_allowed["effects"], dict):
                enemy_allowed["effects"] = {}
            enemy = Enemy(**enemy_allowed)
        else:
            enemy = None
        spare = data.get("spare_ammo", {"Standard": 36})
        if isinstance(spare, int): spare = {"Standard": spare}
        allowed = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        allowed["spare_ammo"] = spare; allowed["enemy"] = enemy
        allowed.setdefault("painkillers_used_this_run", 0); allowed.setdefault("full_restores_used_this_run", 0)
        allowed["combat_medic_level"] = max(0, min(COMBAT_MEDIC_MAX_LEVEL, int(allowed.get("combat_medic_level", 0) or 0)))
        allowed.setdefault("run_money_earned", 0); allowed.setdefault("run_xp_earned", 0)
        allowed.setdefault("bloaters_spawned_this_run", 0); allowed.setdefault("bloater_cooldown", 0); allowed.setdefault("bloater_chance_steps", 0)
        allowed.setdefault("bloater_roll_wave", 0); allowed.setdefault("bloater_wave_result", False)
        allowed.setdefault("owned_ammo", ["Standard"]); allowed.setdefault("owned_weapons", ["Pistol"])
        allowed.setdefault("weapon_upgrades", {})
        allowed.setdefault("void_essence", 0)
        allowed.setdefault("void_weapon_level", 0)
        allowed.setdefault("void_weapons_owned", [])
        allowed.setdefault("void_bazooka_ammo", 0)
        allowed.setdefault("void_bazooka_boss_fired", False)
        allowed.setdefault("run_id", "")
        allowed.setdefault("void_infusion_level", 0); allowed.setdefault("void_shield_level", 0); allowed.setdefault("void_execution_level", 0)
        allowed.setdefault("void_infusion_cooldown", 0); allowed.setdefault("void_shield_cooldown", 0); allowed.setdefault("void_execution_cooldown", 0)
        allowed.setdefault("void_infusion_active", False); allowed.setdefault("void_shield_active", False); allowed.setdefault("void_execution_active", False)
        allowed.setdefault("highest_waves", {})
        allowed.setdefault("highest_wave_dates", {})
        allowed.setdefault("leaderboard_name", data.get("leaderboard_name", "Survivor"))
        allowed.setdefault("leaderboard_guilds", [])
        allowed.setdefault("daily_claimed_at", None)
        allowed.setdefault("xp_boost_until", None)
        allowed.setdefault("global_xp_boost_until", None)
        allowed.setdefault("admin_test_mode", False)
        if "Pistol" not in allowed["owned_weapons"]: allowed["owned_weapons"].append("Pistol")
        allowed["equipped_weapon"] = allowed.get("weapon_name", "Pistol")
        if "stars" not in data: allowed["stars"] = max(0, level_for_xp(int(data.get("xp", 0))) - 1)
        player = cls(**allowed)
        if player.run_active and not player.run_id:
            player.run_id = uuid.uuid4().hex
        player.recalc_stats()
        return player

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

# --- ZONE BOSS SYSTEM -------------------------------------------------------
# Zone bosses are deterministic milestone encounters: Wave 20, 40, 60, ...
# They are never RNG-spawned and always replace the normal/Bloater encounter.
ZONE_BOSS_CONFIG: dict[str, dict[str, Any]] = {
    "Graveyard": {
        "key": "Undertaker", "display": "The Undertaker", "damage_mult": 1.35,
        "cash": 1500, "xp": 500, "extra": None,
    },
    "Mega Death City": {
        "key": "Kingpin", "display": "The Kingpin", "damage_mult": 1.45,
        "cash": 5000, "xp": 1250, "extra": None,
    },
    "Frostbitten Outskirts": {
        "key": "Wendigo", "display": "The Wendigo", "damage_mult": 1.30,
        "cash": 12500, "xp": 2500, "extra": "ammo24",
    },
    "Toxic Wasteland": {
        "key": "Contaminant", "display": "The Contaminant", "damage_mult": 1.25,
        "cash": 30000, "xp": 5000, "extra": "ammo36",
    },
    "The Void": {
        "key": "Erased", "display": "The Erased", "damage_mult": 1.35,
        "cash": 75000, "xp": 10000, "extra": "essence8",
    },
}
ZONE_BOSS_MILESTONE = 20
ZONE_BOSS_HP_BASE = 900
ZONE_BOSS_HP_WAVE_STEP = 25

def is_zone_boss_wave(wave: int) -> bool:
    return int(wave) >= ZONE_BOSS_MILESTONE and int(wave) % ZONE_BOSS_MILESTONE == 0

def boss_reward_multiplier(wave: int) -> float:
    return 1.0 + max(0, int(wave) - ZONE_BOSS_MILESTONE) / 40.0

def _make_zone_boss_enemy(player: Survivor) -> Enemy:
    cfg = ZONE_BOSS_CONFIG[player.zone_name]
    zone = zone_for(player)
    health = round((ZONE_BOSS_HP_BASE + ZONE_BOSS_HP_WAVE_STEP * (player.wave - ZONE_BOSS_MILESTONE)) * zone["hp_mult"])
    # The existing zone damage baseline is 10 * zone dmg_mult; boss multipliers
    # then produce the intended approximate values 12/19/22/26/35.
    damage = max(1, int(10 * zone["dmg_mult"] * cfg["damage_mult"]))
    return Enemy(
        name=cfg["display"], health=health, max_health=health, damage=damage,
        money_reward=cfg["cash"], xp_reward=cfg["xp"],
        is_zone_boss=True, boss_key=cfg["key"],
        is_void_boss=(cfg["key"] == "Erased"),
    )

def _boss_status_text(enemy: Enemy) -> str:
    if not enemy.is_zone_boss:
        return ""
    if enemy.boss_key == "Undertaker":
        marks = enemy.effects.get("grave_marks", 0)
        required = 2 if enemy.health <= enemy.max_health * 0.25 else 3
        return f"☠️ Grave Marks: **{marks}/{required}**"
    if enemy.boss_key == "Kingpin":
        return f"💰 Protection Racket: **{enemy.boss_attacks_taken % 3}/3** • Bounty: **+${enemy.boss_bonus_cash:,}**"
    if enemy.boss_key == "Wendigo":
        frost = enemy.effects.get("boss_frost", 0)
        frozen = bool(enemy.effects.get("wendigo_frozen", 0))
        return f"❄️ Frost: **{frost}/5**" + (" • 🥶 FROZEN" if frozen else "")
    if enemy.boss_key == "Contaminant":
        stacks = enemy.effects.get("contamination", 0)
        return f"☣️ Contamination: **{stacks}/5** (+{stacks * 5}% poison)"
    if enemy.boss_key == "Erased":
        count = enemy.boss_attacks_taken % 3
        if enemy.health <= enemy.max_health * 0.20:
            count = enemy.boss_attacks_taken % 2
        return f"🌀 Erasure: **{count}/{2 if enemy.health <= enemy.max_health * 0.20 else 3}**"
    return ""


def effective_magazine_size(player: Survivor) -> int:
    """Return the temporary combat magazine capacity after boss debuffs."""
    size = int(player.magazine_size)
    enemy = player.enemy
    if enemy and enemy.is_zone_boss and enemy.boss_key == "Wendigo" and enemy.effects.get("boss_frost", 0) >= 4:
        size = max(1, size - 1)
    return size


def _should_spawn_bloater(player: Survivor) -> bool:
    """Return the Bloater result for this wave, rolling at most once.

    The Bloater chance is a WAVE-level decision. A wave can cause spawn_enemy()
    more than once because of recovery/state repair, so the result is cached by
    wave number. This prevents multiple Bloater rolls for the same wave.
    """
    # If this wave has already been decided, never roll again.
    if player.bloater_roll_wave == player.wave:
        return player.bloater_wave_result

    if player.wave < BLOATER_MIN_WAVE:
        player.bloater_roll_wave = player.wave
        player.bloater_wave_result = False
        return False

    # Keep the wave immediately before a guaranteed Zone Boss normal as well;
    # otherwise Wave 19 -> Wave 20 would create back-to-back special waves.
    if is_zone_boss_wave(player.wave + 1):
        player.bloater_roll_wave = player.wave
        player.bloater_wave_result = False
        return False

    if player.bloater_cooldown > 0:
        # Protected wave immediately after a Bloater. Consume the cooldown once
        # for this wave and lock in a normal encounter.
        player.bloater_cooldown -= 1
        player.bloater_roll_wave = player.wave
        player.bloater_wave_result = False
        return False

    start_chance = BLOATER_ZONE_START_CHANCE.get(player.zone_name, 0.05)
    step = BLOATER_ZONE_CHANCE_STEP.get(player.zone_name, 0.03)
    chance = min(BLOATER_MAX_CHANCE, start_chance + player.bloater_chance_steps * step)

    result = random.random() < chance
    player.bloater_roll_wave = player.wave
    player.bloater_wave_result = result

    if not result:
        # Failed eligible roll: increase pressure for the next eligible wave.
        player.bloater_chance_steps += 1

    return result

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

def spawn_enemy(player: Survivor, recovery: bool = False) -> Enemy:
    # Zone Boss milestones always take priority over every other encounter.
    # This makes boss waves deterministic and guarantees no Bloater/normal zombie
    # can coexist with the Zone Boss.
    if is_zone_boss_wave(player.wave):
        boss = _make_zone_boss_enemy(player)
        player.zombies_remaining = 1
        return boss

    # Non-boss waves retain the existing Bloater RNG system.
    if _should_spawn_bloater(player):
        bloater = _make_bloater_enemy(player)
        if not recovery:
            player.bloaters_spawned_this_run += 1
            player.bloater_cooldown = 1  # prevent consecutive Bloater waves
            player.bloater_chance_steps = 0  # reset chance after every Bloater
        # Solo wave: only bloater this round = reward
        player.zombies_remaining = 1
        return bloater

    zone = zone_for(player)
    archetype = random.choices(list(ZOMBIES), weights=zone["weights"])[0]
    base = ZOMBIES[archetype]
    display_name = ZONE_ENEMY_NAMES.get(player.zone_name, {}).get(archetype, archetype)
    health = int((base["health"] + (player.wave - 1) * 4) * zone["hp_mult"])
    damage = int((base["damage"] + (player.wave - 1) // 3) * zone["dmg_mult"])
    return Enemy(name=display_name, health=health, max_health=health, damage=damage, money_reward=int(base["money"]*zone["money_mult"]), xp_reward=int(base["xp"]*zone["xp_mult"]))

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
    return costs[lvl] if lvl < len(costs) else 0

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
    erasure_extra = 1 if (player.enemy and player.enemy.is_zone_boss and player.enemy.boss_key == "Erased" and player.enemy.effects.get("erasure_effect") == "essence") else 0
    total_cost = cost + erasure_extra
    if player.void_essence < total_cost:
        return [f"❌ Need ◈{total_cost} Void Essence to activate **{perk_name}**; you have ◈{player.void_essence}."]
    player.void_essence -= total_cost
    if erasure_extra:
        player.enemy.effects.pop("erasure_effect", None)
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
    player.run_id = uuid.uuid4().hex
    player.painkillers_used_this_run = 0
    player.full_restores_used_this_run = 0
    player.run_money_earned = 0
    player.run_xp_earned = 0
    player.run_zombies_killed = 0
    player.bloaters_spawned_this_run = 0
    player.bloater_cooldown = 0
    player.bloater_roll_wave = 0
    player.bloater_wave_result = False
    player.bloater_chance_steps = 0

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
    if not player.run_id:
        player.run_id = uuid.uuid4().hex
    if player.wave < 1:
        player.wave = 1
    if player.zombies_remaining <= 0:
        player.zombies_remaining = max(3, player.wave + 2)
    player.enemy = spawn_enemy(player, recovery=True)

    # Recovery must restore the persistent consequences of an already-decided
    # Bloater wave without counting a second Bloater spawn. The normal spawn
    # path sets these fields, but recovery intentionally skips those mutations
    # to avoid duplicate run statistics. Re-apply the state here only when the
    # restored encounter is a Bloater.
    if player.enemy.is_bloater:
        player.bloater_cooldown = 1
        player.bloater_chance_steps = 0

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
    boss_text = f" • {_boss_status_text(player.enemy)}" if player.enemy.is_zone_boss else ""
    return f"🔫 {player.ammo_name} {player.magazine}/{player.magazine_size} ({cost}/shot) | spare: {player.get_spare()} | 🧟 {player.enemy.name} {player.enemy.health} HP{boss_text}"

def _apply_boss_attack_effect(player: Survivor, damage_dealt: int) -> tuple[int, list[str]]:
    """Apply a successful Zone Boss attack's mechanic and return adjusted damage/messages."""
    enemy = player.enemy
    if enemy is None or not enemy.is_zone_boss or damage_dealt <= 0:
        return damage_dealt, []
    messages: list[str] = []
    if enemy.boss_key == "Undertaker":
        if enemy.effects.pop("grave_double_pending", 0):
            # The attack that consumes the double-damage charge resets Marks; it
            # does not immediately create a new mark on the same attack.
            enemy.effects["grave_marks"] = 0
            messages.append("☠️ **Grave Marks reset to 0.**")
        else:
            marks = enemy.effects.get("grave_marks", 0) + 1
            enemy.effects["grave_marks"] = marks
            required = 2 if enemy.health <= enemy.max_health * 0.25 else 3
            messages.append(f"☠️ **Grave Mark +1** — {marks}/{required}")
    elif enemy.boss_key == "Wendigo":
        frost = enemy.effects.get("boss_frost", 0) + 1
        if frost >= 5:
            enemy.effects["boss_frost"] = 0
            enemy.effects["wendigo_frozen"] = 1
            messages.append("🥶 **FROZEN!** Your next normal attack will be skipped. Frost resets to 0.")
        else:
            enemy.effects["boss_frost"] = frost
            if frost == 3:
                messages.append("❄️ **Frost 3:** your damage is reduced by 10%.")
            elif frost == 4:
                messages.append("❄️ **Frost 4:** your magazine capacity is temporarily reduced by 1.")
    elif enemy.boss_key == "Contaminant":
        if enemy.effects.pop("contamination_skip_next", 0):
            messages.append("☣️ **Contamination countered** — your medical item prevented this attack from adding a stack.")
            return damage_dealt, messages
        stacks = min(5, enemy.effects.get("contamination", 0) + 1)
        enemy.effects["contamination"] = stacks
        if stacks == 5:
            burst = max(1, int(player.max_health * 0.25))
            player.health = max(0, player.health - burst)
            enemy.effects["contamination"] = 0
            messages.append(f"☣️ **CRITICAL CONTAMINATION!** You take {burst} poison burst damage (25% max HP). Contamination resets.")
        else:
            messages.append(f"☣️ **Contamination +1** — {stacks}/5 (+{stacks * 5}% poison damage)")
    return damage_dealt, messages

def _boss_damage_multiplier_for_player_action(enemy: Enemy) -> float:
    # Player-side boss modifiers. Undertaker's double hit is handled in
    # _enemy_damage because it modifies the Undertaker's attack, not the player's.
    return 1.0

def _apply_boss_player_attack_counter(player: Survivor, action_damage: int) -> list[str]:
    enemy = player.enemy
    if enemy is None or not enemy.is_zone_boss or action_damage <= 0:
        return []
    messages: list[str] = []
    enemy.boss_attacks_taken += 1
    if enemy.boss_key == "Kingpin" and enemy.boss_attacks_taken % 3 == 0 and enemy.health > 0:
        backup = max(1, enemy.damage // 2 - player.armor_reduction)
        player.health = max(0, player.health - backup)
        messages.append(f"💰 **PROTECTION RACKET!** Kingpin's backup hits you for {backup} damage (50% normal attack).")
    if enemy.boss_key == "Kingpin" and action_damage >= 500:
        enemy.boss_bounty_triggers += 1
        enemy.boss_bonus_cash += 250
        messages.append(f"💰 **BOUNTY INCREASED!** +$250 kill bounty ({enemy.boss_bounty_triggers} trigger(s)).")
    if enemy.boss_key == "Erased" and enemy.health > 0:
        interval = 2 if enemy.health <= enemy.max_health * 0.20 else 3
        if enemy.boss_attacks_taken % interval == 0:
            options = ["weapon", "defence", "medical", "essence"]
            effect = random.choice(options)
            enemy.effects["erasure_effect"] = effect
            labels = {"weapon":"🔫 Weapon Erasure: next attack deals -25% damage.", "defence":"🛡️ Defence Erasure: next incoming attack ignores 10 Armour.", "medical":"💉 Medical Erasure: next healing restores 50% less HP.", "essence":"◈ Essence Erasure: next Void ability costs +1 Essence."}
            messages.append(f"🌀 **ERASURE:** {labels[effect]}")
    return messages


def _enemy_damage(player: Survivor) -> list[str]:
    enemy = player.enemy
    if enemy is None:
        return []
    if enemy.effects.pop("shock", 0):
        return [f"⚡ **{enemy.name} stunned!** Misses."]
    if player.dodge_chance > 0 and random.random() < player.dodge_chance:
        return [f"💨 **DODGED!** You evaded {enemy.name}'s attack! ({player.dodge_chance*100:.1f}% chance)"]

    base_dmg = enemy.damage // 2 if enemy.effects.get("freeze", 0) else enemy.damage
    undertaker_double = False
    if enemy.is_zone_boss and enemy.boss_key == "Undertaker":
        required = 2 if enemy.health <= enemy.max_health * 0.25 else 3
        if enemy.effects.get("grave_marks", 0) >= required:
            undertaker_double = True
            enemy.effects["grave_marks"] = 0
            enemy.effects["grave_double_pending"] = 1
            base_dmg *= 2
    # The Erased's Defence Erasure ignores 10 Armour for exactly one incoming hit.
    armour = player.armor_reduction
    erasure_defence = enemy.is_zone_boss and enemy.boss_key == "Erased" and enemy.effects.get("erasure_effect") == "defence"
    if erasure_defence:
        armour = max(0, armour - 10)
        enemy.effects.pop("erasure_effect", None)
    if enemy.is_zone_boss and enemy.boss_key == "Contaminant":
        contamination = enemy.effects.get("contamination", 0)
        base_dmg = int(base_dmg * (1.0 + 0.05 * contamination))
    damage = max(1, base_dmg - armour)
    shield_used = False
    if player.void_shield_active:
        shield_bonus = void_perk_bonus(player, "Void Shield")
        damage = max(1, int(damage * (1.0 - shield_bonus)))
        player.void_shield_active = False
        player.void_shield_cooldown = VOID_PERKS["Void Shield"]["cooldown"]
        shield_used = True
    player.health = max(0, player.health - damage)

    boss_msgs: list[str] = []
    if player.health > 0 and enemy.is_zone_boss:
        _, boss_msgs = _apply_boss_attack_effect(player, damage)

    if enemy.effects.get("freeze", 0):
        enemy.effects["freeze"] -= 1
        if enemy.effects["freeze"] <= 0:
            del enemy.effects["freeze"]
        result = [f"🧊 Frozen! {enemy.name} hits for {damage} dmg." + (f" 🛡️ Void Shield absorbed {int(shield_bonus*100)}%." if shield_used else "")]
    else:
        result = [f"💥 {enemy.name} hits for {damage} dmg." + (f" 🛡️ Void Shield absorbed {int(shield_bonus*100)}%." if shield_used else "")]
    if undertaker_double:
        result.append("☠️ **THE UNDERTAKER CLAIMS YOU!** Double-damage attack!")
    result.extend(boss_msgs)

    if player.health == 0:
        player.health = player.max_health
        data = build_run_summary(player, "died")
        if isinstance(data, dict):
            msgs = [
                f"💀 **You died!** {get_cocky_line()}", "",
                f"🌊 **Waves survived:** {data['waves_survived']} (reached Wave {data['reached_wave']})",
                f"🧟 **Zombies killed:** {data['zombies_killed']}",
                f"💰 **Money earned:** +${data['money']}",
                f"✨ **XP earned:** +{data['xp']} XP", "",
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

    # Damage-over-time effects tick at the start of the player's next action.
    # Frostbite is intentionally split into two effects: its freeze lasts 4
    # enemy attacks, while its bonus cold damage ticks twice, matching the
    # ammo description instead of silently doing nothing.
    dot_data = {
        "bleed": (15, "Bleed"),
        "burn": (20, "Incendiary"),
        "poison": (18, "Toxic"),
        "freeze_dot": (10, "Frostbite"),
    }
    for effect, (base, mod_name) in dot_data.items():
        stacks = int(enemy.effects.get(effect, 0))
        if stacks <= 0:
            continue
        damage = int(base * ammo_modifier(player, mod_name))
        enemy.health = max(0, enemy.health - damage)
        enemy.effects[effect] = stacks - 1
        messages.append(f"☠️ {mod_name} {damage} dmg.")
        if enemy.effects[effect] <= 0:
            del enemy.effects[effect]
    return messages

def _finish_enemy(player: Survivor) -> list[str]:
    enemy = player.enemy
    if enemy is None or enemy.health > 0:
        return []

    # Zone Bosses use their own milestone reward table and wave multiplier.
    # They deliberately bypass the normal kill XP/wave-clear reward pipeline so
    # they cannot accidentally inherit generic healing, ammo, or Bloater rewards.
    if enemy.is_zone_boss:
        mult = boss_reward_multiplier(player.wave)
        xp_gain = int(enemy.xp_reward * mult * (1.0 + player.xp_bonus) * xp_boost_multiplier(player))
        cash_base = int(enemy.money_reward * mult)
        cash_gain = int(cash_base * player.scavenger_bonus * cash_boost_multiplier(player))
        bounty_cash = 0
        if enemy.boss_key == "Kingpin" and enemy.boss_bonus_cash:
            # Kingpin bounty is part of the cash reward, so active cash boosts
            # and Scavenger apply consistently to the entire boss payout.
            bounty_cash = int(enemy.boss_bonus_cash * player.scavenger_bonus * cash_boost_multiplier(player))
            cash_gain += bounty_cash
        player.money += cash_gain
        old_level = player.level
        player.xp += xp_gain
        new_level = player.level
        level_ups = max(0, new_level - old_level)
        if level_ups:
            player.stars += level_ups
        player.run_money_earned += cash_gain
        player.run_xp_earned += xp_gain
        player.run_zombies_killed += 1
        player.zombies_remaining = 0
        player.void_infusion_cooldown = max(0, player.void_infusion_cooldown - 1)
        player.void_shield_cooldown = max(0, player.void_shield_cooldown - 1)
        player.void_execution_cooldown = max(0, player.void_execution_cooldown - 1)
        messages = [f"👑 **{enemy.name} defeated!** +${cash_gain:,} • +{xp_gain:,} XP (×{mult:.2f} milestone scale)"]
        if enemy.boss_key == "Wendigo":
            player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + 24
            messages.append(f"❄️ **Wendigo reward:** +24 {player.ammo_name} ammo")
        elif enemy.boss_key == "Contaminant":
            player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + 36
            messages.append(f"☣️ **Contaminant reward:** +36 {player.ammo_name} ammo")
        elif enemy.boss_key == "Erased":
            player.void_essence += 8
            messages.append("🌀 **The Erased reward:** +8 Void Essence")
        if enemy.boss_key == "Kingpin" and enemy.boss_bonus_cash:
            messages.append(f"💰 **Bounty collected:** +${bounty_cash:,} ({enemy.boss_bounty_triggers} qualifying 500+ damage action(s))")
        if level_ups:
            messages.append(f"🎉 **LEVEL UP!** Level {player.level}! +{level_ups} ⭐")

        # Boss clears are milestone rewards, not ordinary wave clears: no Medic
        # drops, no passive healing, and no generic +5 ammo/+5 HP wave bonus.
        if not getattr(player, "admin_test_mode", False):
            record_completed_wave(player, player.wave)
        player.wave += 1
        player.zombies_remaining = player.wave + 2
        # Guarantee a normal breathing-room wave after every Zone Boss.
        player.bloater_cooldown = 1
        player.bloater_roll_wave = 0
        player.bloater_wave_result = False
        player.void_bazooka_boss_fired = False
        # Boss clears do not restore HP.
        messages.append(f"🌊 **Boss milestone cleared!** Next wave: **{player.wave}**")
        player.enemy = spawn_enemy(player)
        messages.append(f"🧟 **{player.enemy.name}** appears! {player.enemy.health} HP")
        return messages

    # FIXED XP SCALING - Feedback #3
    # Wave scaling: +8% XP per wave - Wave 20 = 2.6x, Wave 30 = 3.4x
    wave_mult = 1.0 + (player.wave * 0.08)
    # Zone mult already in enemy.xp_reward, but add wave
    # Star XP bonus: +10% base +1% per level, max 25%
    xp_bonus_mult = 1.0 + player.xp_bonus
    # Final XP: base (already includes zone_mult) * wave_mult * xp_bonus
    xp_gain = int(enemy.xp_reward * wave_mult * xp_bonus_mult * xp_boost_multiplier(player))
    
    money_gain = int(enemy.money_reward * player.scavenger_bonus * cash_boost_multiplier(player))
    player.money += money_gain
    old_level = player.level
    player.xp += xp_gain
    new_level = player.level
    level_ups = max(0, new_level - old_level)
    if level_ups:
        player.stars += level_ups
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
    if level_ups:
        messages.append(f"🎉 **LEVEL UP!** Level {player.level}! +{level_ups} ⭐")
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
        # Low-probability bonus Star on wave clear. This is separate from
        # guaranteed +1 Star per level gained and scales by zone.
        wave_star_chance = WAVE_STAR_CHANCE.get(player.zone_name, 0.05)
        if random.random() < wave_star_chance:
            player.stars += 1
            messages.append(
                f"⭐ **LUCKY WAVE CLEAR!** +1 Star! ({wave_star_chance * 100:.0f}% chance)"
            )
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


def _combat_action_noop(player: Survivor, action: str, heal_item: str | None = None) -> str | None:
    """Return a message for an action that should consume no turn, else None.

    A failed/no-op button press does not attack, reload, heal, or otherwise
    change combat state, so it must not trigger pending DoT or an enemy attack.
    """
    if action == "reload":
        if player.magazine >= effective_magazine_size(player):
            return "✅ Mag full!"
        # Having no spare ammo is handled as an end-of-run outcome in take_action.

    if action == "heal":
        if heal_item == "full_restore":
            if player.full_restores_used_this_run >= player.max_full_restores_per_run:
                return f"⚠️ Limit: {player.max_full_restores_per_run}/run."
            if player.full_restores <= 0:
                return "❌ No full restores."
            if player.health >= player.max_health:
                return "❤️ Full HP!"
        elif heal_item == "painkillers":
            if player.painkillers_used_this_run >= player.max_painkillers_per_run:
                return f"⚠️ Limit: {player.max_painkillers_per_run}/run."
            if player.painkillers <= 0:
                return "❌ No painkillers."
            if player.health >= player.max_health:
                return "❤️ Full HP!"
        elif heal_item is None:
            return "Choose heal item."

    if action == "attack":
        ammo_data = AMMO[player.ammo_name]
        base_cost = int(ammo_data["cost_per_attack"])
        weapon_data = WEAPONS.get(player.weapon_name, WEAPONS["Pistol"])
        shots = int(weapon_data.get("shots", 1))
        cost = base_cost * shots
        if effective_magazine_size(player) < base_cost:
            return f"❌ **{player.weapon_name} mag too small for {player.ammo_name}!**"
        if effective_magazine_size(player) < cost:
            return f"❌ **{player.weapon_name} mag too small for {shots}x {player.ammo_name}!**"
        if player.magazine < cost and player.get_spare() > 0:
            return f"❌ Need {cost} {player.ammo_name} ammo! Have {player.magazine}/{player.magazine_size}"

    if action in {"void_infusion", "void_shield", "void_execution"}:
        perk_name = {
            "void_infusion": "Void Infusion",
            "void_shield": "Void Shield",
            "void_execution": "Void Execution",
        }[action]
        if player.zone_name != "The Void":
            return "❌ Void perks only work inside **The Void**."
        lvl = void_perk_level(player, perk_name)
        if lvl <= 0:
            return f"🔒 **{perk_name}** is locked. Unlock it in the Void shop."
        cooldown_field = {
            "Void Infusion":"void_infusion_cooldown",
            "Void Shield":"void_shield_cooldown",
            "Void Execution":"void_execution_cooldown",
        }[perk_name]
        active_field = {
            "Void Infusion":"void_infusion_active",
            "Void Shield":"void_shield_active",
            "Void Execution":"void_execution_active",
        }[perk_name]
        if getattr(player, cooldown_field) > 0:
            return f"⏳ **{perk_name}** cooldown: {getattr(player, cooldown_field)} zombie(s) remaining."
        if getattr(player, active_field):
            return f"⚠️ **{perk_name}** is already armed."
        if perk_name == "Void Execution" and player.enemy.health > player.enemy.max_health * 0.50:
            return "⚠️ **Void Execution** only arms when the enemy is at **50% HP or lower**."
        cost = VOID_PERKS[perk_name]["activation_cost"]
        if player.void_essence < cost:
            return f"❌ Need ◈{cost} Void Essence to activate **{perk_name}**; you have ◈{player.void_essence}."

    if action == "void_bazooka":
        if player.zone_name != "The Void":
            return "❌ The Void Bazooka can only be fired inside **The Void**."
        if "Void Bazooka" not in player.void_weapons_owned:
            return "🔒 You do not own the **Void Bazooka** yet. Buy it in the Void shop."
        enemy = player.enemy
        is_boss_target = enemy.is_bloater or enemy.is_zone_boss or getattr(enemy, "is_void_boss", False)
        if is_boss_target and player.void_bazooka_boss_fired:
            return "⚠️ **Void Bazooka already fired at this boss!** Finish it with your primary weapon."
        extra_essence = 1 if (enemy.is_zone_boss and enemy.boss_key == "Erased" and enemy.effects.get("erasure_effect") == "essence") else 0
        if player.void_bazooka_ammo <= 0 and player.void_essence < VOID_BAZOOKA_AMMO_COST + extra_essence:
            return f"❌ **No Void Bazooka ammo!** This shot costs ◈{VOID_BAZOOKA_AMMO_COST + extra_essence} Void Essence."

    return None


def take_action(player: Survivor, action: str, heal_item: str | None = None) -> list[str]:
    if not player.run_active or player.enemy is None:
        return ["Not in a run. Use Start run."]

    noop_message = _combat_action_noop(player, action, heal_item)
    if noop_message is not None:
        return [noop_message]

    messages: list[str] = []
    # Reload is a real combat action, but pending DoT resolves after the reload
    # so a bleed/burn/poison tick can finish the enemy without cancelling the
    # reload the player just performed. If the DoT does not kill the enemy,
    # the normal enemy attack still happens below.
    if action == "reload":
        pass
    # Flee exits before the next enemy turn, so it does not take a pending DoT tick.
    # All other actions begin with pending DoT damage, including healing.
    elif action != "flee":
        messages.extend(_apply_damage_over_time(player))
        if player.enemy is None or player.enemy.health <= 0:
            messages.extend(_finish_enemy(player))
            return messages

    if action == "heal":
        heal_failed = False
        if heal_item == "full_restore":
            if player.full_restores_used_this_run >= player.max_full_restores_per_run:
                messages.append(f"⚠️ Limit: {player.max_full_restores_per_run}/run.")
                heal_failed = True
            elif player.full_restores <= 0:
                messages.append("❌ No full restores.")
                heal_failed = True
            elif player.health >= player.max_health:
                messages.append("❤️ Full HP!")
                heal_failed = True
            else:
                # MEDIC STAR CHECK - chance to not consume
                if player.medic_chance > 0 and random.random() < player.medic_chance:
                    medical_erasure = bool(player.enemy and player.enemy.is_zone_boss and player.enemy.boss_key == "Erased" and player.enemy.effects.get("erasure_effect") == "medical")
                    player.health = int(player.max_health * 0.50) if medical_erasure else player.max_health
                    if medical_erasure:
                        player.enemy.effects.pop("erasure_effect", None)
                    player.full_restores_used_this_run += 1
                    left = player.max_full_restores_per_run - player.full_restores_used_this_run
                    messages.extend([
                        f"💊 **MEDIC SAVE!** Full heal kept! ({player.medic_chance*100:.1f}%) {player.max_health} HP",
                        f"{player.full_restores} owned • {left} left • ✨ Saved!"
                    ])
                else:
                    heal_mult = 0.50 if (player.enemy and player.enemy.is_zone_boss and player.enemy.boss_key == "Erased" and player.enemy.effects.get("erasure_effect") == "medical") else 1.0
                    player.health = int(player.max_health * heal_mult) if heal_mult < 1.0 else player.max_health
                    if heal_mult < 1.0:
                        player.enemy.effects.pop("erasure_effect", None)
                    player.full_restores -= 1
                    player.full_restores_used_this_run += 1
                    if player.enemy and player.enemy.is_zone_boss and player.enemy.boss_key == "Contaminant":
                        stacks = player.enemy.effects.get("contamination", 0)
                        if stacks > 0:
                            removed = min(3, stacks)
                            player.enemy.effects["contamination"] = stacks - removed
                            player.enemy.effects["contamination_skip_next"] = 1
                            messages.append(f"☣️ Full Restore removes {removed} Contamination → {stacks - removed}/5.")
                    left = player.max_full_restores_per_run - player.full_restores_used_this_run
                    messages.extend([
                        f"✨ **Full heal!** {player.health} HP",
                        f"{player.full_restores} owned • {left} left"
                    ])
            heal_item = None

        if heal_item == "painkillers":
            if player.painkillers_used_this_run >= player.max_painkillers_per_run:
                messages.append(f"⚠️ Limit: {player.max_painkillers_per_run}/run.")
                heal_failed = True
            elif player.painkillers <= 0:
                messages.append("❌ No painkillers.")
                heal_failed = True
            elif player.health >= player.max_health:
                messages.append("❤️ Full HP!")
                heal_failed = True
            else:
                amount = max(1, int(player.max_health * 0.40))
                # MEDIC STAR CHECK - chance to not consume
                if player.medic_chance > 0 and random.random() < player.medic_chance:
                    if player.enemy and player.enemy.is_zone_boss and player.enemy.boss_key == "Erased" and player.enemy.effects.get("erasure_effect") == "medical":
                        amount = max(1, amount // 2)
                        player.enemy.effects.pop("erasure_effect", None)
                    player.health = min(player.max_health, player.health + amount)
                    player.painkillers_used_this_run += 1
                    left = player.max_painkillers_per_run - player.painkillers_used_this_run
                    messages.extend([
                        f"💊 **MEDIC SAVE!** +{amount} HP without using item! ({player.medic_chance*100:.1f}%) Now {player.health}/{player.max_health}",
                        f"{player.painkillers} owned • {left} left • ✨ Saved!"
                    ])
                else:
                    player.health = min(player.max_health, player.health + amount)
                    player.painkillers -= 1
                    player.painkillers_used_this_run += 1
                    if player.enemy and player.enemy.is_zone_boss and player.enemy.boss_key == "Contaminant":
                        stacks = player.enemy.effects.get("contamination", 0)
                        if stacks > 0:
                            player.enemy.effects["contamination"] = stacks - 1
                            player.enemy.effects["contamination_skip_next"] = 1
                            messages.append(f"☣️ Painkiller removes 1 Contamination → {stacks - 1}/5.")
                    left = player.max_painkillers_per_run - player.painkillers_used_this_run
                    messages.extend([
                        f"💊 **+{amount} HP!** Now {player.health}/{player.max_health}",
                        f"{player.painkillers} owned • {left} left"
                    ])
            heal_item = None

        if heal_item is not None:
            return ["Choose heal item."]

        # Healing is a free combat action: it restores HP without consuming
        # the player's turn, so the enemy does not get an attack afterward.
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
        is_boss_target = enemy.is_bloater or enemy.is_zone_boss or getattr(enemy, "is_void_boss", False)
        # A boss can only be hit by the Bazooka once per encounter.
        # Normal enemies can be hit repeatedly as long as the player can pay for ammo.
        if is_boss_target and player.void_bazooka_boss_fired:
            return ["⚠️ **Void Bazooka already fired at this boss!** Finish it with your primary weapon."]
        # One free round is loaded at the start of every Void run. After that,
        # each additional shot costs 10 Void Essence.
        if player.void_bazooka_ammo > 0:
            player.void_bazooka_ammo -= 1
            ammo_cost = 0
        else:
            extra_essence = 1 if (enemy.is_zone_boss and enemy.boss_key == "Erased" and enemy.effects.get("erasure_effect") == "essence") else 0
            total_cost = VOID_BAZOOKA_AMMO_COST + extra_essence
            if player.void_essence < total_cost:
                return [f"❌ **No Void Bazooka ammo!** This shot costs ◈{total_cost} Void Essence."]
            player.void_essence -= total_cost
            if extra_essence:
                enemy.effects.pop("erasure_effect", None)
            ammo_cost = total_cost
        if is_boss_target:
            player.void_bazooka_boss_fired = True
        void_level = max(0, min(VOID_UPGRADE_MAX, player.void_weapon_level))
        raw_damage = int(bazooka["damage"] + void_level * VOID_BAZOOKA_DAMAGE_PER_LEVEL)
        boss_mult = bazooka["level_10_boss_mult"] if void_level >= VOID_UPGRADE_MAX else bazooka["boss_mult"]
        multiplier = boss_mult if is_boss_target else 1.0
        perk_multiplier, perk_text = _consume_void_offense_bonus(player, enemy)
        boss_attack_mult = 1.0
        if enemy.is_zone_boss and enemy.boss_key == "Erased" and enemy.effects.get("erasure_effect") == "weapon":
            boss_attack_mult *= 0.75
            enemy.effects.pop("erasure_effect", None)
        frost_mult = 0.90 if (enemy.is_zone_boss and enemy.boss_key == "Wendigo" and enemy.effects.get("boss_frost", 0) >= 3) else 1.0
        erased_final_mult = 1.25 if (enemy.is_zone_boss and enemy.boss_key == "Erased" and enemy.health <= enemy.max_health * 0.20) else 1.0
        bazooka_damage = int(raw_damage * multiplier * perk_multiplier * boss_attack_mult * frost_mult * erased_final_mult)
        enemy.health = max(0, enemy.health - bazooka_damage)
        boss_text = f" ×{multiplier:.1f} BOSS DAMAGE" if is_boss_target else ""
        ammo_text = "FREE RUN AMMO" if ammo_cost == 0 else f"-◈{ammo_cost} Essence"
        perk_suffix = f" • ⚡ {perk_text}" if perk_text else ""
        messages.append(f"💥 **VOID BAZOOKA!** Hit **{enemy.name} for {bazooka_damage} dmg**! (Base {raw_damage}{boss_text}) ◈ Void Lvl {void_level}/{VOID_UPGRADE_MAX} • {ammo_text}{perk_suffix}")
        if enemy.is_zone_boss and bazooka_damage > 0:
            messages.extend(_apply_boss_player_attack_counter(player, bazooka_damage))
            if player.health <= 0:
                player.health = player.max_health
                player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
                player.magazine = 0
                player.run_active = False
                player.enemy = None
                messages.append(f"💀 **The {enemy.name} got you!**")
                messages.extend(_grant_end_of_run_rewards(player))
                return messages
        # No standard crit, pet, ammo effect, or standard weapon upgrade applies.
    elif action == "heal_done":
        pass
    elif action == "attack":
        ammo_data = AMMO[player.ammo_name]
        base_cost = int(ammo_data["cost_per_attack"])
        # NEW: Weapon shots per attack
        weapon_data = WEAPONS.get(player.weapon_name, WEAPONS["Pistol"])
        shots = int(weapon_data.get("shots", 1))
        cost = base_cost * shots

        # NEW: Mag size must support ammo type - e.g. Sawed-Off mag 2 can't use Shock cost 6
        # Check if max magazine size is too small for this ammo type (even with 1 shot)
        current_mag_size = effective_magazine_size(player)
        if current_mag_size < base_cost:
            return [f"❌ **{player.weapon_name} mag too small for {player.ammo_name}!**", f"Need mag size {base_cost}, you have {current_mag_size}. Upgrade mag or use lighter ammo.", f"🔧 {player.weapon_name} {player.magazine}/{current_mag_size} can't fit {player.ammo_name} ({base_cost}/shot)"]
        if current_mag_size < cost:
            return [f"❌ **{player.weapon_name} mag too small for {shots}x {player.ammo_name}!**", f"Need mag size {cost} ({base_cost}x{shots} shots), you have {current_mag_size}. Upgrade mag!", f"🔧 {player.weapon_name} can't do {shots}x {player.ammo_name}"]

        if enemy.is_zone_boss and enemy.boss_key == "Wendigo" and enemy.effects.pop("wendigo_frozen", 0):
            messages.append("🥶 **FROZEN!** Your next normal attack is skipped. Frost resets to 0.")
            messages.extend(_enemy_damage(player))
            return messages

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

        # Wendigo counterplay: Incendiary ammo removes 2 boss Frost stacks.
        if enemy.is_zone_boss and enemy.boss_key == "Wendigo" and player.ammo_name == "Incendiary":
            frost_before = enemy.effects.get("boss_frost", 0)
            if frost_before > 0:
                frost_removed = min(2, frost_before)
                enemy.effects["boss_frost"] = frost_before - frost_removed
                messages.append(f"🔥 Incendiary clears **{frost_removed} Frost** from the Wendigo.")
                if enemy.effects["boss_frost"] <= 0:
                    enemy.effects.pop("boss_frost", None)

        mod = ammo_modifier(player, player.ammo_name)
        perk_multiplier, perk_text = _consume_void_offense_bonus(player, enemy)
        total_dmg = 0
        total_crits = 0
        hit_details = []
        boss_attack_mult = _boss_damage_multiplier_for_player_action(enemy)
        # The Erased's final phase makes all player attacks deal +25% damage.
        # This applies to each normal attack action (and is intentionally
        # evaluated after the attack's current HP threshold is known).
        erased_final_mult = 1.25 if (enemy.is_zone_boss and enemy.boss_key == "Erased" and enemy.health <= enemy.max_health * 0.20) else 1.0
        weapon_erasure_active = bool(enemy.is_zone_boss and enemy.boss_key == "Erased" and enemy.effects.get("erasure_effect") == "weapon")
        if weapon_erasure_active:
            boss_attack_mult *= 0.75
            enemy.effects.pop("erasure_effect", None)
        frost_mult = 0.90 if (enemy.is_zone_boss and enemy.boss_key == "Wendigo" and enemy.effects.get("boss_frost", 0) >= 3) else 1.0
        for shot_i in range(shots):
            dmg = int(player.weapon_damage * mod * perk_multiplier * boss_attack_mult * frost_mult * erased_final_mult)
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
        final_phase_txt = " 🔥 **ERASED FINAL PHASE: +25% DAMAGE**" if erased_final_mult > 1 else ""
        if shots > 1:
            messages.append(f"🔫 **{shots}x** {player.weapon_name} Hit **{enemy.name} for {total_dmg}** ({'+'.join(map(str, hit_details))}){crit_txt}{magical_txt}{perk_txt} using {player.ammo_name} ({base_cost}x{shots}={cost} ammo){mod_txt}{final_phase_txt}")
        else:
            messages.append(f"🔫 Hit **{enemy.name} for {total_dmg}**{crit_txt}{magical_txt}{perk_txt} using {player.ammo_name} ({cost}/shot){mod_txt}{final_phase_txt}")
        
        # DOUBLE-TAP: per-weapon premium upgrade. The proc immediately repeats
        # the weapon attack for free, inherits weapon/ammo/crit behavior, cannot
        # chain, and does not trigger a second pet attack or consume ammo.
        double_tap_level = player.weapon_upgrade_level("double_tap")
        double_tap_bloater_tick = False
        if enemy.health > 0 and double_tap_level > 0 and random.random() < player.double_tap_chance:
            bonus_total = 0
            bonus_crits = 0
            bonus_hits = []
            for shot_i in range(shots):
                bonus_dmg = int(player.weapon_damage * mod * frost_mult * erased_final_mult * (0.75 if weapon_erasure_active else 1.0))
                bonus_crit = random.random() < player.crit_chance
                if bonus_crit:
                    bonus_dmg = int(bonus_dmg * 2)
                    bonus_crits += 1
                enemy.health = max(0, enemy.health - bonus_dmg)
                bonus_total += bonus_dmg
                bonus_hits.append(bonus_dmg)
                if enemy.health <= 0:
                    break
            dt_crit_txt = f" **{bonus_crits}x CRIT!**" if bonus_crits else ""
            dt_detail = '+'.join(map(str, bonus_hits)) if len(bonus_hits) > 1 else str(bonus_total)
            messages.append(f"🔫 **DOUBLE-TAP!** Free repeat for **{bonus_total} dmg** ({dt_detail}){dt_crit_txt} using {player.ammo_name} — no ammo consumed.")
            # A Double-Tap is a real second attack for Bloater fuse purposes.
            # If it consumes the penultimate fuse point, the normal Bloater
            # resolver below consumes the final point and handles the explosion.
            if enemy.is_bloater and enemy.health > 0:
                enemy.bloater_timer = max(1, enemy.bloater_timer - 1)
                double_tap_bloater_tick = True

            # Apply the equipped ammo's proc to the bonus attack as part of
            # mimicking the first attack. It still cannot trigger Double-Tap.
            effect = ammo_data["effect"]
            chances = {"bleed": 0.25, "burn": 0.30, "freeze": 0.25, "poison": 0.40, "shock": 0.20}
            if enemy.health > 0 and effect and random.random() < chances[effect]:
                durations = {"bleed": 3, "burn": 3, "freeze": 4, "poison": 5, "shock": 1}
                enemy.effects[effect] = durations[effect]
                if effect == "freeze":
                    enemy.effects["freeze_dot"] = 2
                messages.append(f"💥 Double-Tap {player.ammo_name} procs **{effect}**!")
                if effect == "shock":
                    shock_dmg = int(30 * ammo_modifier(player, "Shock"))
                    enemy.health = max(0, enemy.health - shock_dmg)
                    bonus_total += shock_dmg
                    messages.append(f"⚡ Double-Tap Shock deals {shock_dmg} dmg!")


        # NORMAL SHOCK PROC: resolve its instant damage before boss-action
        # accounting so Kingpin sees the full damage dealt by this one attack
        # action (weapon + Double-Tap + pet + Shock). Other ammo procs remain
        # in their original post-action position below.
        effect = ammo_data["effect"]
        chances = {"bleed": 0.25, "burn": 0.30, "freeze": 0.25, "poison": 0.40, "shock": 0.20}
        if enemy.health > 0 and effect == "shock" and random.random() < chances["shock"]:
            enemy.effects["shock"] = 1
            shock_dmg = int(30 * ammo_modifier(player, "Shock"))
            enemy.health = max(0, enemy.health - shock_dmg)
            total_dmg += shock_dmg
            messages.append(f"💥 {player.ammo_name} procs **shock**!")
            messages.append(f"⚡ Shock deals {shock_dmg} dmg!")

        # PET ATTACK CHECK
        if enemy.health > 0 and player.pet_chance > 0 and random.random() < player.pet_chance:
            pet_dmg = player.pet_damage
            enemy.health = max(0, enemy.health - pet_dmg)
            messages.append(f"🐺 **Wolf bites {enemy.name} for {pet_dmg} dmg!** ({player.pet_chance*100:.0f}% chance)")
            total_dmg += pet_dmg

        # Double-Tap is part of the same successful attack action. Include its
        # damage in the action total so Kingpin's 500+ bounty threshold sees the
        # full action damage, while the action counter itself still increments once.
        if double_tap_level > 0 and 'bonus_total' in locals():
            total_dmg += bonus_total

        # Count one successful player attack action for boss mechanics.
        if enemy.is_zone_boss and total_dmg > 0:
            messages.extend(_apply_boss_player_attack_counter(player, total_dmg))
            if player.health <= 0:
                player.health = player.max_health
                player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
                player.magazine = 0
                player.run_active = False
                player.enemy = None
                messages.append(f"💀 **The {enemy.name} got you!**")
                messages.extend(_grant_end_of_run_rewards(player))
                return messages

        # BLOATER TICKING BOMB LOGIC - 5 attacks then 65% max HP explosion
        if enemy.is_bloater and enemy.health > 0:
            if not double_tap_bloater_tick:
                enemy.bloater_timer -= 1
            else:
                # The Double-Tap already consumed one fuse point. The normal
                # attack consumes the next point, preserving a 2-attacks-used
                # outcome for a successful Double-Tap turn.
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
        if enemy.health > 0 and effect and effect != "shock" and random.random() < chances[effect]:
            durations = {"bleed": 3, "burn": 3, "freeze": 4, "poison": 5, "shock": 1}
            enemy.effects[effect] = durations[effect]
            if effect == "freeze":
                # Frostbite: halve incoming enemy damage for 4 attacks + 10
                # bonus damage on the next 2 player actions.
                enemy.effects["freeze_dot"] = 2
            messages.append(f"💥 {player.ammo_name} procs **{effect}**!")
    elif action == "reload":
        # A successful reload is a real combat turn: after loading ammo,
        # execution continues to the normal enemy-damage resolution below.
        # Only the full-magazine check in _combat_action_noop() makes reload
        # a free no-op.
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
        amount = min(effective_magazine_size(player) - player.magazine, spare)
        player.magazine += amount
        player.spare_ammo[player.ammo_name] = spare - amount
        messages.append(f"🔄 Reloaded {amount} {player.ammo_name}. {player.spare_ammo[player.ammo_name]} spare left.")

        # Resolve pending DoT after the reload has completed. If it kills the
        # enemy, finish the enemy immediately and skip the enemy's attack.
        messages.extend(_apply_damage_over_time(player))
        if enemy.health <= 0:
            messages.extend(_finish_enemy(player))
            return messages
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
        player.equipped_weapon = item
        player.recalc_stats()
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        return [f"🔫 Re-equipped **{item}** for free."]
    if player.money < weapon["price"]:
        return [f"Need ${weapon['price']} for {item}, you have ${player.money}"]
    player.money -= weapon["price"]
    player.weapon_name = item
    player.equipped_weapon = item
    player.recalc_stats()
    if item not in player.owned_weapons:
        player.owned_weapons.append(item)
    player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
    player.magazine = 0
    return [f"🔫 Equipped **{item}**. ${player.money} left."]

def equip_ammo(player: Survivor, ammo_name: str) -> list[str]:
    if player.run_active:
        return ["⚠️ Can't change ammo during a run! Flee first."]
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
    return [f"🗺️ Travelled to **{zone_name}**.", ammo_effectiveness_text(player), f"*{ZONES[zone_name]['desc']}*"]

def weapon_upgrade_summary(player: Survivor, weapon_name: str | None = None) -> str:
    wn = weapon_name or player.weapon_name
    player._ensure_weapon_upgrades()
    lv = player.weapon_upgrades.get(wn, {"damage": 0, "mag": 0, "crit": 0})
    return f"⚔️ Dmg Lv {lv['damage']} • 📦 Mag Lv {lv['mag']} • 🎯 Crit Lv {lv['crit']} • 🔫 Double-Tap Lv {lv.get('double_tap', 0)}"

def get_weapon_upgrade_cost(player: Survivor, weapon_name: str, stat: str) -> int:
    stat = stat.lower().strip()
    if weapon_name not in WEAPONS or stat not in WEAPON_UPGRADE_BASE_COSTS:
        return 999999999
    level = player.weapon_upgrade_level(stat, weapon_name)
    max_level = {
        "damage": WEAPON_DAMAGE_MAX_LEVEL,
        "mag": WEAPON_MAG_MAX_LEVEL,
        "crit": WEAPON_CRIT_MAX_LEVEL,
        "double_tap": DOUBLE_TAP_MAX_LEVEL,
    }.get(stat)
    if max_level is not None and level >= max_level:
        return 0
    if stat == "double_tap":
        base_cost = DOUBLE_TAP_COSTS[level]
        return int(base_cost * DOUBLE_TAP_WEAPON_MULT.get(weapon_name, 1.0))
    rarity = WEAPON_UPGRADE_RARITY_MULT.get(weapon_name, 1.0)
    return int(WEAPON_UPGRADE_BASE_COSTS[stat] * rarity * (WEAPON_UPGRADE_EARLY_MULT[stat] ** min(level, 10)) * (WEAPON_UPGRADE_LATE_MULT[stat] ** max(level - 10, 0)))

def upgrade_weapon(player: Survivor, weapon_name: str, stat: str) -> list[str]:
    if player.run_active:
        return ["⚠️ Can't upgrade weapons during a run! Flee first."]
    if weapon_name not in WEAPONS:
        return ["❌ That weapon doesn't exist."]
    if weapon_name not in player.owned_weapons:
        return [f"🔒 You don't own **{weapon_name}** yet."]
    stat = stat.lower().strip()
    if stat not in WEAPON_UPGRADE_BASE_COSTS:
        return ["❌ Invalid weapon upgrade."]
    old = player.weapon_upgrade_level(stat, weapon_name)
    max_levels = {
        "damage": WEAPON_DAMAGE_MAX_LEVEL,
        "mag": WEAPON_MAG_MAX_LEVEL,
        "crit": WEAPON_CRIT_MAX_LEVEL,
        "double_tap": DOUBLE_TAP_MAX_LEVEL,
    }
    if old >= max_levels[stat]:
        max_text = {
            "damage": f"Level {WEAPON_DAMAGE_MAX_LEVEL}",
            "mag": f"Level {WEAPON_MAG_MAX_LEVEL}",
            "crit": "40%",
            "double_tap": "10%",
        }[stat]
        return [f"🔥 **{weapon_name} {stat.replace('_', ' ').title()} is MAXED at {max_text}!**"]
    cost = get_weapon_upgrade_cost(player, weapon_name, stat)
    if player.money < cost:
        return [f"❌ Need ${cost:,} for {weapon_name} {stat} upgrade, you have ${player.money:,}."]
    player._ensure_weapon_upgrades()
    player.money -= cost
    player.weapon_upgrades[weapon_name][stat] = old + 1
    player.recalc_stats()
    if stat == "double_tap":
        chance = min((old + 1), 10)
        detail = f"Double-Tap chance → **{chance}%** (free second attack)"
    elif stat == "damage":
        damage_per_upgrade = WEAPON_DAMAGE_PER_UPGRADE.get(weapon_name, 3)
        value = WEAPONS[weapon_name]["damage"] + (old + 1) * damage_per_upgrade
        detail = f"+{damage_per_upgrade} damage → **{value}**"
    elif stat == "mag":
        shots = int(WEAPONS[weapon_name].get("shots", 1))
        value = WEAPONS[weapon_name]["mag"] + (old + 1) * shots
        detail = f"+{shots} magazine → **{value}**"
    else:
        value = min(0.02 + old * 0.005, 0.40)
        detail = f"Crit → **{value*100:.1f}%**"
    return [f"🔧 **{weapon_name} {stat.capitalize()} upgraded!** {detail} | Lv {old + 1} | Paid **${cost:,}** | 💰 ${player.money:,} left."]


def get_combat_medic_cost(player: Survivor) -> int:
    level = player.combat_medic_level
    if level >= COMBAT_MEDIC_MAX_LEVEL:
        return 0
    return COMBAT_MEDIC_COSTS[level]


def upgrade_combat_medic(player: Survivor) -> list[str]:
    if player.run_active:
        return ["⚠️ Can't upgrade Combat Medic during a run! Flee first."]
    level = player.combat_medic_level
    if level >= COMBAT_MEDIC_MAX_LEVEL:
        return ["💉 **Combat Medic is MAXED at Level 6!**"]
    cost = get_combat_medic_cost(player)
    if player.money < cost:
        return [f"❌ Need ${cost:,} for Combat Medic Level {level + 1}, you have ${player.money:,}."]
    player.money -= cost
    player.combat_medic_level = level + 1
    return [
        f"💉 **Combat Medic → Level {player.combat_medic_level}/6!**",
        f"Run limits: 💊 {player.max_painkillers_per_run} Painkillers • ✨ {player.max_full_restores_per_run} Full Restores",
        f"Paid **${cost:,}** • 💰 ${player.money:,} left.",
    ]


def get_upgrade_cost(player: Survivor, stat: str) -> int:
    """Balanced exponential scaling costs"""
    stat = stat.lower()
    # Base costs
    bases = {
        "health": 200,
        "armor": 450,
        "scavenger": 700,
    }
    # Two-stage scaling: strong early/mid-game growth, then a flatter late-game curve.
    # The first 10 upgrade levels keep the existing progression. From level 10
    # onward, each stat uses a gentler multiplier so late-game upgrades stay
    # expensive without becoming effectively unreachable.
    early_mults = {
        "health": 1.40,
        "armor": 1.50,
        "scavenger": 1.65,
    }
    late_mults = {
        "health": 1.25,
        "armor": 1.28,
        "scavenger": 1.25,
    }
    if stat not in bases:
        return 999999
    count = 0
    if stat == "health": count = player.health_upgrades
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
    """Universal cash upgrades only. Weapon damage/mag/crit are per-weapon."""
    if player.run_active:
        return ["⚠️ Can't upgrade during a run! Flee first."]
    alias = {"health":"health", "hp":"health", "max_health":"health", "armor":"armor", "armour":"armor", "defense":"armor", "scavenger":"scavenger", "loot":"scavenger", "money":"scavenger"}
    canonical = alias.get(stat.lower().strip(), stat.lower().strip())
    cost = get_upgrade_cost(player, canonical)
    if player.money < cost:
        return [f"❌ Need ${cost} for {canonical}, you have ${player.money}"]
    player.money -= cost
    if canonical == "health":
        player.max_health += 20; player.health_upgrades += 1; player.health = player.max_health
        return [f"❤️ Max HP → **{player.max_health}** (+20). ${player.money} left. Lvl {player.health_upgrades}"]
    if canonical == "armor":
        player.armor_upgrades += 1
        return [f"🛡️ Armor → **-{player.armor_reduction} dmg**. ${player.money} left. Lvl {player.armor_upgrades}"]
    if canonical == "scavenger":
        player.scavenger_upgrades += 1
        return [f"💰 Loot bonus → **+{int((player.scavenger_bonus-1)*100)}%** (+10% per lvl). ${player.money} left. Lvl {player.scavenger_upgrades}"]
    player.money += cost
    return [f"❓ Unknown universal upgrade '{stat}'. Try: health, armor, scavenger"]


STAR_MAX_LEVELS = {
    "dodge": 41,      # 10% + 0.5% per extra level = 30%
    "magical": 31,    # 5% + 0.5% per extra level = 20%
    "medic": 21,      # 2% + 0.25% per extra level = 7%
    "pet": 6,         # 5% + 1% per extra level = 10%
    "xp": 16,         # 10% + 1% per extra level = 25%
}


def get_star_upgrade_cost(player: Survivor, stat: str) -> int:
    """Star upgrades: 5 to unlock, then pattern 3,3,4,4,5,5,6,6...; 0 means maxed."""
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
    if canonical in STAR_MAX_LEVELS and lvl >= STAR_MAX_LEVELS[canonical]:
        return 0
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

    # Read the current level before checking the cap.
    lvl = {
        "dodge": player.star_dodge_upgrades,
        "magical": player.star_magical_upgrades,
        "medic": player.star_medic_upgrades,
        "pet": player.star_pet_upgrades,
        "xp": player.star_xp_upgrades,
    }.get(canonical, 0)
    if canonical in STAR_MAX_LEVELS and lvl >= STAR_MAX_LEVELS[canonical]:
        caps = {"dodge": "30%", "magical": "20%", "medic": "7%", "pet": "10%", "xp": "25%"}
        return [f"❌ {canonical.title()} already maxed at {caps[canonical]}! (Lvl {lvl})"]
    cost = get_star_upgrade_cost(player, canonical)
    if player.stars < cost:
        return [f"Need ⭐{cost} for {canonical}, you have ⭐{player.stars}. Keep grinding waves!"]

    # Check caps before purchase
    if canonical == "dodge":
        if player.star_dodge_upgrades > 0 and player.dodge_chance >= 0.30:
            return [f"❌ Dodge already maxed at 30%! (Lvl {player.star_dodge_upgrades})"]
        player.stars -= cost
        player.star_dodge_upgrades += 1
        next_text = "MAXED" if player.star_dodge_upgrades >= STAR_MAX_LEVELS["dodge"] else f"Next: ⭐{get_star_upgrade_cost(player,'dodge')} (cap 30%)"
        return [f"💨 Dodge → **{player.dodge_chance*100:.1f}%** dodge chance (Lvl {player.star_dodge_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | {next_text}"]
    if canonical == "magical":
        if player.star_magical_upgrades > 0 and player.magical_bullet_chance >= 0.20:
            return [f"❌ Magical Bullet already maxed at 20%! (Lvl {player.star_magical_upgrades})"]
        player.stars -= cost
        player.star_magical_upgrades += 1
        next_text = "MAXED" if player.star_magical_upgrades >= STAR_MAX_LEVELS["magical"] else f"Next: ⭐{get_star_upgrade_cost(player,'magical')} (cap 20%)"
        return [f"✨ Magical Bullet → **{player.magical_bullet_chance*100:.1f}%** free shot (Lvl {player.star_magical_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | {next_text}"]
    if canonical == "medic":
        if player.star_medic_upgrades > 0 and player.medic_chance >= 0.07:
            return [f"❌ Medic already maxed at 7%! (Lvl {player.star_medic_upgrades})"]
        player.stars -= cost
        player.star_medic_upgrades += 1
        next_text = "MAXED" if player.star_medic_upgrades >= STAR_MAX_LEVELS["medic"] else f"Next: ⭐{get_star_upgrade_cost(player,'medic')} (cap 7%)"
        return [f"💊 Medic → **{player.medic_chance*100:.2f}%** heal drop (Lvl {player.star_medic_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | {next_text}"]
    if canonical == "pet":
        if player.star_pet_upgrades > 0 and player.pet_chance >= 0.10:
            return [f"❌ Pet already maxed at 10%! (Lvl {player.star_pet_upgrades})"]
        player.stars -= cost
        player.star_pet_upgrades += 1
        next_text = "MAXED" if player.star_pet_upgrades >= STAR_MAX_LEVELS["pet"] else f"Next: ⭐{get_star_upgrade_cost(player,'pet')} (cap 10%)"
        return [f"🐺 Wolf Pet → **{player.pet_chance*100:.0f}%** to deal {player.pet_damage} dmg (Lvl {player.star_pet_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | {next_text}"]

    if canonical == "xp":
        if player.star_xp_upgrades > 0 and player.xp_bonus >= 0.25:
            return [f"❌ XP Gain already maxed at 25%! (Lvl {player.star_xp_upgrades})"]
        player.stars -= cost
        player.star_xp_upgrades += 1
        next_text = "MAXED" if player.star_xp_upgrades >= STAR_MAX_LEVELS["xp"] else f"Next: ⭐{get_star_upgrade_cost(player,'xp')} (cap 25%)"
        return [f"✨ XP Gain → **{player.xp_bonus*100:.1f}%** bonus XP (Lvl {player.star_xp_upgrades}) | Paid ⭐{cost} | ⭐ {player.stars} left | {next_text}"]

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





DAILY_COOLDOWN_SECONDS = 24 * 60 * 60

def daily_crate_rewards(player: Survivor) -> tuple[int, int, int]:
    """Small level-scaled daily reward: cash, Standard ammo, XP."""
    cash = int(min(100 + player.level * 5, 1100) * cash_boost_multiplier(player))
    ammo = min(10 + player.level // 10, 30)
    xp = int(min(50 + player.level * 2, 400) * xp_boost_multiplier(player))
    return cash, ammo, xp

def daily_crate_status(player: Survivor) -> tuple[bool, int]:
    """Return (claimable, seconds_remaining) using UTC and a persistent timestamp."""
    if not player.daily_claimed_at:
        return True, 0
    try:
        last = datetime.fromisoformat(player.daily_claimed_at)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        remaining = max(0, int(DAILY_COOLDOWN_SECONDS - elapsed))
        return remaining <= 0, remaining
    except (TypeError, ValueError):
        # Corrupt/legacy timestamp: let the survivor claim and replace it.
        return True, 0

def format_duration(seconds: int) -> str:
    hours, rem = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"

def claim_daily_crate(player: Survivor) -> list[str]:
    """Claim the daily crate. Returns player-facing messages."""
    claimable, remaining = daily_crate_status(player)
    if not claimable:
        return [f"⏳ **Daily crate already claimed.** Come back in **{format_duration(remaining)}**."]

    cash, ammo, xp = daily_crate_rewards(player)
    old_level = player.level
    player.money += cash
    player.spare_ammo["Standard"] = player.spare_ammo.get("Standard", 0) + ammo
    player.xp += xp
    level_ups = max(0, player.level - old_level)
    if level_ups:
        player.stars += level_ups
    player.daily_claimed_at = datetime.now(timezone.utc).isoformat()

    rewards = [
        "🎁 **DAILY SURVIVOR CRATE OPENED!**",
        f"💵 **+${cash} Cash**",
        f"🔫 **+{ammo} Standard Ammo**",
        f"✨ **+{xp} XP**",
    ]
    if level_ups:
        rewards.append(f"🎉 **LEVEL UP!** Level {player.level}! +{level_ups} ⭐")
    return rewards


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
        f"💥 Dmg: {player.weapon_damage} | 📦 Mag: {player.magazine_size} | 🎯 Crit: {player.crit_chance*100:.1f}% | {weapon_upgrade_summary(player)}",
        f"🎯 Crit: {int(player.crit_chance*100)}% | 🛡️ Armor: -{player.armor_reduction} | 💰 Loot: +{int((player.scavenger_bonus-1)*100)}%",
        f"💰 ${player.money} | ⭐ {player.stars} | ✨ {player.xp} XP ({earned}/{needed})",
        f"🔫 {player.weapon_name} [{player.ammo_name}] | 📦 Spare: {player.get_spare()}",
         f"◈ Void Essence: {player.void_essence} | Void Bazooka: {'Owned' if 'Void Bazooka' in player.void_weapons_owned else 'Locked'} | Void Lvl {player.void_weapon_level}/10",
        f"🎒 Ammo: {', '.join([f'{k}:{v}' for k,v in player.spare_ammo.items() if v>0]) or 'Empty'}",
        f"💉 Combat Medic: L{player.combat_medic_level}/6 | Run limits: 💊{player.max_painkillers_per_run} • ✨{player.max_full_restores_per_run}",
        f"💊 Painkillers: {player.painkillers} | ✨ Restores: {player.full_restores}",
        f"🗺️ Zone: {player.zone_name} | Guns: {', '.join(player.owned_weapons)}",
    ]
    return "\n".join(lines)

def get_status(player: Survivor, display_name: str = "Survivor") -> str:
    return status(player, display_name)

def get_detailed_status(player: Survivor, display_name: str = "Survivor") -> str:
    return status_detailed(player, display_name)





def _parse_xp_boost_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None

def _xp_boost_active(value: str | None) -> bool:
    expiry = _parse_xp_boost_expiry(value)
    return bool(expiry and expiry > datetime.now(timezone.utc))

def xp_boost_multiplier(player: Survivor) -> float:
    """Return active XP multiplier; personal/global boosts never stack."""
    return 1.5 if (_xp_boost_active(getattr(player, "xp_boost_until", None)) or _xp_boost_active(GLOBAL_XP_BOOST_UNTIL)) else 1.0

def cash_boost_multiplier(player: Survivor) -> float:
    """Return active cash multiplier; personal/global boosts never stack."""
    return 1.5 if (_xp_boost_active(getattr(player, "cash_boost_until", None)) or _xp_boost_active(GLOBAL_CASH_BOOST_UNTIL)) else 1.0

class GameStore:
    """CONSTANT SAVE - every player action triggers an instant persistent save.

    A PostgreSQL/load failure is never treated as an empty game.
    """
    def __init__(self):
        self.players = {}
        self._save_count = 0
        self._action_locks = {}
        self._save_locks = {}
        self._reset_lock = asyncio.Lock()
        self._reset_generation = 0
        self.load()

    def action_lock(self, user_id: int):
        """Return a per-player lock for serialising combat state mutations."""
        import asyncio
        key = str(user_id)
        lock = self._action_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._action_locks[key] = lock
        return lock

    def save_lock(self, user_id: int):
        """Return a per-player lock so database snapshots are written in order."""
        import asyncio
        key = str(user_id)
        lock = self._save_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._save_locks[key] = lock
        return lock

    @staticmethod
    def _player_dict(player):
        try:
            return player.to_dict()
        except Exception:
            return asdict(player)

    def get(self, user_id: int):
        key = str(user_id)
        if key not in self.players:
            # Do not perform blocking PostgreSQL I/O from an async callback just
            # because this is the first time we have seen a user. The caller
            # persists state through save_one_async(), and background autosave
            # covers idle/newly-created survivors as well.
            self.players[key] = Survivor()
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
        key = str(key)
        p = self.players.get(key)
        if p is None:
            return
        # Snapshot while the per-player action lock is held. The reset
        # generation prevents a save that started before /launch_reset from
        # writing stale progress back over the fresh-launch state.
        async with self.action_lock(int(key)):
            generation = self._reset_generation
            snapshot = self._player_dict(p)
        async with self.save_lock(int(key)):
            if generation != self._reset_generation:
                # A full reset happened while this save was waiting. Re-snapshot
                # the current (post-reset) player instead of restoring old data.
                p = self.players.get(key)
                if p is None:
                    return
                async with self.action_lock(int(key)):
                    generation = self._reset_generation
                    snapshot = self._player_dict(p)
            ok = await asyncio.to_thread(save_player, key, snapshot)
            if not ok:
                raise RuntimeError(f"Could not save player {key}")
            self._save_count += 1

    async def reset_all_players(self) -> int:
        """Reset every persisted survivor to a brand-new launch state.

        Player IDs remain in storage, but all gameplay progression and
        leaderboard records are replaced with Survivor defaults. The separate
        Game Admin list is intentionally untouched.
        """
        async with self._reset_lock:
            # Advance the generation before replacing any player objects so
            # in-flight saves cannot write pre-reset snapshots after this point.
            self._reset_generation += 1
            global GLOBAL_XP_BOOST_UNTIL, GLOBAL_CASH_BOOST_UNTIL
            GLOBAL_XP_BOOST_UNTIL = None
            GLOBAL_CASH_BOOST_UNTIL = None
            keys = list(self.players.keys())
            for key in keys:
                self.players[key] = Survivor()

            if not keys:
                print("[LAUNCH RESET] No player records found; nothing to reset.")
                return 0

            # Persist the complete fresh state before reporting success.
            results = await asyncio.gather(
                *(self._save_fresh_player(key) for key in keys),
                return_exceptions=True,
            )
            failed = [f"{key}: {result}" for key, result in zip(keys, results) if isinstance(result, Exception)]
            if failed:
                raise RuntimeError("Launch reset failed for: " + "; ".join(failed[:10]))

            print(f"[LAUNCH RESET] Reset {len(keys)} player records to fresh-launch defaults.")
            return len(keys)

    async def _save_fresh_player(self, key: str):
        """Save one already-reset player without taking a pre-reset snapshot."""
        async with self.save_lock(int(key)):
            p = self.players.get(str(key))
            if p is None:
                return
            snapshot = self._player_dict(p)
            ok = await asyncio.to_thread(save_player, str(key), snapshot)
            if not ok:
                raise RuntimeError(f"Could not save player {key}")
            self._save_count += 1

    async def save_async(self):
        """Persist every player without racing a full launch reset."""
        async with self._reset_lock:
            if not self.players:
                print("[AUTOSAVE] REFUSING ASYNC SAVE: no players are loaded")
                return
            keys = list(self.players.keys())
            results = await asyncio.gather(
                *(self.save_one_async(k) for k in keys),
                return_exceptions=True,
            )
            failed = []
            for k, result in zip(keys, results):
                if isinstance(result, Exception):
                    failed.append(f"{k}: {result}")
            if failed:
                raise RuntimeError("Failed to save players: " + "; ".join(failed[:10]))
            print(f"[AUTOSAVE] Saved {len(keys)} players to Postgres - all safe")

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
        global GLOBAL_XP_BOOST_UNTIL, GLOBAL_CASH_BOOST_UNTIL
        owner_record = self.players.get(str(OWNER_ID)) if "OWNER_ID" in globals() else None
        GLOBAL_XP_BOOST_UNTIL = getattr(owner_record, "global_xp_boost_until", None) if owner_record else None
        if GLOBAL_XP_BOOST_UNTIL and not _xp_boost_active(GLOBAL_XP_BOOST_UNTIL):
            GLOBAL_XP_BOOST_UNTIL = None
            if owner_record:
                owner_record.global_xp_boost_until = None
        GLOBAL_CASH_BOOST_UNTIL = getattr(owner_record, "global_cash_boost_until", None) if owner_record else None
        if GLOBAL_CASH_BOOST_UNTIL and not _xp_boost_active(GLOBAL_CASH_BOOST_UNTIL):
            GLOBAL_CASH_BOOST_UNTIL = None
            if owner_record:
                owner_record.global_cash_boost_until = None
        print(f"[STORE] Loaded {len(loaded)} players - PERSISTENT")

game_store = GameStore()

async def background_autosave():
    import asyncio
    await asyncio.sleep(60)
    while True:
        try:
            # Never run synchronous PostgreSQL I/O on Discord's event loop.
            # A slow DB connection must not freeze every button interaction.
            await game_store.save_async()
        except Exception as e:
            print(f"[AUTOSAVE ERROR] {e}")
        await asyncio.sleep(60)





class PlayerView(discord.ui.View):
    def __init__(self, user_id: int, store: GameStore, display_name: str = "Survivor", timeout: float | None = None):
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
        super().__init__(user_id, store, display_name, timeout=None)
        self.end_embed = end_embed

        btn_continue = discord.ui.Button(label="🏠 Main Menu", style=discord.ButtonStyle.success, row=0)
        async def cont_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            name = getattr(self, "display_name", "Survivor")
            await interaction.response.edit_message(content=status(p, display_name=name), embed=None, view=ZombieMenuView(self.user_id, self.store, display_name=name))
        btn_continue.callback = cont_cb
        self.add_item(btn_continue)

        # A RunEndedView is only shown after the run has ended, so shopping is
        # available again here. The purchase functions still enforce the
        # no-shopping-during-run rule as a second layer of protection.
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
            await interaction.response.defer()
            p = self.store.get(self.user_id)
            msgs = start_run(p)
            await self.store.save_one_async(str(self.user_id))
            embed = combat_embed(p, msgs)
            await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
        btn_again.callback = again_cb
        self.add_item(btn_again)



class LeaderboardView(PlayerView):
    """Compact leaderboard browser: Global, Server, and personal records."""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", guild_id: int | None = None, zone_name: str | None = None, timeout: float | None = None):
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


class DailyCrateView(PlayerView):
    """Dedicated Daily Survivor Crate interface with no shop/upgrade controls."""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float | None = None):
        super().__init__(user_id, store, display_name, timeout)
        self.refresh_view()

    def build_embed(self, player: Survivor) -> discord.Embed:
        claimable, remaining = daily_crate_status(player)
        cash, ammo, xp = daily_crate_rewards(player)
        embed = make_embed(
            title="🎁 DAILY SURVIVOR CRATE",
            description="A free supply drop for survivors who keep coming back.\n\nYour reward scales gently with your level.",
            color=discord.Color.green() if claimable else discord.Color.blurple(),
        )
        if claimable:
            embed.add_field(
                name="📦 Today's Crate",
                value=f"💵 **+${cash:,} Cash**\n🔫 **+{ammo} Standard Ammo**\n✨ **+{xp} XP**",
                inline=False,
            )
            embed.add_field(name="🎁 Ready to claim", value="Press **Open Daily Crate** below.", inline=False)
        else:
            embed.add_field(name="⏳ Crate already claimed", value=f"Come back in **{format_duration(remaining)}**.", inline=False)
            embed.add_field(
                name="📦 Next crate",
                value=f"💵 **+${cash:,} Cash**\n🔫 **+{ammo} Standard Ammo**\n✨ **+{xp} XP**",
                inline=False,
            )
        embed.add_field(
            name="👤 Survivor",
            value=f"Level **{player.level}** • 💰 ${player.money:,} • 🌍 {player.zone_name}",
            inline=False,
        )
        set_embed_footer(embed, text="No Essence • No shop • No upgrades from this screen")
        return embed

    def refresh_view(self):
        self.clear_items()
        player = self.store.get(self.user_id)
        claimable, _ = daily_crate_status(player)

        claim_btn = discord.ui.Button(
            label="🎁 Open Daily Crate",
            style=discord.ButtonStyle.success,
            row=0,
            disabled=not claimable,
        )

        async def claim_cb(interaction: discord.Interaction):
            await interaction.response.defer()
            lock = self.store.action_lock(self.user_id)
            async with lock:
                p = self.store.get(self.user_id)
                msgs = claim_daily_crate(p)
            if msgs and msgs[0].startswith("🎁"):
                await self.store.save_one_async(str(self.user_id))
            self.refresh_view()
            await interaction.edit_original_response(content=None, embed=self.build_embed(p), view=self)

        claim_btn.callback = claim_cb
        self.add_item(claim_btn)

        back_btn = discord.ui.Button(label="⬅️ Main Menu", style=discord.ButtonStyle.secondary, row=1)
        async def back_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            name = getattr(self, "display_name", "Survivor")
            try:
                name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            except Exception:
                pass
            await interaction.response.edit_message(
                content=status(p, display_name=name),
                embed=None,
                view=ZombieMenuView(self.user_id, self.store, display_name=name),
            )
        back_btn.callback = back_cb
        self.add_item(back_btn)


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
            await interaction.response.defer()
            p = self.store.get(self.user_id)
            if p.run_active:
                if p.enemy is None:
                    msgs = recover_stuck_run(p)
                    await self.store.save_one_async(str(self.user_id))
                    embed = combat_embed(p, msgs)
                    await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                    return
                embed = combat_embed(p, [f"🔄 Resumed your run! Wave {p.wave} | {p.zombies_remaining} zombies left"])
                await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                return
            msgs = start_run(p)
            await self.store.save_one_async(str(self.user_id))
            embed = combat_embed(p, msgs)
            await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
        btn_start.callback = start_cb
        self.add_item(btn_start)

        btn_shop = discord.ui.Button(label="🛒 Shop", style=discord.ButtonStyle.primary, row=0)
        async def shop_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            if p.run_active:
                await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                return
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
            # Acknowledge immediately because persistence can be slower than Discord's
            # component-response window.  The old flow saved before acknowledging,
            # which could produce "Zombie Survival didn’t respond in time".
            await interaction.response.defer()
            p=self.store.get(self.user_id)
            name=getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            p.leaderboard_name=name[:32]
            gid=interaction.guild.id if interaction.guild else None
            if gid is not None and str(gid) not in p.leaderboard_guilds:
                p.leaderboard_guilds.append(str(gid))
            await self.store.save_one_async(str(self.user_id))
            await interaction.edit_original_response(content=leaderboard_text(self.store, p.zone_name, None), embed=None, view=LeaderboardView(self.user_id,self.store,display_name=name,guild_id=gid,zone_name=p.zone_name))
        lb_cb.__name__ = "leaderboards_cb"
        self.add_item(btn_lb)
        btn_lb.callback = lb_cb

        # Ammo and permanent upgrades are accessed through the main Shop now.
        # They are intentionally not shown as separate buttons on the main menu.

        # Daily crate gets its own isolated interface. It exposes no shop or upgrade controls.
        btn_daily = discord.ui.Button(label="🎁 Daily Crate", style=discord.ButtonStyle.success, row=2)
        async def daily_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            view = DailyCrateView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            await interaction.response.edit_message(content=None, embed=view.build_embed(p), view=view)
        btn_daily.callback = daily_cb
        self.add_item(btn_daily)

        # ROW 2: Refresh
        btn_refresh = discord.ui.Button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=2)
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
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float | None = None, run_id: str | None = None):
        # Combat must not expire after 180 seconds. Deep runs can last much longer,
        # and the old View timeout made the Attack/Reload/Flee controls appear dead.
        super().__init__(user_id, store, display_name, timeout)
        current_player = self.store.get(user_id)
        self.run_id = run_id if run_id is not None else current_player.run_id
        # Void-only controls stay out of ordinary-zone combat instead of
        # cluttering the UI with buttons that cannot be used there.
        player = self.store.get(user_id)
        if player.zone_name != "The Void":
            for item in list(self.children):
                if getattr(item, "label", "") in {
                    "💥 Void Bazooka", "◈ Void Perks"
                }:
                    self.remove_item(item)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        player = self.store.get(self.user_id)
        if player.run_id != self.run_id:
            await interaction.response.send_message(
                "⚠️ This combat panel is from an older run. Open **Continue Run** from the main menu to use the current run.",
                ephemeral=True,
            )
            return False
        if not player.run_active:
            await interaction.response.send_message(
                "ℹ️ This run has ended. Return to the main menu to start another run.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="🔫 Attack", style=discord.ButtonStyle.danger, row=0)
    async def attack(self, interaction: discord.Interaction, _b):
        # ACK immediately. Then serialise the state mutation AND the Discord
        # message update so rapid interactions cannot overwrite the UI out of order.
        # PostgreSQL I/O stays outside the combat lock.
        await interaction.response.defer()
        lock = self.store.action_lock(self.user_id)
        async with lock:
            player = self.store.get(self.user_id)
            msgs = take_action(player, "attack")
            if not player.run_active:
                embed = make_embed(title="☠️ Run Ended", description="\n".join(msgs), color=discord.Color.red())
                embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
                embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
                embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
                set_embed_footer(embed, text=f"HP restored to {player.max_health}/{player.max_health} • Press any button to continue")
                next_view = RunEndedView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), end_embed=embed)
            else:
                embed = combat_embed(player, msgs)
                # Keep this View alive for the entire run instead of letting its
                # 180-second timeout kill the controls.
                next_view = self
            await interaction.edit_original_response(content=None, embed=embed, view=next_view)
        await self.store.save_one_async(str(self.user_id))

    @discord.ui.button(label="💥 Void Bazooka", style=discord.ButtonStyle.secondary, row=1)
    async def void_bazooka(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        lock = self.store.action_lock(self.user_id)
        async with lock:
            player=self.store.get(self.user_id)
            msgs=take_action(player, "void_bazooka")
            if not player.run_active:
                embed=make_embed(title="☠️ Run Ended", description="\n".join(msgs), color=discord.Color.red())
                embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
                embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
                embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
                set_embed_footer(embed, text=f"HP restored to {player.max_health}/{player.max_health} • Press any button to continue")
                next_view = RunEndedView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), end_embed=embed)
            else:
                embed=combat_embed(player,msgs)
                next_view = CombatView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))
            await interaction.edit_original_response(content=None, embed=embed, view=next_view)
        await self.store.save_one_async(str(self.user_id))

    @discord.ui.button(label="◈ Void Perks", style=discord.ButtonStyle.secondary, row=1)
    async def void_perks(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        view = VoidPerkView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
        await interaction.response.edit_message(content=None, embed=view.get_embed(player), view=view)

    @discord.ui.button(label="🔄 Reload", style=discord.ButtonStyle.primary, row=0)
    async def reload(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        lock = self.store.action_lock(self.user_id)
        async with lock:
            player = self.store.get(self.user_id)
            msgs = take_action(player, "reload")
            if not player.run_active:
                embed = make_embed(title="☠️ Run Ended", description="\n".join(msgs), color=discord.Color.red())
                embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
                embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
                embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
                set_embed_footer(embed, text=f"HP restored to {player.max_health}/{player.max_health} • Press any button to continue")
                next_view = RunEndedView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), end_embed=embed)
            else:
                embed = combat_embed(player, msgs)
                next_view = CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            # Keep the Discord message update inside the same per-player lock as the
            # state mutation. Otherwise rapid clicks can finish out of order and an
            # older interaction can overwrite the message with stale combat state.
            await interaction.edit_original_response(content=None, embed=embed, view=next_view)
        await self.store.save_one_async(str(self.user_id))

    @discord.ui.button(label="💊 Heal", style=discord.ButtonStyle.success, row=0)
    async def heal(self, interaction: discord.Interaction, _b):
        player = self.store.get(self.user_id)
        embed = combat_embed(player, ["Choose heal item"])
        await interaction.response.edit_message(content=None, embed=embed, view=HealView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="🏃 Flee", style=discord.ButtonStyle.secondary, row=0)
    async def flee(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        lock = self.store.action_lock(self.user_id)
        async with lock:
            player = self.store.get(self.user_id)
            msgs = take_action(player, "flee")
            if not player.run_active:
                embed = make_embed(title="🏃 Escaped!", description="\n".join(msgs), color=discord.Color.blue())
                embed.add_field(name="🌊 Waves", value=f"{player.wave - 1 if player.run_zombies_killed>0 else 0} survived\nReached Wave {player.wave}", inline=True)
                embed.add_field(name="🧟 Kills", value=f"{player.run_zombies_killed} zombies", inline=True)
                embed.add_field(name="💰 Rewards", value=f"+${player.run_money_earned}\n+{player.run_xp_earned} XP", inline=True)
                set_embed_footer(embed, text=f"HP restored to {player.max_health}/{player.max_health} • Press any button to continue")
                next_view = RunEndedView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), end_embed=embed)
            else:
                embed = combat_embed(player, msgs)
                next_view = CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"))
            # Keep the Discord message update inside the same per-player lock so
            # a rapid second click cannot overwrite the message with stale state.
            await interaction.edit_original_response(content=None, embed=embed, view=next_view)
        await self.store.save_one_async(str(self.user_id))

    @discord.ui.button(label="🏠 Main Menu", style=discord.ButtonStyle.secondary, row=3)
    async def main_menu(self, interaction: discord.Interaction, _b):
        # Always provide a safe exit from combat. This does not abandon the run;
        # it simply returns to the menu so the player can resume it later.
        await interaction.response.defer()
        lock = self.store.action_lock(self.user_id)
        async with lock:
            player = self.store.get(self.user_id)
            if player.run_active and player.enemy is None:
                msgs = recover_stuck_run(player)
            else:
                msgs = []
            name = getattr(self, "display_name", "Survivor")
            content = status(player, display_name=name)
            if msgs:
                content += "\n\n" + "\n".join(msgs)
        if msgs:
            await self.store.save_one_async(str(self.user_id))
        await interaction.edit_original_response(content=content, embed=None, view=ZombieMenuView(self.user_id, self.store, display_name=name))

    @discord.ui.button(label="🛠️ Recover Run", style=discord.ButtonStyle.secondary, row=3)
    async def recover_run(self, interaction: discord.Interaction, _b):
        await interaction.response.defer()
        lock = self.store.action_lock(self.user_id)
        async with lock:
            player = self.store.get(self.user_id)
            msgs = recover_stuck_run(player)
            if not msgs:
                msgs = ["✅ Your run is already healthy — an enemy is active."]
            embed = combat_embed(player, msgs)
        await self.store.save_one_async(str(self.user_id))
        await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))




class VoidPerkView(PlayerView):
    """Dedicated Void perk panel so combat stays clean and readable."""
    PERKS = (
        ("Void Infusion", "⚡", "Boosts your next eligible attack."),
        ("Void Shield", "🛡️", "Reduces the next actual incoming hit."),
        ("Void Execution", "☠️", "Arms below 50% enemy HP for a heavy finishing bonus."),
    )

    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float | None = None):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.clear_items()

        for perk_name, icon, _desc in self.PERKS:
            lvl = void_perk_level(player, perk_name)
            if lvl <= 0:
                label = f"{icon} {perk_name.split()[-1]} 🔒"
                style = discord.ButtonStyle.secondary
            elif getattr(player, {"Void Infusion":"void_infusion_active", "Void Shield":"void_shield_active", "Void Execution":"void_execution_active"}[perk_name], False):
                label = f"{icon} {perk_name.split()[-1]} ARMED"
                style = discord.ButtonStyle.success
            else:
                label = f"{icon} {perk_name.split()[-1]} L{lvl}"
                style = discord.ButtonStyle.primary

            btn = discord.ui.Button(label=label, style=style, row=0, disabled=(lvl <= 0))
            async def perk_cb(interaction: discord.Interaction, pn=perk_name):
                await interaction.response.defer()
                lock = self.store.action_lock(self.user_id)
                async with lock:
                    p = self.store.get(self.user_id)
                    msgs = take_action(p, pn.lower().replace(" ", "_"))
                    embed = combat_embed(p, msgs)
                    await interaction.edit_original_response(
                        content=None,
                        embed=embed,
                        view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")),
                    )
                await self.store.save_one_async(str(self.user_id))
            btn.callback = perk_cb
            self.add_item(btn)

        back = discord.ui.Button(label="⬅️ Back to Combat", style=discord.ButtonStyle.secondary, row=1)
        async def back_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
            await interaction.response.edit_message(
                content=None,
                embed=combat_embed(p, ["◈ Void Perks panel closed."]),
                view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")),
            )
        back.callback = back_cb
        self.add_item(back)

    def get_embed(self, player, extra_msgs=None):
        embed = make_embed(
            title="◈ THE VOID — PERKS",
            description=(
                f"**Essence:** ◈{player.void_essence:,}\n"
                "Choose a perk to activate it. Unlocking and upgrading happens in the Void shop."
            ),
            color=discord.Color.dark_purple(),
        )
        for perk_name, icon, desc in self.PERKS:
            lvl = void_perk_level(player, perk_name)
            spec = VOID_PERKS[perk_name]
            bonus = int(void_perk_bonus(player, perk_name) * 100)
            cost = spec["activation_cost"]
            cooldown_field = {"Void Infusion":"void_infusion_cooldown", "Void Shield":"void_shield_cooldown", "Void Execution":"void_execution_cooldown"}[perk_name]
            active_field = {"Void Infusion":"void_infusion_active", "Void Shield":"void_shield_active", "Void Execution":"void_execution_active"}[perk_name]
            cooldown = getattr(player, cooldown_field, 0)
            active = getattr(player, active_field, False)

            if lvl <= 0:
                status = "🔒 Locked — unlock in Void shop"
            elif active:
                status = f"🟢 ARMED • +{bonus}% effect"
            elif cooldown > 0:
                status = f"⏳ {cooldown} zombie(s) cooldown"
            else:
                status = f"🟣 Ready • ◈{cost} activation"

            effect = (
                f"+{bonus}% next attack" if perk_name == "Void Infusion" else
                f"-{bonus}% next incoming hit" if perk_name == "Void Shield" else
                f"+{bonus}% damage when enemy is ≤50% HP"
            )
            embed.add_field(
                name=f"{icon} {perk_name} — L{lvl}/10",
                value=f"{desc}\n**Effect:** {effect}\n**Status:** {status}",
                inline=False,
            )

        if extra_msgs:
            embed.add_field(name="⚔️ Result", value="\n".join(extra_msgs)[:1024], inline=False)
        set_embed_footer(embed, text="Activation costs Essence • Cooldowns reset after enough kills")
        return embed


class HealView(PlayerView):
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float | None = None):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.clear_items()
        pk_left = player.max_painkillers_per_run - player.painkillers_used_this_run
        pk_label = f"💊 Painkillers ({player.painkillers}x - {pk_left} left this run)"
        pk_btn = discord.ui.Button(label=pk_label[:80], style=discord.ButtonStyle.success, row=0)
        async def pk_cb(interaction):
            try:
                await interaction.response.defer()
            except:
                pass
            lock = self.store.action_lock(self.user_id)
            async with lock:
                p=self.store.get(self.user_id)
                msgs=take_action(p,"heal","painkillers")
                embed = combat_embed(p, msgs)
                await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            try:
                await self.store.save_one_async(str(self.user_id))
            except Exception as e:
                print(f"Heal save error: {e}")
            return
        pk_btn.callback = pk_cb
        self.add_item(pk_btn)

        fr_left = player.max_full_restores_per_run - player.full_restores_used_this_run
        fr_label = f"✨ Full restore ({player.full_restores}x - {fr_left} left)"
        fr_btn = discord.ui.Button(label=fr_label[:80], style=discord.ButtonStyle.success, row=0)
        async def fr_cb(interaction):
            try:
                await interaction.response.defer()
            except:
                pass
            lock = self.store.action_lock(self.user_id)
            async with lock:
                p=self.store.get(self.user_id)
                msgs=take_action(p,"heal","full_restore")
                embed = combat_embed(p, msgs)
                await interaction.edit_original_response(content=None, embed=embed, view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
            try:
                await self.store.save_one_async(str(self.user_id))
            except Exception as e:
                print(f"Heal save error: {e}")
            return
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
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float | None = None):
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
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_weapon: str = None, timeout: float | None = None):
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
                await interaction.response.defer()
                p=self.store.get(self.user_id)
                if p.run_active:
                    await interaction.edit_original_response(content=None, embed=combat_embed(p, ["🚫 **Shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                    return
                if wn not in p.owned_weapons:
                    msgs = buy_item(p, wn)
                    schedule_shop_save(self.store, self.user_id)
                content = self.get_shop_text(p, selected_override=wn, extra_msgs=None)
                await interaction.edit_original_response(content=content, view=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_weapon=wn))
            btn.callback = cb
            self.add_item(btn)

        # Buy button for selected
        wdata = WEAPONS.get(self.selected_weapon, {"price": 0})
        buy_label = f"Buy {self.selected_weapon} ${wdata['price']}"
        if self.selected_weapon in player.owned_weapons:
            buy_label = f"Equip {self.selected_weapon}"
        btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.primary, row=2)
        async def buy_cb(interaction):
            await interaction.response.defer()
            p=self.store.get(self.user_id)
            if p.run_active:
                await interaction.edit_original_response(content=None, embed=combat_embed(p, ["🚫 **Shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                return
            msgs = buy_item(p, self.selected_weapon)
            schedule_shop_save(self.store, self.user_id)
            content = self.get_shop_text(p, selected_override=self.selected_weapon, extra_msgs=msgs)
            await interaction.edit_original_response(content=content, view=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_weapon=self.selected_weapon))
        btn_buy.callback = buy_cb
        self.add_item(btn_buy)

        upgrade_btn = discord.ui.Button(label=f"🔧 Upgrade {self.selected_weapon}", style=discord.ButtonStyle.success, row=2, disabled=self.selected_weapon not in player.owned_weapons)
        async def weapon_upgrade_cb(interaction):
            p=self.store.get(self.user_id)
            if p.run_active:
                await interaction.response.edit_message(content=None,embed=combat_embed(p,["🚫 **Shopping is locked during a run.** Flee or finish the run first."]),view=CombatView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))); return
            view=WeaponUpgradeView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"),weapon_name=self.selected_weapon)
            await interaction.response.edit_message(content=view.get_shop_text(p),embed=None,view=view)
        upgrade_btn.callback=weapon_upgrade_cb; self.add_item(upgrade_btn)

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
        if sel in player.owned_weapons:
            lv=player.weapon_upgrades.get(sel,{"damage":0,"mag":0,"crit":0})
            lines.append(f"🔧 Upgrades: ⚔️ Lv {lv['damage']} • 📦 Lv {lv['mag']} • 🎯 Lv {lv['crit']} • 🔫 Double-Tap Lv {lv.get('double_tap',0)}")
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
                lv=player.weapon_upgrades.get(wname,{"damage":0,"mag":0,"crit":0}); shots=int(w.get("shots",1))
                dmg=w.get("damage",0)+lv.get("damage",0)*WEAPON_DAMAGE_PER_UPGRADE.get(wname,3); mag=w.get("mag",0)+lv.get("mag",0)*shots
                crit=0 if lv.get("crit",0)<=0 else min(0.02+(lv.get("crit",0)-1)*0.005,0.40)
                status_str = f"Owned - Dmg {dmg} | Mag {mag} | Crit {crit*100:.1f}% | Double-Tap {lv.get('double_tap',0)}%"
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


class WeaponUpgradeView(PlayerView):
    """Individual weapon upgrades inside the Weapons shop."""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", weapon_name: str | None = None, timeout: float | None = None):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.weapon_name = weapon_name if weapon_name in WEAPONS else player.weapon_name
        self.clear_items()
        max_levels = {
            "damage": WEAPON_DAMAGE_MAX_LEVEL,
            "mag": WEAPON_MAG_MAX_LEVEL,
            "crit": WEAPON_CRIT_MAX_LEVEL,
            "double_tap": DOUBLE_TAP_MAX_LEVEL,
        }
        max_labels = {"damage": "Lv 200", "mag": "Lv 200", "crit": "40%", "double_tap": "10%"}
        for row, (stat, label, icon) in enumerate([("damage","Damage","⚔️"),("mag","Magazine","📦"),("crit","Crit","🎯"),("double_tap","Double-Tap","🔫")]):
            lvl = player.weapon_upgrade_level(stat, self.weapon_name)
            is_max = lvl >= max_levels[stat]
            cost = get_weapon_upgrade_cost(player, self.weapon_name, stat)
            btn_label = f"{icon} {label} MAX {max_labels[stat]}" if is_max else f"{icon} {label} L{lvl} • ${cost:,}"
            btn = discord.ui.Button(label=btn_label[:80], style=discord.ButtonStyle.secondary if is_max else discord.ButtonStyle.success, disabled=is_max, row=row)
            async def cb(interaction, st=stat):
                await interaction.response.defer()
                if self.user_id in _purchase_locks:
                    await interaction.edit_original_response(content="⏳ Purchase already processing. Try again in a moment.", view=self); return
                _purchase_locks.add(self.user_id)
                try:
                    p=self.store.get(self.user_id); msgs=upgrade_weapon(p,self.weapon_name,st); schedule_shop_save(self.store, self.user_id)
                    view=WeaponUpgradeView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"),weapon_name=self.weapon_name)
                    await interaction.edit_original_response(content=view.get_shop_text(p,msgs),view=view)
                finally: _purchase_locks.discard(self.user_id)
            btn.callback=cb; self.add_item(btn)
        back=discord.ui.Button(label="⬅️ Back to Weapons",style=discord.ButtonStyle.secondary,row=3)
        async def back_cb(interaction):
            p=self.store.get(self.user_id); view=WeaponShopView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"),selected_weapon=self.weapon_name)
            await interaction.response.edit_message(content=view.get_shop_text(p),embed=None,view=view)
        back.callback=back_cb; self.add_item(back)
        main_btn=discord.ui.Button(label="🏠 Main menu",style=discord.ButtonStyle.secondary,row=3)
        async def main_cb(interaction):
            p=self.store.get(self.user_id); name=getattr(self,"display_name","Survivor")
            await interaction.response.edit_message(content=status(p,display_name=name),embed=None,view=ZombieMenuView(self.user_id,self.store,display_name=name))
        main_btn.callback=main_cb; self.add_item(main_btn)
    def get_shop_text(self, player, messages=None):
        w=WEAPONS[self.weapon_name]; lv=player.weapon_upgrades.get(self.weapon_name,{"damage":0,"mag":0,"crit":0}); shots=int(w.get("shots",1))
        crit=0 if lv["crit"]<=0 else min(0.02+(lv["crit"]-1)*0.005,0.40)
        lines=[]
        if messages: lines.extend(messages); lines.append("")
        dt_level = lv.get("double_tap", 0)
        dt_chance = min(dt_level, 10)
        lines += [f"🔧 **{self.weapon_name} Upgrades**","",f"💰 Cash: **${player.money:,}**",f"⚔️ Damage: **{w['damage']+lv['damage']*WEAPON_DAMAGE_PER_UPGRADE.get(self.weapon_name,3)}**",f"📦 Magazine: **{w['mag']+lv['mag']*shots}** ({shots} shot(s) per attack)",f"🎯 Crit: **{crit*100:.1f}%**",f"🔫 Double-Tap: **{dt_chance}%**", "","Each upgrade uses cash and affects **only this weapon**.","Double-Tap gives a chance to immediately repeat the attack for free; the bonus attack cannot chain.",""]
        for stat,label,icon in [("damage","Damage","⚔️"),("mag","Magazine","📦"),("crit","Crit","🎯"),("double_tap","Double-Tap","🔫")]:
            cost=get_weapon_upgrade_cost(player,self.weapon_name,stat)
            if stat=="damage": detail=f"+{WEAPON_DAMAGE_PER_UPGRADE.get(self.weapon_name, 3)} damage"
            elif stat=="mag": detail=f"+{shots} capacity"
            elif stat=="crit": detail="+2% first, +0.5% after"
            else: detail=f"+1% proc chance (free second attack)"
            max_levels = {"damage": WEAPON_DAMAGE_MAX_LEVEL, "mag": WEAPON_MAG_MAX_LEVEL, "crit": WEAPON_CRIT_MAX_LEVEL, "double_tap": DOUBLE_TAP_MAX_LEVEL}
            max_values = {"damage": "Lv 200", "mag": "Lv 200", "crit": "40%", "double_tap": "10%"}
            if lv[stat] >= max_levels[stat]:
                lines.append(f"{icon} **{label}** — **MAX {max_values[stat]}**")
            else:
                lines.append(f"{icon} **{label}** — Lv {lv[stat]} → {lv[stat]+1} | {detail} | **${cost:,}**")
        return "\n".join(lines)


class AmmoShopView(PlayerView):
    """Fisher Bait Shop clone - list + select + bulk buy +1 +10 +100 +1000"""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_ammo: str = None, timeout: float | None = None):
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
                await interaction.response.defer()
                p=self.store.get(self.user_id)
                if p.run_active:
                    await interaction.edit_original_response(content=None, embed=combat_embed(p, ["🚫 **Ammo shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                    return
                msgs = []
                success = True
                if an not in p.owned_ammo:
                    msgs = equip_ammo(p, an)
                    # Check if equip failed (message starts with ❌ or Need or unlocks)
                    if msgs and any(x.startswith('❌') or 'Need $' in x or 'unlocks at level' in x.lower() for x in msgs):
                        success = False
                    schedule_shop_save(self.store, self.user_id)
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
                    schedule_shop_save(self.store, self.user_id)
                
                if success:
                    self.selected_ammo = an
                    content = self.get_shop_text(p, extra_msgs=msgs)
                    await interaction.edit_original_response(content=content, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_ammo=an))
                else:
                    # Equip failed, keep old selection but show error
                    content = self.get_shop_text(p, extra_msgs=msgs)
                    await interaction.edit_original_response(content=content, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_ammo=self.selected_ammo))
            btn.callback = cb
            self.add_item(btn)
        
        box_price = AMMO[self.selected_ammo]["box_price"]
        for qty, row in [(1,2), (10,2), (100,3), (1000,3)]:
            total = box_price * qty
            label = f"+{qty} (${total:,})"
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary, row=row)
            async def bulk_cb(interaction, q=qty, ammo=self.selected_ammo):
                await interaction.response.defer()
                if self.user_id in _purchase_locks:
                    await interaction.edit_original_response(content="⏳ Purchase already processing. Try again in a moment.", view=self)
                    return
                _purchase_locks.add(self.user_id)
                try:
                    p=self.store.get(self.user_id)
                    if p.run_active:
                        await interaction.edit_original_response(content=None, embed=combat_embed(p, ["🚫 **Ammo shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                        return
                    msgs = buy_ammo_boxes(p, ammo, q)
                    schedule_shop_save(self.store, self.user_id)
                    content = self.get_shop_text(p, selected_override=ammo, extra_msgs=msgs)
                    await interaction.edit_original_response(content=content, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_ammo=ammo))
                finally:
                    _purchase_locks.discard(self.user_id)
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
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_med: str = "painkillers", timeout: float | None = None):
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
                p=self.store.get(self.user_id)
                if p.run_active:
                    await interaction.response.edit_message(content=None, embed=combat_embed(p, ["🚫 **Med shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                    return
                self.selected_med = m
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
                await interaction.response.defer()
                if self.user_id in _purchase_locks:
                    await interaction.edit_original_response(content="⏳ Purchase already processing. Try again in a moment.", view=self)
                    return
                _purchase_locks.add(self.user_id)
                try:
                    p = self.store.get(self.user_id)
                    if p.run_active:
                        await interaction.edit_original_response(content=None, embed=combat_embed(p, ["🚫 **Med shopping is locked during a run.** Flee or finish the run first."]), view=CombatView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
                        return
                    total_cost = (15 if med == "painkillers" else 80) * q

                    if p.money < total_cost:
                        msgs = [f"❌ Need ${total_cost} for {q}x {med}, you have ${p.money}"]
                    else:
                        p.money -= total_cost
                        if med == "painkillers":
                            p.painkillers += 2 * q
                            bought = 2 * q
                            msgs = [f"💊 Bought {q}x Painkillers +{bought} | Now {p.painkillers}x | ${p.money} left"]
                        else:
                            p.full_restores += q
                            bought = q
                            msgs = [f"✨ Bought {q}x Full Restore +{bought} | Now {p.full_restores}x | ${p.money} left"]
                        schedule_shop_save(self.store, self.user_id)
                    content = self.get_shop_text(p, selected_override=med, extra_msgs=msgs)
                    await interaction.edit_original_response(content=content, view=MedsShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_med=med))
                finally:
                    _purchase_locks.discard(self.user_id)
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
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_up: str = "health", timeout: float | None = None):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.selected_up = selected_up
        self.clear_items()

        upgrades = [
            ("health", "❤️ Health", "+20 HP"),
            ("armor", "🛡️ Armor", "-2 Dmg"),
            ("scavenger", "💰 Loot", "+10%"),
            ("combat_medic", "💉 Combat Medic", "More meds/run"),
        ]
        for i, (uid, uname, plus) in enumerate(upgrades):
            is_sel = uid == self.selected_up
            cost = get_combat_medic_cost(player) if uid == "combat_medic" else get_upgrade_cost(player, uid)
            lvl = player.combat_medic_level if uid == "combat_medic" else (getattr(player, f"{uid}_upgrades", 0) if uid != "scavenger" else player.scavenger_upgrades)
            label = f"{uname.split()[1]} ({lvl}) {'✅' if is_sel else ''}"
            style = discord.ButtonStyle.success if is_sel else discord.ButtonStyle.primary
            btn = discord.ui.Button(label=label[:80], style=style, row=0 if i < 3 else 1)
            async def cb(interaction, u=uid):
                self.selected_up = u
                p=self.store.get(self.user_id)
                content = self.get_shop_text(p, selected_override=u)
                # Component callbacks must acknowledge the interaction before editing.
                # Using edit_original_response() without defer/response caused the
                # Armour/Loot selector buttons to show "didn't respond in time".
                await interaction.response.edit_message(
                    content=content,
                    view=UpgradeView(
                        self.user_id,
                        self.store,
                        display_name=getattr(self, "display_name", "Survivor"),
                        selected_up=u,
                    ),
                )
            btn.callback = cb
            self.add_item(btn)

        # Single buy button for selected upgrade - no bulk as requested
        cost = get_combat_medic_cost(player) if self.selected_up == "combat_medic" else get_upgrade_cost(player, self.selected_up)
        selected_max = (
            (self.selected_up == "combat_medic" and player.combat_medic_level >= COMBAT_MEDIC_MAX_LEVEL)
        )
        if selected_max:
            max_label = "Combat Medic MAXED"
            btn_buy = discord.ui.Button(label=f"🔥 {max_label}", style=discord.ButtonStyle.secondary, disabled=True, row=2)
        else:
            buy_label = f"Buy {self.selected_up.replace('_', ' ').title()} ${cost:,}"
            btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.success, row=2)
        async def buy_cb(interaction):
            # FIX #1: Prevent double-click race - locks per user
            if self.user_id in _purchase_locks:
                try:
                    await interaction.response.defer()
                except:
                    pass
                return
            await interaction.response.defer()
            _purchase_locks.add(self.user_id)
            try:
                p=self.store.get(self.user_id)
                msgs = upgrade_combat_medic(p) if self.selected_up == "combat_medic" else upgrade(p, self.selected_up)
                schedule_shop_save(self.store, self.user_id)
                content = self.get_shop_text(p, selected_override=self.selected_up, extra_msgs=msgs)
                await interaction.edit_original_response(content=content, view=UpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_up=self.selected_up))
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
        lines.append("Universal survivor upgrades only. Weapon Damage, Magazine and Crit are now upgraded inside each individual weapon.")
        lines.append("")
        lines.append(f"Your balance: **${player.money:,}** | Stars: **{player.stars}**")
        lines.append(f"Selected: **{sel.replace('_', ' ').title()}**")
        lines.append("---")
        if sel == "combat_medic":
            next_cost = get_combat_medic_cost(player)
            lvl = player.combat_medic_level
            lines.append(f"💉 **Combat Medic ({lvl})**")
            lines.append(f"**{player.max_painkillers_per_run} 💊 Painkillers + {player.max_full_restores_per_run} ✨ Full Restore per run**")
            if lvl < COMBAT_MEDIC_MAX_LEVEL:
                lines.append(f"Cost **${next_cost:,}** — Lvl {lvl}")
            else:
                lines.append("🔥 **MAXED — Lvl 6**")
            lines.append("")
        for uid, uname, plus in [
            ("health", "❤️ Health", "+20 HP"),
            ("armor", "🛡️ Armor", "-2 Dmg taken"),
            ("scavenger", "💰 Loot", "+10% Money"),
            ("combat_medic", "💉 Combat Medic", "More meds/run"),
        ]:
            cost = get_combat_medic_cost(player) if uid == "combat_medic" else get_upgrade_cost(player, uid)
            lvl = player.combat_medic_level if uid == "combat_medic" else (getattr(player, f"{uid}_upgrades", 0) if uid != "scavenger" else player.scavenger_upgrades)
            sel_mark = " ← SELECTED" if uid == sel else ""
            lines.append(f"{uname} ({lvl}){sel_mark}")
            if uid == "combat_medic":
                lines.append(
                    f"{player.max_painkillers_per_run} 💊 Painkillers + {player.max_full_restores_per_run} ✨ Full Restore per run - Cost ${cost:,} - Lvl {lvl}"
                    if lvl < COMBAT_MEDIC_MAX_LEVEL else
                    f"{player.max_painkillers_per_run} 💊 Painkillers + {player.max_full_restores_per_run} ✨ Full Restore per run - MAXED"
                )
            else:
                lines.append(f"{plus} per level - Cost ${cost:,} - Lvl {lvl}")
            lines.append("")
        if sel == "combat_medic" and player.combat_medic_level >= COMBAT_MEDIC_MAX_LEVEL:
            lines.append("Next: **Combat Medic MAXED — Lvl 6**")
        else:
            if sel == "combat_medic":
                next_lvl = player.combat_medic_level + 1
                next_cost = get_combat_medic_cost(player)
            else:
                next_lvl = (getattr(player, f"{sel}_upgrades", 0) + 1) if sel != "scavenger" else player.scavenger_upgrades + 1
                next_cost = get_upgrade_cost(player, sel)
            lines.append(f"Next: {sel.replace('_', ' ').title()} Lvl {next_lvl} for ${next_cost:,}")
        return "\n".join(lines)


class StarUpgradeView(PlayerView):
    """Star upgrade shop with persistent component controls and per-player purchase locking."""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", selected_star: str = "dodge", timeout: float | None = None):
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
                p = self.store.get(self.user_id)
                content = self.get_shop_text(p, selected_override=s)
                view = StarUpgradeView(
                    self.user_id,
                    self.store,
                    display_name=getattr(self, "display_name", "Survivor"),
                    selected_star=s,
                )
                # A component callback must acknowledge the interaction before
                # editing the message.  The old code called edit_original_response
                # without responding/defering, which made the selector buttons fail.
                await interaction.response.edit_message(content=content, view=view)
            btn.callback = cb
            self.add_item(btn)

        # Single buy button for selected star - no bulk as requested
        cost = get_star_upgrade_cost(player, self.selected_star)
        star_level = {
            "dodge": player.star_dodge_upgrades,
            "magical": player.star_magical_upgrades,
            "medic": player.star_medic_upgrades,
            "pet": player.star_pet_upgrades,
            "xp": player.star_xp_upgrades,
        }[self.selected_star]
        star_is_max = star_level >= STAR_MAX_LEVELS[self.selected_star]
        buy_label = f"⭐ {self.selected_star.capitalize()} MAXED" if star_is_max else f"Buy {self.selected_star.capitalize()} ⭐{cost}"
        btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.secondary if star_is_max else discord.ButtonStyle.success, disabled=star_is_max, row=2)
        async def buy_cb(interaction):
            # FIX #1: Prevent double-click race for star upgrades
            if self.user_id in _purchase_locks:
                try:
                    await interaction.response.defer()
                except:
                    pass
                return
            await interaction.response.defer()
            _purchase_locks.add(self.user_id)
            try:
                p=self.store.get(self.user_id)
                msgs = upgrade_star(p, self.selected_star)
                schedule_shop_save(self.store, self.user_id)
                content = self.get_shop_text(p, selected_override=self.selected_star, extra_msgs=msgs)
                await interaction.edit_original_response(content=content, view=StarUpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_star=self.selected_star))
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
        selected_level = {"dodge": player.star_dodge_upgrades, "magical": player.star_magical_upgrades, "medic": player.star_medic_upgrades, "pet": player.star_pet_upgrades, "xp": player.star_xp_upgrades}[sel]
        if selected_level >= STAR_MAX_LEVELS[sel]:
            lines.append(f"Selected: {emoji_map.get(sel,'⭐')} **{sel.capitalize()}** → **MAXED**")
        else:
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
            if lvl >= STAR_MAX_LEVELS[sid]:
                lines.append(f"Cap {cap} | {per} | **MAXED**")
            else:
                lines.append(f"Cap {cap} | {per} | Cost ⭐{cost} | Next Lvl {lvl+1}")
            lines.append("")
        if selected_level >= STAR_MAX_LEVELS[sel]:
            lines.append(f"Selected: **{sel.capitalize()}** → **MAXED — no further upgrades**")
        else:
            lines.append(f"Selected: **{sel.capitalize()}** → Buy for ⭐{get_star_upgrade_cost(player, sel)}")
        return "\n".join(lines)




class VoidUpgradeView(PlayerView):
    """Clean, compact Void progression page."""
    def __init__(self, user_id: int, store, display_name: str = "Survivor", timeout: float | None = None):
        super().__init__(user_id, store, display_name, timeout)
        player = self.store.get(user_id)
        self.clear_items()

        owned = "Void Bazooka" in player.void_weapons_owned
        lvl = max(0, min(VOID_UPGRADE_MAX, player.void_weapon_level))
        if lvl >= VOID_UPGRADE_MAX:
            baz_label = "💥 Bazooka MAX"
        else:
            baz_label = "💥 Void Bazooka" + (" ✅" if owned else " 🔒")
        btn = discord.ui.Button(label=baz_label, style=discord.ButtonStyle.secondary if lvl >= VOID_UPGRADE_MAX else (discord.ButtonStyle.success if owned else discord.ButtonStyle.primary), disabled=(lvl >= VOID_UPGRADE_MAX), row=0)
        async def bazooka_select(interaction):
            await interaction.response.defer()
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
                    schedule_shop_save(self.store, self.user_id)
            view=VoidUpgradeView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))
            await interaction.edit_original_response(content=None, embed=view.get_shop_embed(p,msgs), view=view)
        btn.callback=bazooka_select; self.add_item(btn)

        cost=get_void_upgrade_cost(player)
        up_label = "⬆️ Bazooka MAX" if lvl >= VOID_UPGRADE_MAX else f"⬆️ Upgrade Bazooka • ◈{cost:,}"
        btn_up=discord.ui.Button(label=up_label, style=discord.ButtonStyle.success, row=1, disabled=(lvl>=VOID_UPGRADE_MAX))
        async def upgrade_cb(interaction):
            if self.user_id in _purchase_locks:
                await interaction.response.defer(); return
            await interaction.response.defer()
            _purchase_locks.add(self.user_id)
            try:
                p=self.store.get(self.user_id); msgs=upgrade_void_weapon(p); schedule_shop_save(self.store, self.user_id)
                view=VoidUpgradeView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))
                await interaction.edit_original_response(content=None, embed=view.get_shop_embed(p,msgs), view=view)
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
            b=discord.ui.Button(label=label[:80], style=discord.ButtonStyle.secondary if plvl>=10 else (discord.ButtonStyle.success if plvl else discord.ButtonStyle.primary), disabled=(plvl>=10), row=2)
            async def perk_cb(interaction,pn=perk_name):
                if self.user_id in _purchase_locks:
                    await interaction.response.defer(); return
                await interaction.response.defer()
                _purchase_locks.add(self.user_id)
                try:
                    p=self.store.get(self.user_id); msgs=upgrade_void_perk(p,pn); schedule_shop_save(self.store, self.user_id)
                    view=VoidUpgradeView(self.user_id,self.store,display_name=getattr(self,"display_name","Survivor"))
                    await interaction.edit_original_response(content=None, embed=view.get_shop_embed(p,msgs), view=view)
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
        embed=make_embed(title="🌑 The Void",description=f"◈ **Essence:** {player.void_essence:,}\n💰 **Balance:** ${player.money:,}\n🎚️ **Level:** {player.level}",color=discord.Color.dark_purple())
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
        set_embed_footer(embed, text="Perks work in The Void and can modify the Bazooka.")
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
    return costs[lvl] if lvl < VOID_UPGRADE_MAX else 0


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
    def __init__(self, user_id, store, display_name: str = "Survivor", timeout: float | None = None):
        super().__init__(user_id, store, display_name)
        for i, zone_name in enumerate(ZONES):
            btn = discord.ui.Button(label=zone_name, style=discord.ButtonStyle.primary, row=i//2)
            async def cb(interaction, zn=zone_name):
                await interaction.response.defer()
                user_id = self.user_id
                lock = self.store.action_lock(user_id)
                async with lock:
                    p = self.store.get(user_id)
                    msgs = change_zone(p, zn)
                await self.store.save_one_async(str(user_id))
                # Keep the zone picker focused on the zone-change result.  The old
                # flow appended the full player status/inventory here, which made a
                # simple zone tap suddenly replace the picker with the inventory screen.
                await interaction.edit_original_response(content="\n".join(msgs), view=ZoneView(user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))
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
        user_id = interaction.user.id
        lock = game_store.action_lock(user_id)
        async with lock:
            player = game_store.get(user_id)
            name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
            player.leaderboard_name = name[:32]
            if interaction.guild and str(interaction.guild.id) not in player.leaderboard_guilds:
                player.leaderboard_guilds.append(str(interaction.guild.id))
            recovery_msgs = []
            if player.run_active and player.enemy is None:
                recovery_msgs = recover_stuck_run(player)
                print(f"[RECOVERY] /zombie repaired player {user_id}: {recovery_msgs}")
            content = status(player, display_name=name)
            if recovery_msgs:
                content += "\n\n" + "\n".join(recovery_msgs)
            view = ZombieMenuView(user_id, game_store, display_name=name)

        await game_store.save_one_async(str(user_id))
        print(f"[CMD] /zombie by {user_id} name={name} level={player.level}")
        await interaction.followup.send(content=content, view=view)
        print(f"[CMD] /zombie sent OK for {user_id}")
    except Exception as e:
        print(f"[CMD ERROR] /zombie failed: {e}")
        import traceback
        traceback.print_exc()
        try:
            await interaction.followup.send(f"❌ Bot error: {e}\n```{traceback.format_exc()[:1500]}```", ephemeral=True)
        except:
            pass

@bot.tree.command(name="daily", description="Open your free Daily Survivor Crate")
async def daily_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    player = game_store.get(interaction.user.id)
    name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
    view = DailyCrateView(interaction.user.id, game_store, display_name=name)
    await interaction.followup.send(content=None, embed=view.build_embed(player), view=view)

@bot.tree.command(name="leaderboard", description="View Zombie Survival leaderboards")
@app_commands.describe(scope="Global, server, or personal records", zone="Zone to view")
@app_commands.choices(scope=[app_commands.Choice(name="Global",value="global"),app_commands.Choice(name="Server",value="server"),app_commands.Choice(name="My Records",value="personal")])
async def leaderboard_cmd(interaction: discord.Interaction, scope: str = "global", zone: str | None = None):
    await interaction.response.defer()
    user_id = interaction.user.id
    lock = game_store.action_lock(user_id)
    async with lock:
        p=game_store.get(user_id)
        name=getattr(interaction.user,"display_name",None) or getattr(interaction.user,"global_name",None) or interaction.user.name
        p.leaderboard_name=name[:32]
        gid=interaction.guild.id if interaction.guild else None
        if gid is not None and str(gid) not in p.leaderboard_guilds:
            p.leaderboard_guilds.append(str(gid))
        if zone not in ZONES:
            zone=p.zone_name
    await game_store.save_one_async(str(user_id))
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
    user_id = interaction.user.id
    lock = game_store.action_lock(user_id)
    async with lock:
        player = game_store.get(user_id)
        player.leaderboard_name = (getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name)[:32]
        if interaction.guild and str(interaction.guild.id) not in player.leaderboard_guilds:
            player.leaderboard_guilds.append(str(interaction.guild.id))
        if player.run_active:
            recovery_msgs = recover_stuck_run(player) if player.enemy is None else []
            if recovery_msgs:
                result_msgs = recovery_msgs
            else:
                result_msgs = [f"Already in run! Wave {player.wave}"]
            embed = combat_embed(player, result_msgs)
        else:
            result_msgs = start_run(player)
            embed = combat_embed(player, result_msgs)
    # Persist only after the mutation lock is released; save_one_async takes the
    # same action lock while snapshotting and therefore must not be called inside it.
    await game_store.save_one_async(str(user_id))
    await interaction.followup.send(embed=embed, view=CombatView(user_id, game_store))

# --- OWNER / GAME ADMIN COMMANDS ---
# The bot uses its own permission hierarchy instead of Discord server roles:
#   👑 Owner -> 🛠️ Game Admins -> 🧟 Players
# OWNER_ID is intentionally fixed in code. No Discord command can change it.


def is_owner(interaction: discord.Interaction) -> bool:
    return int(interaction.user.id) == OWNER_ID


def has_admin_commands(interaction: discord.Interaction) -> bool:
    """True only for the fixed Owner or a delegated Game Admin.

    Discord server Administrator/Manage Guild permissions are deliberately NOT
    sufficient. This prevents a server administrator from gaining the bot's
    game-admin powers unless the Owner explicitly delegates them.
    """
    if is_owner(interaction):
        return True
    try:
        return bool(is_bot_admin(interaction.user.id))
    except Exception as e:
        print(f"[ADMIN] Failed delegated-admin check for {interaction.user.id}: {e}")
        return False


def admin_denied_message() -> str:
    return "❌ You do not have **Zombie Game Admin** access."


def owner_denied_message() -> str:
    return "❌ Only the **Owner** can manage Zombie Game Admins."


admin_group = app_commands.Group(name="admin", description="[OWNER] Manage Zombie Game Admins")


@admin_group.command(name="add", description="[OWNER] Give a player Zombie Game Admin access")
@app_commands.describe(user="Player who should receive Zombie Game Admin access")
async def admin_add(interaction: discord.Interaction, user: discord.User):
    if not is_owner(interaction):
        await interaction.response.send_message(owner_denied_message(), ephemeral=True)
        return
    if user.id == OWNER_ID:
        await interaction.response.send_message("ℹ️ You are already the **Owner**.", ephemeral=True)
        return

    import asyncio
    try:
        already_admin = bool(await asyncio.to_thread(is_bot_admin, user.id))
        if already_admin:
            await interaction.response.send_message(f"ℹ️ {user.mention} is already a **Zombie Game Admin**.", ephemeral=True)
            return
        result = await asyncio.to_thread(add_bot_admin, user.id)
        if result is False:
            raise RuntimeError("storage.add_bot_admin returned False")
    except Exception as e:
        print(f"[OWNER] Failed to grant Game Admin to {user.id}: {e}")
        await interaction.response.send_message(f"❌ Could not give {user.mention} Game Admin access.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"🛠️ {user.mention} is now a **Zombie Game Admin**.\n"
        "They can use game-admin/testing tools, but they cannot manage admins or use Owner-only reset controls.",
        ephemeral=True,
    )


@admin_group.command(name="remove", description="[OWNER] Remove Zombie Game Admin access")
@app_commands.describe(user="Game Admin to remove")
async def admin_remove(interaction: discord.Interaction, user: discord.User):
    if not is_owner(interaction):
        await interaction.response.send_message(owner_denied_message(), ephemeral=True)
        return
    if user.id == OWNER_ID:
        await interaction.response.send_message("❌ The Owner cannot be removed.", ephemeral=True)
        return

    import asyncio
    try:
        if not bool(await asyncio.to_thread(is_bot_admin, user.id)):
            await interaction.response.send_message(f"ℹ️ {user.mention} is not a Zombie Game Admin.", ephemeral=True)
            return
        result = await asyncio.to_thread(remove_bot_admin, user.id)
        if result is False:
            raise RuntimeError("storage.remove_bot_admin returned False")
    except Exception as e:
        print(f"[OWNER] Failed to remove Game Admin {user.id}: {e}")
        await interaction.response.send_message(f"❌ Could not remove Game Admin access from {user.mention}.", ephemeral=True)
        return

    await interaction.response.send_message(f"✅ {user.mention} is no longer a **Zombie Game Admin**.", ephemeral=True)


@admin_group.command(name="list", description="[OWNER] List Zombie Game Admins")
async def admin_list(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message(owner_denied_message(), ephemeral=True)
        return

    import asyncio
    try:
        admin_ids = await asyncio.to_thread(get_bot_admins)
    except Exception as e:
        print(f"[OWNER] Failed to list Game Admins: {e}")
        await interaction.response.send_message("❌ Could not load the Game Admin list.", ephemeral=True)
        return

    lines = [f"👑 **Owner:** <@{OWNER_ID}>"]
    if not admin_ids:
        lines.append("🛠️ **Game Admins:** None")
    else:
        entries = []
        for admin_id in sorted({int(x) for x in admin_ids}):
            try:
                member = interaction.guild.get_member(admin_id) if interaction.guild else None
                user_obj = member or await bot.fetch_user(admin_id)
                entries.append(f"• {user_obj.mention} (`{admin_id}`)")
            except Exception:
                entries.append(f"• <@{admin_id}> (`{admin_id}`)")
        lines.append("🛠️ **Game Admins:**\n" + "\n".join(entries))

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# Register the /admin command group with Discord.
bot.tree.add_command(admin_group)


async def _run_launch_reset(interaction: discord.Interaction, confirm: bool = False):
    """Owner-only nuclear reset: fresh player state + empty leaderboards."""
    if not is_owner(interaction):
        await interaction.response.send_message(owner_denied_message(), ephemeral=True)
        return

    if not confirm:
        await interaction.response.send_message(
            "☢️ **LAUNCH RESET** will reset **every player** to fresh-start defaults and clear **all personal/server/global leaderboard records**.\n"
            "Your Zombie Game Admin list is **not** changed.\n\n"
            "If this is intentional, run **`/launch_reset confirm:true`**.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    try:
        count = await game_store.reset_all_players()
    except Exception as e:
        logger.exception("[LAUNCH RESET] Failed")
        await interaction.followup.send(
            f"❌ **Launch reset FAILED.** No success confirmation was issued.\nError: `{type(e).__name__}`",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        "☢️ **LAUNCH RESET COMPLETE**\n\n"
        f"🧟 Players reset: **{count}**\n"
        "🏆 Global/server/personal leaderboards: **0 / cleared**\n"
        "💰 Player cash, ⭐ Stars, ✨ XP, weapons, upgrades, Void progression, zones, meds, ammo and active runs: **fresh defaults**\n"
        "🛠️ Game Admin access: **unchanged**\n\n"
        "🚀 **The game is ready for a fresh launch.**",
        ephemeral=True,
    )


@bot.tree.command(name="launch_reset", description="[OWNER] Reset all players and leaderboards for a fresh launch")
@app_commands.describe(confirm="Set this to True to confirm the full launch reset")
async def launch_reset(interaction: discord.Interaction, confirm: bool = False):
    await _run_launch_reset(interaction, confirm)


@bot.tree.command(name="reset_everything", description="[OWNER] Reset all player progress and leaderboards")
@app_commands.describe(confirm="Set this to True to confirm the full reset")
async def reset_everything(interaction: discord.Interaction, confirm: bool = False):
    await _run_launch_reset(interaction, confirm)


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
        async with game_store.action_lock(target.id):
            player = game_store.get(target.id)

            # If the player is not currently running, initialise a normal run first.
            # Then jump directly to the requested wave and create a fresh encounter.
            if not player.run_active:
                start_run(player)

            player.run_active = True
            player.run_id = uuid.uuid4().hex
            player.wave = int(wave)
            player.zombies_remaining = 3
            player.enemy = None
            player.bloater_cooldown = 0
            player.bloaters_spawned_this_run = 0
            player.bloater_chance_steps = 0
            player.bloater_roll_wave = 0
            player.bloater_wave_result = False
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
        await game_store.save_one_async(str(target.id))

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
            view=CombatView(target.id, game_store, run_id=player.run_id),
            ephemeral=(target.id == interaction.user.id),
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


def _resolve_xp_boost_target(interaction: discord.Interaction, target_text: str):
    """Resolve Global, a Discord mention/ID, or an exact guild member name."""
    target_text = (target_text or "").strip()
    if target_text.lower() == "global":
        return "global", None
    import re
    match = re.fullmatch(r"<@!?(\d+)>", target_text)
    if match:
        return "player", int(match.group(1))
    if target_text.isdigit():
        return "player", int(target_text)
    guild = interaction.guild
    if guild is None:
        return None, None
    lowered = target_text.casefold()
    matches = []
    for member in guild.members:
        names = {
            str(getattr(member, "name", "") or "").casefold(),
            str(getattr(member, "display_name", "") or "").casefold(),
            str(getattr(member, "global_name", "") or "").casefold(),
        }
        if lowered in names:
            matches.append(member)
    if len(matches) == 1:
        return "player", matches[0].id
    if len(matches) > 1:
        return "ambiguous", matches
    return None, None


@bot.tree.command(name="xpbooster", description="[OWNER] Give a player or everyone 1.5x XP for 24 hours")
@app_commands.describe(target="Player name/mention/ID, or type Global for everyone")
async def xpbooster(interaction: discord.Interaction, target: str):
    """Owner-only temporary 1.5x XP grant. Personal/global boosts do not stack."""
    await interaction.response.defer(ephemeral=False)
    if not is_owner(interaction):
        await interaction.followup.send("❌ Owner only.", ephemeral=False)
        return

    kind, value = _resolve_xp_boost_target(interaction, target)
    expiry = datetime.now(timezone.utc) + timedelta(seconds=XP_BOOST_DURATION_SECONDS)
    expiry_iso = expiry.isoformat()

    if kind == "global":
        global GLOBAL_XP_BOOST_UNTIL
        GLOBAL_XP_BOOST_UNTIL = expiry_iso
        async with game_store.action_lock(OWNER_ID):
            owner_player = game_store.get(OWNER_ID)
            owner_player.global_xp_boost_until = expiry_iso
        await game_store.save_one_async(str(OWNER_ID))
        await interaction.followup.send(
            f"🌍 **GLOBAL 1.5x XP ACTIVATED!**\n✨ Everyone earns **1.5× XP** for 24 hours.\n"
            f"⏰ Expires <t:{int(expiry.timestamp())}:F> (<t:{int(expiry.timestamp())}:R>)\n"
            f"⚠️ Personal + global boosts do **not** stack to 2.25×.",
            ephemeral=False,
        )
        return

    if kind == "ambiguous":
        names = ", ".join(m.mention for m in value[:10])
        await interaction.followup.send(f"❌ That name matches multiple players: {names}\nUse a mention or Discord user ID instead.", ephemeral=False)
        return
    if kind != "player" or value is None:
        await interaction.followup.send("❌ Player not found. Use a mention, Discord user ID, exact server name, or `Global`.", ephemeral=False)
        return

    async with game_store.action_lock(value):
        player = game_store.get(value)
        player.xp_boost_until = expiry_iso
    await game_store.save_one_async(str(value))
    await interaction.followup.send(
        f"✨ **1.5x XP ACTIVATED** for <@{value}>!\n"
        f"⏰ Expires <t:{int(expiry.timestamp())}:F> (<t:{int(expiry.timestamp())}:R>)\n"
        f"XP earned during the boost is increased by 50%. Personal + global boosts never stack to 2.25×.",
        ephemeral=False,
    )


def _resolve_cash_boost_target(interaction: discord.Interaction, target_text: str):
    """Resolve Global, a Discord mention/ID, or an exact guild member name."""
    return _resolve_xp_boost_target(interaction, target_text)


@bot.tree.command(name="moneybooster", description="[OWNER] Give a player or everyone 1.5x Cash for 24 hours")
@app_commands.describe(target="Player name/mention/ID, or type Global for everyone")
async def moneybooster(interaction: discord.Interaction, target: str):
    """Owner-only temporary 1.5x Cash grant. Personal/global boosts do not stack."""
    await interaction.response.defer(ephemeral=False)
    if not is_owner(interaction):
        await interaction.followup.send("❌ Owner only.", ephemeral=False)
        return

    kind, value = _resolve_cash_boost_target(interaction, target)
    expiry = datetime.now(timezone.utc) + timedelta(seconds=CASH_BOOST_DURATION_SECONDS)
    expiry_iso = expiry.isoformat()

    if kind == "global":
        global GLOBAL_CASH_BOOST_UNTIL
        GLOBAL_CASH_BOOST_UNTIL = expiry_iso
        async with game_store.action_lock(OWNER_ID):
            owner_player = game_store.get(OWNER_ID)
            owner_player.global_cash_boost_until = expiry_iso
        await game_store.save_one_async(str(OWNER_ID))
        await interaction.followup.send(
            f"🌍 **GLOBAL 1.5x CASH ACTIVATED!**\n💰 Everyone earns **1.5× Cash** for 24 hours.\n"
            f"⏰ Expires <t:{int(expiry.timestamp())}:F> (<t:{int(expiry.timestamp())}:R>)\n"
            f"⚠️ Personal + global cash boosts do **not** stack to 2.25×.",
            ephemeral=False,
        )
        return

    if kind == "ambiguous":
        names = ", ".join(m.mention for m in value[:10])
        await interaction.followup.send(f"❌ That name matches multiple players: {names}\nUse a mention or Discord user ID instead.", ephemeral=False)
        return
    if kind != "player" or value is None:
        await interaction.followup.send("❌ Player not found. Use a mention, Discord user ID, exact server name, or `Global`.", ephemeral=False)
        return

    async with game_store.action_lock(value):
        player = game_store.get(value)
        player.cash_boost_until = expiry_iso
    await game_store.save_one_async(str(value))
    await interaction.followup.send(
        f"💰 **1.5x CASH ACTIVATED** for <@{value}>!\n"
        f"⏰ Expires <t:{int(expiry.timestamp())}:F> (<t:{int(expiry.timestamp())}:R>)\n"
        f"Cash earned during the boost is increased by 50%. Personal + global boosts never stack to 2.25×.",
        ephemeral=False,
    )


def _booster_status_line(label: str, expiry_iso: str | None) -> str:
    if not expiry_iso:
        return f"{label}: ❌ **Inactive**"
    try:
        expiry = datetime.fromisoformat(expiry_iso)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        expiry_ts = int(expiry.timestamp())
    except (TypeError, ValueError, OverflowError):
        return f"{label}: ❌ **Inactive**"
    if expiry_ts <= int(datetime.now(timezone.utc).timestamp()):
        return f"{label}: ❌ **Inactive**"
    return f"{label}: ✅ **Active** — <t:{expiry_ts}:R> remaining"


@bot.tree.command(name="xpboosterstatus", description="Check the remaining time on XP boosters")
async def xpboosterstatus(interaction: discord.Interaction):
    """Show personal and global XP booster status. Available to everyone."""
    player = game_store.get(interaction.user.id)
    embed = make_embed(
        title="✨ XP BOOSTER STATUS",
        description=(
            f"{_booster_status_line('🌍 Global XP Booster', GLOBAL_XP_BOOST_UNTIL)}\n"
            f"{_booster_status_line('👤 Your Personal XP Booster', getattr(player, 'xp_boost_until', None))}\n\n"
            f"**Current XP Multiplier:** **{xp_boost_multiplier(player):.1f}×**\n"
            "⚠️ Personal + global boosters do **not** stack."
        ),
        color=discord.Color.blue(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="moneyboosterstatus", description="Check the remaining time on money boosters")
async def moneyboosterstatus(interaction: discord.Interaction):
    """Show personal and global money booster status. Available to everyone."""
    player = game_store.get(interaction.user.id)
    embed = make_embed(
        title="💰 MONEY BOOSTER STATUS",
        description=(
            f"{_booster_status_line('🌍 Global Money Booster', GLOBAL_CASH_BOOST_UNTIL)}\n"
            f"{_booster_status_line('👤 Your Personal Money Booster', getattr(player, 'cash_boost_until', None))}\n\n"
            f"**Current Cash Multiplier:** **{cash_boost_multiplier(player):.1f}×**\n"
            "⚠️ Personal + global boosters do **not** stack."
        ),
        color=discord.Color.gold(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="addmoney", description="[ADMIN] Add money to a player")
@app_commands.describe(user="Player to give money to (leave empty for yourself)", amount="Amount to add (e.g. 5000)")
async def addmoney(interaction: discord.Interaction, amount: int, user: discord.User = None):
    await interaction.response.defer(ephemeral=True)
    if not has_admin_commands(interaction):
        await interaction.followup.send(admin_denied_message(), ephemeral=True)
        return
    if amount < 0:
        await interaction.followup.send("❌ Amount must be **0 or greater**.", ephemeral=True)
        return

    target = user or interaction.user
    async with game_store.action_lock(target.id):
        player = game_store.get(target.id)
        player.money += amount
    await game_store.save_one_async(str(target.id))
    await interaction.followup.send(f"💰 **+${amount}** added to {target.mention} → Now has **${player.money}**", ephemeral=True)


@bot.tree.command(name="addstars", description="[ADMIN] Add stars to a player")
@app_commands.describe(user="Player to give stars to", amount="Amount to add")
async def addstars(interaction: discord.Interaction, amount: int, user: discord.User = None):
    await interaction.response.defer(ephemeral=True)
    if not has_admin_commands(interaction):
        await interaction.followup.send(admin_denied_message(), ephemeral=True)
        return
    if amount < 0:
        await interaction.followup.send("❌ Amount must be **0 or greater**.", ephemeral=True)
        return

    target = user or interaction.user
    async with game_store.action_lock(target.id):
        player = game_store.get(target.id)
        player.stars += amount
    await game_store.save_one_async(str(target.id))
    await interaction.followup.send(f"⭐ **+{amount} stars** to {target.mention} → Now has **{player.stars}** ⭐", ephemeral=True)


@bot.tree.command(name="addxp", description="[ADMIN] Add XP to a player")
@app_commands.describe(user="Player to give XP to", amount="Amount to add")
async def addxp(interaction: discord.Interaction, amount: int, user: discord.User = None):
    await interaction.response.defer(ephemeral=True)
    if not has_admin_commands(interaction):
        await interaction.followup.send(admin_denied_message(), ephemeral=True)
        return
    if amount < 0:
        await interaction.followup.send("❌ Amount must be **0 or greater**.", ephemeral=True)
        return

    target = user or interaction.user
    async with game_store.action_lock(target.id):
        player = game_store.get(target.id)
        old_level = player.level
        player.xp += amount
        level_ups = max(0, player.level - old_level)
        if level_ups:
            player.stars += level_ups
    await game_store.save_one_async(str(target.id))
    await interaction.followup.send(f"✨ **+{amount} XP** to {target.mention} → Level {player.level} | XP: {player.xp}" + (f" | +{level_ups} ⭐" if level_ups else ""), ephemeral=True)


@bot.tree.command(name="resetplayer", description="[ADMIN] Reset a player's progress")
@app_commands.describe(user="Player to reset")
async def resetplayer(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)
    if not has_admin_commands(interaction):
        await interaction.followup.send(admin_denied_message(), ephemeral=True)
        return
    
    # Create fresh survivor
    from dataclasses import replace
    async with game_store.action_lock(user.id):
        fresh = game_store.get(user.id)
        new_player = fresh.__class__()
        game_store.players[str(user.id)] = new_player
    await game_store.save_one_async(str(user.id))
    await interaction.followup.send(f"🔄 {user.mention} has been reset to level 1!", ephemeral=True)


@bot.tree.command(name="zombie_give", description="[ADMIN] Give money/stars/xp to restore a player")
@app_commands.describe(user="Player to restore", money="Money to give", stars="Stars to give", xp="XP to give")
async def zombie_give(interaction: discord.Interaction, user: discord.User, money: int = 0, stars: int = 0, xp: int = 0):
    await interaction.response.defer(ephemeral=True)
    if not has_admin_commands(interaction):
        await interaction.followup.send(admin_denied_message(), ephemeral=True)
        return
    if money < 0 or stars < 0 or xp < 0:
        await interaction.followup.send("❌ Money, Stars and XP must all be **0 or greater**.", ephemeral=True)
        return
    
    async with game_store.action_lock(user.id):
        player = game_store.get(user.id)
        old_level = player.level
        player.money += money
        player.stars += stars
        player.xp += xp
        level_ups = max(0, player.level - old_level)
        if level_ups:
            player.stars += level_ups
    await game_store.save_one_async(str(user.id))
    await interaction.followup.send(f"✅ Restored {user.mention}: +${money}, +{stars}⭐, +{xp} XP" + (f" +{level_ups}⭐ level-up bonus" if level_ups else "") + f"\nNow: ${player.money} | {player.stars}⭐ | Lvl {player.level} ({player.xp} XP)", ephemeral=True)

@bot.tree.command(name="addvoidessence", description="[ADMIN] Add Void Essence to a player")
@app_commands.describe(user="Player to give Void Essence to", amount="Amount of Void Essence to add")
async def addvoidessence(interaction: discord.Interaction, amount: int, user: discord.User = None):
    await interaction.response.defer(ephemeral=True)
    if not has_admin_commands(interaction):
        await interaction.followup.send(admin_denied_message(), ephemeral=True)
        return
    if amount < 0:
        await interaction.followup.send("❌ Amount must be **0 or greater**.", ephemeral=True)
        return

    
    target=user or interaction.user
    async with game_store.action_lock(target.id):
        player=game_store.get(target.id)
        player.void_essence=max(0, player.void_essence + amount)
    await game_store.save_one_async(str(target.id))
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
