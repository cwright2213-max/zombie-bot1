"""Ultimate clean bot V6 POSTGRES CONSTANT SAVE - every action saves instantly - zero loss"""
import os, sys, json, random, logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone
import discord
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('zombie-bot')
from discord import app_commands

# --- VOLUME PERSISTENT STORAGE - NEVER WIPES AFTER THIS ---
from storage import load_all_players, save_player, DB_PATH, SAVE_FILE, get_bot_admins, is_bot_admin, add_bot_admin, remove_bot_admin
print(f"[STORAGE] Using POSTGRES - CONSTANT SAVE ENABLED")

# Anti double-click lock for upgrades
_purchase_locks: set[int] = set()

# Bloater config - MUST be before combat_embed
BLOATER_BASE = {"health": 280, "damage": 4, "money": 350, "xp": 120}
BLOATER_MAX_PER_ZONE = {
    "Graveyard": 1,
    "Mega Death City": 2,
    "Frostbitten Outskirts": 3,
    "Toxic Wasteland": 4,
    "The Void": 5,
}
BLOATER_MIN_WAVE = 5
BLOATER_FUSE = 5
BLOATER_EXPLODE_PCT = 0.65

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
    if player.enemy and player.enemy.is_bloater:
        embed.add_field(name=f"💣 BLOATER - {player.enemy.bloater_timer} ATTACKS LEFT!", value=f"⏰ Kill it in {player.enemy.bloater_timer} attacks or take {int(BLOATER_EXPLODE_PCT*100)}% max HP damage! Solo wave - reward if you survive!", inline=False)
    if last_msgs:
        clean = [m for m in last_msgs if m and "HP restored" not in m and "Waves survived" not in m][:3]
        if clean:
            embed.add_field(name="⚔️ Last action", value="\n".join(clean)[:1024], inline=False)
    embed.set_footer(text=f"💰 ${player.money} | ⭐ {player.stars} | ✨ {player.xp} XP | {player.ammo_name} {player.magazine}/{player.magazine_size}")
    return embed

MAX_PAINKILLERS_PER_RUN = 3
MAX_FULL_RESTORES_PER_RUN = 1
ZONES: dict[str, dict[str, Any]] = {
    "Graveyard": {"min_level": 1, "hp_mult": 0.9, "dmg_mult": 0.9, "money_mult": 2.0, "xp_mult": 1.6, "desc": "Foggy, quiet, and good for learning.", "weights": [60, 25, 12, 3], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.00, "Frostbite": 1.00, "Toxic": 1.00, "Shock": 1.00}},
    "Mega Death City": {"min_level": 50, "hp_mult": 2.2, "dmg_mult": 1.4, "money_mult": 3.5, "xp_mult": 2.1, "desc": "A concrete jungle with tougher, richer zombies.", "weights": [30, 30, 25, 15], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.20, "Frostbite": 0.90, "Toxic": 1.00, "Shock": 1.15}},
    "Frostbitten Outskirts": {"min_level": 100, "hp_mult": 5.5, "dmg_mult": 2.0, "money_mult": 5.0, "xp_mult": 2.8, "desc": "Freezing rain and frost armor - NOT for level 50s.", "weights": [20, 20, 35, 25], "ammo_mods": {"Standard": 1.00, "Bleed": 0.90, "Incendiary": 1.40, "Frostbite": 0.70, "Toxic": 1.00, "Shock": 1.15}},
    "Toxic Wasteland": {"min_level": 150, "hp_mult": 9.0, "dmg_mult": 2.6, "money_mult": 7.5, "xp_mult": 3.6, "desc": "A green haze where toxic rounds shine. Bring real gear.", "weights": [15, 15, 35, 35], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.10, "Frostbite": 1.00, "Toxic": 1.50, "Shock": 0.90}},
    "The Void": {"min_level": 200, "hp_mult": 14.0, "dmg_mult": 3.4, "money_mult": 10.0, "xp_mult": 4.8, "desc": "Endgame. Everything wants you dead. 3-4 shots? Not here.", "weights": [10, 10, 30, 50], "ammo_mods": {"Standard": 1.00, "Bleed": 1.10, "Incendiary": 1.15, "Frostbite": 1.10, "Toxic": 1.25, "Shock": 1.50}},
}
ZONE_ORDER = ["Graveyard", "Mega Death City", "Frostbitten Outskirts", "Toxic Wasteland", "The Void"]
AMMO: dict[str, dict[str, Any]] = {
    "Standard": {"unlock_level": 1, "price": 0, "desc": "Reliable regular lead.", "effect": None, "cost_per_attack": 1, "box_price": 15, "box_amount": 24},
    "Bleed": {"unlock_level": 10, "price": 200, "desc": "25% bleed 15 dmg x3", "effect": "bleed", "cost_per_attack": 2, "box_price": 50, "box_amount": 24},
    "Incendiary": {"unlock_level": 35, "price": 600, "desc": "30% burn 20 dmg x3", "effect": "burn", "cost_per_attack": 3, "box_price": 100, "box_amount": 24},
    "Frostbite": {"unlock_level": 70, "price": 1200, "desc": "20% freeze halves dmg x4 + 10 dmg x2", "effect": "freeze", "cost_per_attack": 4, "box_price": 100, "box_amount": 24},
    "Toxic": {"unlock_level": 110, "price": 2500, "desc": "35% poison 15 dmg x5", "effect": "poison", "cost_per_attack": 5, "box_price": 150, "box_amount": 24},
    "Shock": {"unlock_level": 160, "price": 5000, "desc": "15% stun 1 turn + 20 dmg", "effect": "shock", "cost_per_attack": 6, "box_price": 185, "box_amount": 24},
}
WEAPONS: dict[str, dict[str, Any]] = {
    "Pistol": {"damage": 20, "mag": 12, "price": 0, "unlock_level": 1, "shots": 1},
    "Shotgun": {"damage": 45, "mag": 6, "price": 250, "unlock_level": 15, "shots": 1},
    "Rifle": {"damage": 25, "mag": 30, "price": 2500, "unlock_level": 30, "shots": 2},
    "SMG": {"damage": 15, "mag": 42, "price": 4000, "unlock_level": 60, "shots": 3},
    "Sawed-Off": {"damage": 70, "mag": 2, "price": 6000, "unlock_level": 90, "shots": 1},
}

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
        if "Pistol" not in allowed["owned_weapons"]: allowed["owned_weapons"].append("Pistol")
        if "stars" not in data: allowed["stars"] = max(0, level_for_xp(int(data.get("xp", 0))) - 1)
        return cls(**allowed)
class GameStore:
    """CONSTANT SAVE - every single player action triggers instant Postgres save"""
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
                print(f"[SAVE] New player {key} instantly saved (#{self._save_count})")
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
            try: save_player(k, p.to_dict())
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

        btn_shop = discord.ui.Button(label="🛒 Shop", style=discord.ButtonStyle.primary, row=0)
        async def shop_cb(interaction: discord.Interaction):
            p = self.store.get(self.user_id)
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
            if p.run_active and p.enemy:
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

        # ROW 1: Zones + Refresh - slick 4-button layout
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

        # ROW 1: Refresh (4th button)
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
            "",
            f"Balance: **${player.money}** | Stars: **{player.stars}**",
            f"Level **{player.level}** | Zone: **{player.zone_name}**",
        ]
        return "\n".join(lines)

    @discord.ui.button(label="🔫", style=discord.ButtonStyle.primary, row=0)
    async def weapons_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        await interaction.response.edit_message(content=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="🧪", style=discord.ButtonStyle.primary, row=0)
    async def ammo_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        await interaction.response.edit_message(content=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="💊", style=discord.ButtonStyle.primary, row=0)
    async def meds_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        await interaction.response.edit_message(content=MedsShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=MedsShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.primary, row=0)
    async def upgrades_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        await interaction.response.edit_message(content=UpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=UpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.primary, row=0)
    async def stars_btn(self, interaction: discord.Interaction, _b):
        p=self.store.get(self.user_id)
        await interaction.response.edit_message(content=StarUpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")).get_shop_text(p), embed=None, view=StarUpgradeView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor")))

    @discord.ui.button(label="Return", style=discord.ButtonStyle.secondary, row=1)
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

        for i, wname in enumerate(["Pistol", "Shotgun", "Rifle", "SMG", "Sawed-Off"]):
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
                # FIX: Always equip, even if already owned - was only buying when not owned, so switching between owned guns did nothing (SMG -> Sawn-off bug)
                msgs = buy_item(p, wn)
                self.store.save()
                content = self.get_shop_text(p, selected_override=wn, extra_msgs=msgs)
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
            if self.user_id in _purchase_locks:
                try:
                    await interaction.response.defer()
                except:
                    pass
                return
            _purchase_locks.add(self.user_id)
            try:
                try:
                    await interaction.response.defer()
                except:
                    pass
                p=self.store.get(self.user_id)
                msgs = buy_item(p, self.selected_weapon)
                try:
                    await self.store.save_one_async(str(self.user_id))
                except:
                    self.store.save()
                content = self.get_shop_text(p, selected_override=self.selected_weapon, extra_msgs=msgs)
                await interaction.edit_original_response(content=content, view=WeaponShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_weapon=self.selected_weapon))
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
        for wname in ["Pistol", "Shotgun", "Rifle", "SMG", "Sawed-Off"]:
            if wname not in WEAPONS:
                continue
            w = WEAPONS[wname]
            owned = wname in player.owned_weapons
            is_sel = wname == sel
            marker = " ← SELECTED" if is_sel else ""
            status_str = "Owned" if owned else f"LOCKED Level {w['unlock_level']} - ${w['price']}"
            if owned:
                status_str = f"Owned - Dmg {w.get('damage', '?')} | Mag {w.get('mag_size', '?')}"
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
                if self.user_id in _purchase_locks:
                    try:
                        await interaction.response.defer()
                    except:
                        pass
                    return
                _purchase_locks.add(self.user_id)
                try:
                    try:
                        await interaction.response.defer()
                    except:
                        pass
                    p=self.store.get(self.user_id)
                    msgs = equip_ammo(p, an)
                    try:
                        await self.store.save_one_async(str(self.user_id))
                    except:
                        self.store.save()
                    self.selected_ammo = an
                    content = self.get_shop_text(p, extra_msgs=msgs)
                    await interaction.edit_original_response(content=content, view=AmmoShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_ammo=an))
                finally:
                    _purchase_locks.discard(self.user_id)
            btn.callback = cb
            self.add_item(btn)
        
        box_price = AMMO[self.selected_ammo]["box_price"]
        for qty, row in [(1,2), (10,2), (100,3), (1000,3)]:
            total = box_price * qty
            label = f"+{qty} (${total:,})"
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary, row=row)
            async def bulk_cb(interaction, q=qty, ammo=self.selected_ammo):
                p=self.store.get(self.user_id)
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
                p=self.store.get(self.user_id)
                total_cost = (15 if med == "painkillers" else 80) * q
                if p.money < total_cost:
                    msgs = [f"❌ Need ${total_cost} for {q}x {med}, you have ${p.money}"]
                    content = self.get_shop_text(p, selected_override=med, extra_msgs=msgs)
                    await interaction.response.edit_message(content=content, view=MedsShopView(self.user_id, self.store, display_name=getattr(self, "display_name", "Survivor"), selected_med=med))
                    return
                # Clean single loop - +2 per painkiller purchase, +1 per full restore
                bought = 0
                for _ in range(q):
                    if med == "painkillers":
                        if p.money >= 15:
                            p.money -= 15
                            p.painkillers += 2
                            bought += 2
                        else:
                            break
                    else:
                        if p.money >= 80:
                            p.money -= 80
                            p.full_restores += 1
                            bought += 1
                        else:
                            break
                self.store.save()
                if med == "painkillers":
                    msgs = [f"💊 Bought {q}x Painkillers +{bought} (2 per purchase) | Now {p.painkillers}x | ${p.money} left"]
                else:
                    msgs = [f"✨ Bought {q}x Full Restore +{bought} | Now {p.full_restores}x | ${p.money} left"]
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

        # Single buy button for selected upgrade - no bulk as requested + anti double-click
        cost = get_upgrade_cost(player, self.selected_up)
        buy_label = f"Buy {self.selected_up.capitalize()} ${cost}"
        btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.success, row=2)
        async def buy_cb(interaction):
            # Prevent double-click race
            if self.user_id in _purchase_locks:
                try:
                    await interaction.response.defer()
                except:
                    pass
                return
            _purchase_locks.add(self.user_id)
            try:
                try:
                    await interaction.response.defer()
                except:
                    pass
                p=self.store.get(self.user_id)
                msgs = upgrade(p, self.selected_up)
                # Use async save to ensure DB write completes before next click
                try:
                    await self.store.save_one_async(str(self.user_id))
                except:
                    self.store.save()
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

        # Single buy button for selected star - no bulk + anti double-click fix for Twiitcchy bug
        cost = get_star_upgrade_cost(player, self.selected_star)
        buy_label = f"Buy {self.selected_star.capitalize()} ⭐{cost}"
        btn_buy = discord.ui.Button(label=buy_label[:80], style=discord.ButtonStyle.success, row=2)
        async def buy_cb(interaction):
            # Prevent double-click race - this was causing stars to go up in price without level up
            if self.user_id in _purchase_locks:
                try:
                    await interaction.response.defer()
                except:
                    pass
                return
            _purchase_locks.add(self.user_id)
            try:
                try:
                    await interaction.response.defer()
                except:
                    pass
                p=self.store.get(self.user_id)
                # Re-check cost with fresh data
                fresh_cost = get_star_upgrade_cost(p, self.selected_star)
                msgs = upgrade_star(p, self.selected_star)
                try:
                    await self.store.save_one_async(str(self.user_id))
                except:
                    self.store.save()
                content = self.get_shop_text(p, selected_override=self.selected_star, extra_msgs=msgs)
                # If cost mismatch due to race, show warning
                if fresh_cost != cost:
                    content = f"⚠️ Race prevented! Cost was ⭐{cost} but fresh was ⭐{fresh_cost}.\n" + content
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




class ZoneView(PlayerView):
    def __init__(self, user_id, store, display_name: str = "Survivor", timeout: float = 180):
        super().__init__(user_id, store, display_name)
        for i, zone_name in enumerate(ZONES):
            btn = discord.ui.Button(label=zone_name, style=discord.ButtonStyle.primary, row=i//2)
            async def cb(interaction, zn=zone_name):
                p=self.store.get(self.user_id); msgs=change_zone(p,zn); await self.store.save_one_async(str(self.user_id))
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
    name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "global_name", None) or interaction.user.name
    await interaction.followup.send(content=status(player, display_name=name), view=ZombieMenuView(interaction.user.id, game_store, display_name=name))

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

# --- ADMIN SYSTEM ---
# Bot admins are stored in /data/players.db and persist across deploys
def is_server_admin(interaction: discord.Interaction) -> bool:
    # 1. Check if user is in bot admin list (persistent team)
    try:
        if is_bot_admin(interaction.user.id):
            return True
    except:
        pass
    # 2. Check Discord server permissions
    if interaction.guild is None:
        # In DMs, only bot admins can use admin commands
        return False
    try:
        perms = interaction.user.guild_permissions
        if perms.administrator:
            return True
        if perms.manage_guild:
            return True
    except:
        pass
    return False

def is_owner_or_server_admin(interaction: discord.Interaction) -> bool:
    """For /giveadmin - only server owners/admins can assign new bot admins"""
    if interaction.guild is None:
        return False
    try:
        # Guild owner always can
        if interaction.guild.owner_id == interaction.user.id:
            return True
        perms = interaction.user.guild_permissions
        if perms.administrator:
            return True
    except:
        pass
    # Also existing bot admins can add more (to build team)
    try:
        if is_bot_admin(interaction.user.id):
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


@bot.tree.command(name="giveadmin", description="[ADMIN] Give bot admin permissions to a user for testing")
@app_commands.describe(user="User to make bot admin")
async def giveadmin(interaction: discord.Interaction, user: discord.User):
    if not is_owner_or_server_admin(interaction):
        await interaction.response.send_message("❌ Only **Server Owner** or existing Bot Admins can give admin permissions.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if is_bot_admin(user.id):
        await interaction.followup.send(f"⚠️ {user.mention} is already a Bot Admin!", ephemeral=True)
        return
    success = add_bot_admin(user.id, added_by=str(interaction.user.id))
    if success:
        await interaction.followup.send(f"✅ **{user.mention} is now a Bot Admin!**\nThey can use: /addmoney, /addstars, /addxp, /resetplayer, /zombie_give, /giveadmin, /removeadmin\n\n*This persists across deploys (stored in /data)*", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Failed to add {user.mention} as admin. Check logs.", ephemeral=True)

@bot.tree.command(name="removeadmin", description="[ADMIN] Remove bot admin permissions from a user")
@app_commands.describe(user="User to remove admin from")
async def removeadmin(interaction: discord.Interaction, user: discord.User):
    if not is_owner_or_server_admin(interaction):
        await interaction.response.send_message("❌ Only **Server Owner** or existing Bot Admins can remove admins.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if not is_bot_admin(user.id):
        await interaction.followup.send(f"⚠️ {user.mention} is not a Bot Admin.", ephemeral=True)
        return
    if user.id == interaction.user.id:
        await interaction.followup.send(f"⚠️ You are removing yourself! Removing...", ephemeral=True)
    success = remove_bot_admin(user.id)
    if success:
        await interaction.followup.send(f"✅ **{user.mention} is no longer a Bot Admin.**", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Failed to remove {user.mention}.", ephemeral=True)

@bot.tree.command(name="listadmins", description="[ADMIN] List all bot admins")
async def listadmins(interaction: discord.Interaction):
    if not is_server_admin(interaction):
        await interaction.response.send_message("❌ You need Bot Admin or Server Admin permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    admins = get_bot_admins()
    if not admins:
        await interaction.followup.send("📋 **No Bot Admins yet.**\nAnyone with Discord Administrator can add the first one with /giveadmin", ephemeral=True)
        return
    lines = []
    for uid in admins:
        try:
            u = await bot.fetch_user(int(uid))
            lines.append(f"- {u.mention} ({u.name}) - `{uid}`")
        except:
            lines.append(f"- <@{uid}> - `{uid}` (not cached)")
    await interaction.followup.send(f"📋 **Bot Admins ({len(admins)}):**\n" + "\n".join(lines), ephemeral=True)


def main():
    import os, sys
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN missing")
        sys.exit(1)
    print(f"Token found {token[:10]}... Starting V6 CONSTANT SAVE - crit/armor/loot/medic/pet fixed - CONSTANT SAVE")
    bot.run(token, log_handler=None)

if __name__ == "__main__":
    main()
