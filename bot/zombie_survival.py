"""Turn-based Discord zombie survival - SEPARATE AMMO POOLS + RARITY COSTS"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SAVE_FILE = Path("zombie_saves.json")

MAX_PAINKILLERS_PER_RUN = 3
MAX_FULL_RESTORES_PER_RUN = 1

ZONES: dict[str, dict[str, Any]] = {
    "Graveyard": {
        "min_level": 1, "hp_mult": 1.0, "dmg_mult": 1.0, "money_mult": 1.0, "xp_mult": 1.0,
        "desc": "Foggy, quiet, and good for learning.",
        "weights": [60, 25, 12, 3],
        "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.00, "Frostbite": 1.00, "Toxic": 1.00, "Shock": 1.00},
    },
    "Mega Death City": {
        "min_level": 50, "hp_mult": 2.2, "dmg_mult": 1.4, "money_mult": 2.5, "xp_mult": 2.0,
        "desc": "A concrete jungle with tougher, richer zombies.",
        "weights": [30, 30, 25, 15],
        "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.20, "Frostbite": 0.90, "Toxic": 1.00, "Shock": 1.15},
    },
    "Frostbitten Outskirts": {
        "min_level": 100, "hp_mult": 3.8, "dmg_mult": 1.8, "money_mult": 4.0, "xp_mult": 3.5,
        "desc": "Freezing rain and frost armor.",
        "weights": [20, 20, 35, 25],
        "ammo_mods": {"Standard": 1.00, "Bleed": 0.90, "Incendiary": 1.40, "Frostbite": 0.70, "Toxic": 1.00, "Shock": 1.15},
    },
    "Toxic Wasteland": {
        "min_level": 150, "hp_mult": 6.0, "dmg_mult": 2.3, "money_mult": 6.5, "xp_mult": 5.5,
        "desc": "A green haze where toxic rounds shine.",
        "weights": [15, 15, 35, 35],
        "ammo_mods": {"Standard": 1.00, "Bleed": 1.00, "Incendiary": 1.10, "Frostbite": 1.00, "Toxic": 1.50, "Shock": 0.90},
    },
    "The Void": {
        "min_level": 200, "hp_mult": 10.0, "dmg_mult": 3.0, "money_mult": 10.0, "xp_mult": 8.0,
        "desc": "Endgame. Everything wants you dead.",
        "weights": [10, 10, 30, 50],
        "ammo_mods": {"Standard": 1.00, "Bleed": 1.10, "Incendiary": 1.15, "Frostbite": 1.10, "Toxic": 1.25, "Shock": 1.50},
    },
}

# NEW COSTS - rarer = more expensive
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
    "Sawed-Off": {"damage": 70, "mag": 2, "price": 1800, "unlock_level": 90},
}

ZOMBIES: dict[str, dict[str, int]] = {
    "Walker": {"health": 50, "damage": 10, "money": 10, "xp": 5},
    "Runner": {"health": 35, "damage": 18, "money": 20, "xp": 10},
    "Brute": {"health": 100, "damage": 15, "money": 40, "xp": 20},
    "Mutant": {"health": 150, "damage": 25, "money": 100, "xp": 50},
}

@dataclass
class Enemy:
    name: str
    health: int
    max_health: int
    damage: int
    money_reward: int
    xp_reward: int
    effects: dict[str, int] = field(default_factory=dict)

@dataclass
class Survivor:
    max_health: int = 100
    health: int = 100
    money: int = 0
    xp: int = 0
    stars: int = 0
    weapon_name: str = "Pistol"
    weapon_damage: int = 20
    magazine_size: int = 12
    magazine: int = 12
    # NEW: separate pools
    spare_ammo: dict[str, int] = field(default_factory=lambda: {"Standard": 36})
    full_restores: int = 1
    painkillers: int = 3
    painkillers_used_this_run: int = 0
    full_restores_used_this_run: int = 0
    run_money_earned: int = 0
    run_xp_earned: int = 0
    zone_name: str = "Graveyard"
    ammo_name: str = "Standard"
    owned_ammo: list[str] = field(default_factory=lambda: ["Standard"])
    run_active: bool = False
    wave: int = 0
    zombies_remaining: int = 0
    enemy: Enemy | None = None

    @property
    def level(self) -> int:
        return level_for_xp(self.xp)

    def get_spare(self, ammo_type: str | None = None) -> int:
        ammo_type = ammo_type or self.ammo_name
        return self.spare_ammo.get(ammo_type, 0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Survivor:
        enemy_data = data.get("enemy")
        enemy = Enemy(**enemy_data) if isinstance(enemy_data, dict) else None
        
        # MIGRATION: old save had spare_ammo as int -> convert to dict
        spare = data.get("spare_ammo", {"Standard": 36})
        if isinstance(spare, int):
            spare = {"Standard": spare}
        
        allowed = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        allowed["spare_ammo"] = spare
        allowed["enemy"] = enemy
        allowed.setdefault("painkillers_used_this_run", 0)
        allowed.setdefault("full_restores_used_this_run", 0)
        allowed.setdefault("run_money_earned", 0)
        allowed.setdefault("run_xp_earned", 0)
        allowed.setdefault("owned_ammo", ["Standard"])
        if "stars" not in data:
            allowed["stars"] = max(0, level_for_xp(int(data.get("xp", 0))) - 1)
        return cls(**allowed)

class GameStore:
    def __init__(self) -> None:
        self.players: dict[str, Survivor] = {}
        self.load()
    def get(self, user_id: int) -> Survivor:
        key = str(user_id)
        if key not in self.players:
            self.players[key] = Survivor()
            self.save()
        return self.players[key]
    def save(self) -> None:
        try:
            SAVE_FILE.write_text(json.dumps({k: p.to_dict() for k, p in self.players.items()}, indent=2), encoding="utf-8")
        except OSError:
            pass
    def load(self) -> None:
        if not SAVE_FILE.exists():
            return
        try:
            data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.players = {k: Survivor.from_dict(v) for k, v in data.items() if isinstance(v, dict)}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self.players = {}

def zone_for(player: Survivor) -> dict[str, Any]:
    return ZONES[player.zone_name]

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
    # ensure current ammo has some spare
    if player.get_spare() <= 0:
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + 12
    player.magazine = min(player.magazine_size, player.get_spare())
    # deduct what we loaded from spare
    player.spare_ammo[player.ammo_name] = max(0, player.get_spare() - player.magazine)
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
    damage = enemy.damage // 2 if enemy.effects.get("freeze", 0) else enemy.damage
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
        # return mag to spare on death
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        result.append("💀 **You died!** Rewards saved.")
        result.extend(_grant_random_elemental_drop(player))
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
    player.money += enemy.money_reward
    player.xp += enemy.xp_reward
    player.run_money_earned += enemy.money_reward
    player.run_xp_earned += enemy.xp_reward
    player.zombies_remaining -= 1
    messages = [f"✅ **{enemy.name} defeated!** +${enemy.money_reward} • +{enemy.xp_reward} XP"]
    if player.level > 1 and level_progress(player)[0] == 0:  # just leveled? approximate
        pass
    old_level = player.level - (1 if player.xp - enemy.xp_reward < 0 else 0)  # simplified
    # use proper level check
    if player.stars == 0 and player.xp >= 100:
        pass
    # level up check via xp
    if player.level > level_for_xp(player.xp - enemy.xp_reward):
        ups = player.level - level_for_xp(player.xp - enemy.xp_reward)
        if ups > 0:
            player.stars += ups
            messages.append(f"🎉 **LEVEL UP!** Level {player.level}! +{ups} ⭐")
    if player.zombies_remaining <= 0:
        bonus = int(15 * player.wave * zone_for(player)["money_mult"])
        player.money += bonus
        player.run_money_earned += bonus
        # reward ammo of current type
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
            return [f"❌ Need {cost} {player.ammo_name} ammo! Have {player.magazine}/{player.magazine_size}", f"🔄 Reload (you have {player.get_spare()} spare)"]
        player.magazine -= cost
        mod = ammo_modifier(player, player.ammo_name)
        dmg = int(player.weapon_damage * mod)
        enemy.health = max(0, enemy.health - dmg)
        mod_txt = f" (Zone {int(mod*100)}%)" if mod != 1.0 else ""
        messages.append(f"🔫 Hit **{enemy.name} for {dmg}** using {player.ammo_name} ({cost}/shot){mod_txt}")
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
            return [f"❌ No {player.ammo_name} spare ammo! Buy at shop."]
        amount = min(player.magazine_size - player.magazine, spare)
        player.magazine += amount
        player.spare_ammo[player.ammo_name] = spare - amount
        messages.append(f"🔄 Reloaded {amount} {player.ammo_name}. {player.spare_ammo[player.ammo_name]} spare left.")
    elif action == "flee":
        # return mag to spare
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        player.run_active = False
        player.enemy = None
        player.health = player.max_health
        messages.append(f"🏃 Fled! Kept ${player.run_money_earned} • {player.run_xp_earned} XP this run.")
        messages.extend(_grant_random_elemental_drop(player))
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
        # Buy for currently equipped ammo type
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
    if item == player.weapon_name:
        return ["Already equipped!"]
    if player.money < weapon["price"]:
        return [f"Need ${weapon['price']} for {item}, you have ${player.money}"]
    player.money -= weapon["price"]
    player.weapon_name = item
    player.weapon_damage = weapon["damage"]
    player.magazine_size = weapon["mag"]
    # return old mag to spare
    player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
    player.magazine = 0
    return [f"🔫 Equipped **{item}**. ${player.money} left."]

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
        player.spare_ammo[ammo_name] = player.spare_ammo.get(ammo_name, 0) + 12  # starter ammo
    # Switch ammo: return current mag to its pool
    if player.ammo_name != ammo_name:
        player.spare_ammo[player.ammo_name] = player.spare_ammo.get(player.ammo_name, 0) + player.magazine
        player.magazine = 0
        player.ammo_name = ammo_name
        # auto reload some from new pool
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

def upgrade(player: Survivor, stat: str) -> list[str]:
    if player.run_active:
        return ["Can't upgrade in a run!"]
    if player.stars <= 0:
        return ["No stars! Level up."]
    stat = stat.lower().strip()
    if stat in ("health", "hp", "max_health"):
        player.max_health += 20
        player.health = player.max_health
        player.stars -= 1
        return [f"❤️ Max HP → **{player.max_health}**. Stars: {player.stars}"]
    if stat in ("damage", "weapon", "dmg"):
        player.weapon_damage += 5
        player.stars -= 1
        return [f"💥 Damage → **{player.weapon_damage}**. Stars: {player.stars}"]
    if stat in ("mag", "magazine", "ammo"):
        player.magazine_size += 4
        player.stars -= 1
        return [f"📦 Mag size → **{player.magazine_size}**. Stars: {player.stars}"]
    return [f"Unknown upgrade. Stars: {player.stars}"]


def _grant_random_elemental_drop(player: Survivor) -> list[str]:
    """End-of-run drop: 1 single elemental bullet + 1-10 normal bullets, only if you own an elemental type"""
    elemental_owned = [a for a in player.owned_ammo if a != "Standard"]
    if not elemental_owned:
        return []  # No elemental unlocked = no drop
    
    chosen = random.choice(elemental_owned)
    normal_amount = random.randint(1, 10)
    
    # Give 1 of the elemental + 1-10 standard
    player.spare_ammo[chosen] = player.spare_ammo.get(chosen, 0) + 1
    player.spare_ammo["Standard"] = player.spare_ammo.get("Standard", 0) + normal_amount
    
    return [f"🎁 **Scavenged!** +1x **{chosen}** bullet + {normal_amount}x Standard bullets found!"]


def status(player: Survivor) -> str:
    earned, needed = level_progress(player)
    pain_left = MAX_PAINKILLERS_PER_RUN - player.painkillers_used_this_run
    full_left = MAX_FULL_RESTORES_PER_RUN - player.full_restores_used_this_run
    cost = AMMO[player.ammo_name]["cost_per_attack"]
    spare = player.get_spare()
    lines = [
        f"**🧟 {player.zone_name} | Lvl {player.level}** {earned}/{needed} XP | ⭐ {player.stars} | 💰 ${player.money}",
        f"❤️ {player.health}/{player.max_health} | 🔫 {player.weapon_name} ({player.weapon_damage} dmg) {player.magazine}/{player.magazine_size}+{spare} [{player.ammo_name} {cost}/shot]",
    ]
    if player.run_active and player.enemy:
        lines.append(f"⚔️ Wave {player.wave} • {player.zombies_remaining} left • Fighting {player.enemy.name} {player.enemy.health}/{player.enemy.max_health} HP • 💵 Run: ${player.run_money_earned} | ✨ {player.run_xp_earned} XP")
    else:
        # show all ammo pools
        pool_text = " | ".join([f"{k}: {v}" for k, v in player.spare_ammo.items() if v > 0])
        lines.append(f"💊 {player.painkillers} painkillers ({pain_left} left) • ✨ {player.full_restores} restores ({full_left} left)")
        lines.append(f"🎒 Ammo pools: {pool_text or 'Empty'} | Owned: {', '.join(player.owned_ammo)}")
    return "\n".join(lines)

def get_status(player: Survivor) -> str:
    return status(player)
