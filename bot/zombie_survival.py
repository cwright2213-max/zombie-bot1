"""Turn-based Discord adaptation of the attached zombie survival game."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SAVE_FILE = Path("zombie_saves.json")

ZONES: dict[str, dict[str, Any]] = {
    "Graveyard": {
        "min_level": 1,
        "max_level": 49,
        "hp_mult": 1.0,
        "dmg_mult": 1.0,
        "money_mult": 1.0,
        "xp_mult": 1.0,
        "desc": "Foggy, quiet, and good for learning.",
        "weights": [60, 25, 12, 3],
    },
    "Mega Death City": {
        "min_level": 50,
        "max_level": 99,
        "hp_mult": 2.2,
        "dmg_mult": 1.4,
        "money_mult": 2.5,
        "xp_mult": 2.0,
        "desc": "A concrete jungle with tougher, richer zombies.",
        "weights": [30, 30, 25, 15],
    },
    "Frostbitten Outskirts": {
        "min_level": 100,
        "max_level": 149,
        "hp_mult": 3.8,
        "dmg_mult": 1.8,
        "money_mult": 4.0,
        "xp_mult": 3.5,
        "desc": "Freezing rain and frost armor.",
        "weights": [20, 20, 35, 25],
    },
    "Toxic Wasteland": {
        "min_level": 150,
        "max_level": 199,
        "hp_mult": 6.0,
        "dmg_mult": 2.3,
        "money_mult": 6.5,
        "xp_mult": 5.5,
        "desc": "A green haze where toxic rounds shine.",
        "weights": [15, 15, 35, 35],
    },
    "The Void": {
        "min_level": 200,
        "max_level": 9999,
        "hp_mult": 10.0,
        "dmg_mult": 3.0,
        "money_mult": 10.0,
        "xp_mult": 8.0,
        "desc": "Endgame. Everything wants you dead.",
        "weights": [10, 10, 30, 50],
    },
}

AMMO: dict[str, dict[str, Any]] = {
    "Standard": {"unlock_level": 1, "price": 0, "desc": "Reliable regular lead.", "effect": None},
    "Bleed": {"unlock_level": 10, "price": 200, "desc": "25% chance to deal 8 damage for 3 turns.", "effect": "bleed"},
    "Incendiary": {"unlock_level": 35, "price": 600, "desc": "30% chance to burn for 12 damage twice.", "effect": "burn"},
    "Frostbite": {"unlock_level": 70, "price": 1200, "desc": "20% chance to halve zombie damage for 3 turns.", "effect": "freeze"},
    "Toxic": {"unlock_level": 110, "price": 2500, "desc": "35% chance to poison for 10 damage four times.", "effect": "poison"},
    "Shock": {"unlock_level": 160, "price": 5000, "desc": "15% chance to stun the zombie for one turn.", "effect": "shock"},
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
    weapon_name: str = "Pistol"
    weapon_damage: int = 20
    magazine_size: int = 12
    magazine: int = 12
    spare_ammo: int = 36
    full_restores: int = 1
    painkillers: int = 3
    zone_name: str = "Graveyard"
    ammo_name: str = "Standard"
    owned_ammo: list[str] = field(default_factory=lambda: ["Standard"])
    run_active: bool = False
    wave: int = 0
    zombies_remaining: int = 0
    enemy: Enemy | None = None

    @property
    def level(self) -> int:
        return self.xp // 100 + 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Survivor:
        enemy_data = data.get("enemy")
        enemy = Enemy(**enemy_data) if isinstance(enemy_data, dict) else None
        allowed = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        allowed["enemy"] = enemy
        return cls(**allowed)


class GameStore:
    """In-memory player sessions backed by a small JSON save file."""

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
            SAVE_FILE.write_text(
                json.dumps({key: player.to_dict() for key, player in self.players.items()}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # The bot should keep the current in-memory game running if disk
            # persistence is temporarily unavailable.
            pass

    def load(self) -> None:
        if not SAVE_FILE.exists():
            return
        try:
            data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.players = {
                    key: Survivor.from_dict(value)
                    for key, value in data.items()
                    if isinstance(value, dict)
                }
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self.players = {}


def zone_for(player: Survivor) -> dict[str, Any]:
    return ZONES[player.zone_name]


def spawn_enemy(player: Survivor) -> Enemy:
    zone = zone_for(player)
    name = random.choices(list(ZOMBIES), weights=zone["weights"])[0]
    base = ZOMBIES[name]
    health = int((base["health"] + (player.wave - 1) * 6) * zone["hp_mult"])
    damage = int((base["damage"] + (player.wave - 1) // 2) * zone["dmg_mult"])
    return Enemy(
        name=name,
        health=health,
        max_health=health,
        damage=damage,
        money_reward=int(base["money"] * zone["money_mult"]),
        xp_reward=int(base["xp"] * zone["xp_mult"]),
    )


def start_run(player: Survivor) -> list[str]:
    if player.run_active:
        return ["You are already in a run. Use `/zombie status` to see the current fight."]
    player.health = player.max_health
    player.magazine = player.magazine_size
    player.spare_ammo = max(player.spare_ammo, 36)
    player.wave = 1
    player.zombies_remaining = 3
    player.run_active = True
    player.enemy = spawn_enemy(player)
    return [
        f"Run started in **{player.zone_name}**.",
        f"Wave {player.wave}: **{player.enemy.name}** appears with {player.enemy.health} HP.",
        action_help(player),
    ]


def action_help(player: Survivor) -> str:
    enemy = player.enemy
    if enemy is None:
        return "Use `/zombie action` to choose your next move."
    return (
        f"**{player.health}/{player.max_health} HP** | "
        f"**{player.magazine}/{player.magazine_size}** ammo, {player.spare_ammo} spare | "
        f"**{enemy.name} {enemy.health}/{enemy.max_health} HP**. "
        "Choose `attack`, `reload`, `heal`, or `flee`."
    )


def _enemy_damage(player: Survivor) -> list[str]:
    enemy = player.enemy
    if enemy is None:
        return []
    if enemy.effects.pop("shock", 0):
        return [f"The {enemy.name} is stunned and misses its attack."]
    damage = enemy.damage // 2 if enemy.effects.get("freeze", 0) else enemy.damage
    player.health = max(0, player.health - damage)
    if enemy.effects.get("freeze", 0):
        enemy.effects["freeze"] -= 1
        if enemy.effects["freeze"] <= 0:
            del enemy.effects["freeze"]
        result = [f"Frozen armor halves the hit. The {enemy.name} deals {damage} damage."]
    else:
        result = [f"The {enemy.name} attacks for {damage} damage."]
    if player.health == 0:
        player.run_active = False
        player.enemy = None
        result.append("You died. Your rewards from defeated zombies were saved.")
    return result


def _apply_damage_over_time(player: Survivor) -> list[str]:
    enemy = player.enemy
    if enemy is None:
        return []
    messages: list[str] = []
    for effect in list(enemy.effects):
        if effect in {"bleed", "burn", "poison"}:
            damage = {"bleed": 8, "burn": 18 if player.zone_name == "Frostbitten Outskirts" else 12, "poison": 10}[effect]
            enemy.health = max(0, enemy.health - damage)
            enemy.effects[effect] -= 1
            messages.append(f"{effect.title()} deals {damage} damage.")
            if enemy.effects[effect] <= 0:
                del enemy.effects[effect]
    return messages


def _finish_enemy(player: Survivor) -> list[str]:
    enemy = player.enemy
    if enemy is None or enemy.health > 0:
        return []
    player.money += enemy.money_reward
    player.xp += enemy.xp_reward
    player.zombies_remaining -= 1
    messages = [
        f"**{enemy.name} defeated.** +${enemy.money_reward}, +{enemy.xp_reward} XP.",
    ]
    if player.zombies_remaining <= 0:
        bonus = int(15 * player.wave * zone_for(player)["money_mult"])
        player.money += bonus
        player.spare_ammo += 10
        player.wave += 1
        player.zombies_remaining = player.wave + 2
        player.health = min(player.max_health, player.health + 5)
        messages.append(
            f"**Wave cleared.** +${bonus}, +10 ammo. Wave {player.wave} begins with "
            f"{player.zombies_remaining} zombies."
        )
    player.enemy = spawn_enemy(player)
    messages.append(f"A **{player.enemy.name}** appears with {player.enemy.health} HP.")
    return messages


def take_action(player: Survivor, action: str, heal_item: str | None = None) -> list[str]:
    if not player.run_active or player.enemy is None:
        return ["You are not in a run. Start one with `/zombie start`."]

    messages = _apply_damage_over_time(player)
    if player.enemy is None or player.enemy.health <= 0:
        messages.extend(_finish_enemy(player))
        return messages

    enemy = player.enemy
    if action == "attack":
        if player.magazine <= 0:
            return ["Your magazine is empty. Choose `reload`."]
        player.magazine -= 1
        enemy.health = max(0, enemy.health - player.weapon_damage)
        messages.append(f"You hit the {enemy.name} for {player.weapon_damage} damage.")
        ammo_data = AMMO[player.ammo_name]
        effect = ammo_data["effect"]
        chances = {"bleed": 0.25, "burn": 0.30, "freeze": 0.20, "poison": 0.35, "shock": 0.15}
        if effect and random.random() < chances[effect]:
            durations = {"bleed": 3, "burn": 2, "freeze": 3, "poison": 4, "shock": 1}
            enemy.effects[effect] = durations[effect]
            messages.append(f"{player.ammo_name} procs **{effect}**.")
    elif action == "reload":
        if player.magazine == player.magazine_size:
            return ["Your magazine is already full."]
        if player.spare_ammo <= 0:
            return ["You have no spare ammo."]
        amount = min(player.magazine_size - player.magazine, player.spare_ammo)
        player.magazine += amount
        player.spare_ammo -= amount
        messages.append(f"You reload {amount} round(s).")
    elif action == "heal":
        if heal_item == "full_restore" and player.full_restores > 0 and player.health < player.max_health:
            player.health = player.max_health
            player.full_restores -= 1
            messages.append("You use a full restore.")
        elif heal_item == "painkillers" and player.painkillers > 0 and player.health < player.max_health:
            amount = max(1, player.max_health // 4)
            player.health = min(player.max_health, player.health + amount)
            player.painkillers -= 1
            messages.append(f"You use painkillers and recover {amount} HP.")
        else:
            return ["Choose an available healing item and make sure you are not at full health."]
    elif action == "flee":
        player.run_active = False
        player.enemy = None
        messages.append("You flee the run. Your saved rewards are safe.")
        return messages
    else:
        return ["Choose `attack`, `reload`, `heal`, or `flee`."]

    if enemy.health <= 0:
        messages.extend(_finish_enemy(player))
    else:
        messages.extend(_enemy_damage(player))
    return messages


def buy_item(player: Survivor, item: str) -> list[str]:
    if player.run_active:
        return ["You cannot shop during a run."]
    if item == "ammo":
        price = 30
        if player.money < price:
            return ["You need $30 for an ammo box."]
        player.money -= price
        player.spare_ammo += 24
        return ["Bought an ammo box: +24 spare ammo."]
    if item == "painkillers":
        price = 40
        if player.money < price:
            return ["You need $40 for painkillers."]
        player.money -= price
        player.painkillers += 2
        return ["Bought painkillers: +2."]
    if item == "full_restore":
        price = 120
        if player.money < price:
            return ["You need $120 for a full restore."]
        player.money -= price
        player.full_restores += 1
        return ["Bought a full restore: +1."]
    if item not in WEAPONS:
        return ["That shop item does not exist."]
    weapon = WEAPONS[item]
    if player.level < weapon["unlock_level"]:
        return [f"{item} unlocks at level {weapon['unlock_level']}."]
    if item == player.weapon_name:
        return ["That weapon is already equipped."]
    if player.money < weapon["price"]:
        return [f"You need ${weapon['price']} for the {item}."]
    player.money -= weapon["price"]
    player.weapon_name = item
    player.weapon_damage = weapon["damage"]
    player.magazine_size = weapon["mag"]
    player.magazine = player.magazine_size
    return [f"Equipped the **{item}**."]


def equip_ammo(player: Survivor, ammo_name: str) -> list[str]:
    if ammo_name not in AMMO:
        return ["That ammo type does not exist."]
    if ammo_name in player.owned_ammo:
        player.ammo_name = ammo_name
        return [f"Equipped **{ammo_name}** ammo."]
    ammo = AMMO[ammo_name]
    if player.level < ammo["unlock_level"]:
        return [f"{ammo_name} unlocks at level {ammo['unlock_level']}."]
    if player.money < ammo["price"]:
        return [f"You need ${ammo['price']} for {ammo_name} ammo."]
    player.money -= ammo["price"]
    player.owned_ammo.append(ammo_name)
    player.ammo_name = ammo_name
    return [f"Bought and equipped **{ammo_name}** ammo."]


def change_zone(player: Survivor, zone_name: str) -> list[str]:
    if player.run_active:
        return ["You cannot change zones during a run."]
    if zone_name not in ZONES:
        return ["That zone does not exist."]
    if player.level < ZONES[zone_name]["min_level"]:
        return [f"{zone_name} unlocks at level {ZONES[zone_name]['min_level']}."]
    player.zone_name = zone_name
    return [f"Travelled to **{zone_name}**."]


def upgrade(player: Survivor, stat: str) -> list[str]:
    if player.run_active:
        return ["You cannot upgrade during a run."]
    costs = {"health": 80, "damage": 100, "magazine": 70}
    if stat not in costs:
        return ["Choose `health`, `damage`, or `magazine`."]
    if player.xp < costs[stat]:
        return [f"You need {costs[stat]} XP."]
    player.xp -= costs[stat]
    if stat == "health":
        player.max_health += 20
        return ["Max health increased by 20."]
    if stat == "damage":
        player.weapon_damage += 5
        return ["Weapon damage increased by 5."]
    player.magazine_size += 3
    player.magazine = player.magazine_size
    return ["Magazine size increased by 3."]


def status(player: Survivor) -> str:
    run = "Active" if player.run_active else "Idle"
    result = (
        f"**Level {player.level} Survivor — {run}**\n"
        f"Zone: **{player.zone_name}** — {zone_for(player)['desc']}\n"
        f"Health: {player.health}/{player.max_health} | Money: ${player.money} | XP: {player.xp}\n"
        f"Weapon: {player.weapon_name} ({player.weapon_damage} damage) | "
        f"Ammo: {player.magazine}/{player.magazine_size} + {player.spare_ammo} spare\n"
        f"Ammo type: {player.ammo_name} | Painkillers: {player.painkillers} | "
        f"Full restores: {player.full_restores}"
    )
    if player.run_active and player.enemy:
        result += (
            f"\nWave {player.wave}, zombies remaining: {player.zombies_remaining}\n"
            f"Enemy: **{player.enemy.name} {player.enemy.health}/{player.enemy.max_health} HP**"
        )
    return result