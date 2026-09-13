"""Turn-based Discord zombie survival - FIXED H-01 profiles never silently lost"""
from __future__ import annotations
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
    "Graveyard": {"min_level": 1, "hp_mult": 1.0, "dmg_mult": 1.0, "money_mult": 1.0, "xp_mult": 1.0, "desc": "Foggy, quiet, and good for learning.", "weights": [60, 25, 12, 3], "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.00, "Frostbite": 1.00, "Toxic": 1.00, "Shock": 1.00}},
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
    "Walker": {"health": 50, "damage": 10, "money": 10, "xp": 5},
    "Runner": {"health": 35, "damage": 18, "money": 20, "xp": 10},
    "Brute": {"health": 100, "damage": 15, "money": 40, "xp": 20},
    "Mutant": {"health": 150, "damage": 25, "money": 100, "xp": 50},
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
        return self.crit_upgrades * 0.02  # 2% per upgrade
    @property
    def armor_reduction(self) -> int:
        return self.armor_upgrades * 2  # -2 dmg per upgrade
    @property
    def scavenger_bonus(self) -> float:
        return 1.0 + self.scavenger_upgrades * 0.05
        # max health: 100 base + 20 per health upgrade
        self.max_health = 100 + self.health_upgrades * 20
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
    return 100 + (level - 1) * 25

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
        player.magazine -= cost
        mod = ammo_modifier(player, player.ammo_name)
        dmg = int(player.weapon_damage * mod)
        is_crit = random.random() < player.crit_chance
        if is_crit:
            dmg = int(dmg * 2)
        enemy.health = max(0, enemy.health - dmg)
        mod_txt = f" (Zone {int(mod*100)}%)" if mod != 1.0 else ""
        crit_txt = " **CRIT!**" if 'is_crit' in locals() and is_crit else ""
        messages.append(f"🔫 Hit **{enemy.name} for {dmg}**{crit_txt} using {player.ammo_name} ({cost}/shot){mod_txt}")
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
        "damage": 350,
        "health": 300,
        "mag": 500,
        "crit": 700,
        "armor": 600,
        "scavenger": 900,
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
    if player.run_active:
        return ["Can't upgrade in a run!"]
    stat = stat.lower().strip()
    # Map aliases to canonical
    alias_map = {
        "health": "health", "hp": "health", "max_health": "health",
        "damage": "damage", "weapon": "damage", "dmg": "damage",
        "mag": "mag", "magazine": "mag", "ammo": "mag",
        "crit": "crit", "critical": "crit", "crit_chance": "crit",
        "armor": "armor", "armour": "armor", "def": "armor", "defense": "armor", "tank": "armor",
        "scavenger": "scavenger", "scav": "scavenger", "money": "scavenger", "loot": "scavenger", "economy": "scavenger",
    }
    canonical = alias_map.get(stat)
    if not canonical:
        return [f"Unknown upgrade '{stat}'. Options: health(${get_upgrade_cost(player,'health')}) / damage(${get_upgrade_cost(player,'damage')}) / mag(${get_upgrade_cost(player,'mag')}) / crit(${get_upgrade_cost(player,'crit')}) / armor(${get_upgrade_cost(player,'armor')}) / scavenger(${get_upgrade_cost(player,'scavenger')}) | 💰 ${player.money} | ⭐ {player.stars} flex"]
    
    cost = get_upgrade_cost(player, canonical)
    if player.money < cost:
        return [f"Need ${cost} for {canonical} upgrade, you have ${player.money}. Grind more waves!"]
    
    player.money -= cost
    if canonical == "health":
        player.health_upgrades += 1
        player.recalc_stats()
        player.health = player.max_health
        return [f"❤️ Max HP → **{player.max_health}** (+{player.health_upgrades*20}) | Paid ${cost} | 💰 ${player.money} left | Next: ${get_upgrade_cost(player,'health')}"]
    if canonical == "damage":
        player.damage_upgrades += 1
        player.recalc_stats()
        return [f"💥 Damage → **{player.weapon_damage}** (base + {player.damage_upgrades*3} from {player.damage_upgrades} upgrades) | Paid ${cost} | 💰 ${player.money} left | Next: ${get_upgrade_cost(player,'damage')}"]
    if canonical == "mag":
        player.mag_upgrades += 1
        player.recalc_stats()
        return [f"📦 Mag → **{player.magazine_size}** (+{player.mag_upgrades*1}) | Paid ${cost} | 💰 ${player.money} left | Next: ${get_upgrade_cost(player,'mag')}"]
    if canonical == "crit":
        player.crit_upgrades += 1
        return [f"🎯 Crit → **{int(player.crit_chance*100)}%** (+2% per level, 2x dmg) | Paid ${cost} | 💰 ${player.money} left | Next: ${get_upgrade_cost(player,'crit')}"]
    if canonical == "armor":
        player.armor_upgrades += 1
        return [f"🛡️ Armor → **-{player.armor_reduction} dmg taken** (-2 per level) | Paid ${cost} | 💰 ${player.money} left | Next: ${get_upgrade_cost(player,'armor')}"]
    if canonical == "scavenger":
        player.scavenger_upgrades += 1
        return [f"💰 Scavenger → **+{int((player.scavenger_bonus-1)*100)}% money** per kill | Paid ${cost} | 💰 ${player.money} left | Next: ${get_upgrade_cost(player,'scavenger')}"]
    return [f"Unknown error"]


def _grant_star_drop(player: Survivor) -> list[str]:
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