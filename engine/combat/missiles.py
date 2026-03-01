"""
Missile combat resolution - cruise and ballistic missiles.

Handles:
- Cruise missile strikes (BrahMos, Babur, etc.)
- Ballistic missile strikes (Prithvi, Shaheen, etc.)
- Air defense interception
"""

from dataclasses import dataclass
from typing import Optional
from .base import CombatResolver, CombatReport, CombatResult


@dataclass
class MissileStrike:
    """A planned missile strike."""
    battery_id: str
    target_id: str
    target_type: str  # "airbase", "sam_site", "ground_unit", "infrastructure"
    missiles_fired: int
    missile_type: str


@dataclass
class InterceptionResult:
    """Result of air defense interception attempt."""
    missiles_incoming: int
    missiles_intercepted: int
    missiles_leaked: int
    interceptor_rounds_used: int


class MissileCombat(CombatResolver):
    """Resolves missile strikes and air defense."""

    # Missile type characteristics
    MISSILE_STATS = {
        # Cruise missiles
        "brahmos": {"accuracy": 90, "damage": 95, "speed": "supersonic", "detectability": 60},
        "nirbhay": {"accuracy": 85, "damage": 80, "speed": "subsonic", "detectability": 40},
        "babur": {"accuracy": 85, "damage": 75, "speed": "subsonic", "detectability": 35},
        "raad": {"accuracy": 80, "damage": 70, "speed": "subsonic", "detectability": 30},
        # Ballistic missiles
        "prithvi": {"accuracy": 70, "damage": 90, "speed": "ballistic", "detectability": 80},
        "pralay": {"accuracy": 85, "damage": 85, "speed": "quasi_ballistic", "detectability": 70},
        "shaheen": {"accuracy": 75, "damage": 90, "speed": "ballistic", "detectability": 85},
        "ghaznavi": {"accuracy": 70, "damage": 85, "speed": "ballistic", "detectability": 80},
    }

    # Air defense effectiveness vs missile types
    SAM_EFFECTIVENESS = {
        # System: {missile_speed: intercept_chance}
        # Supersonic (Mach 2.8+ BrahMos): near-impossible for anything except S-400 (theoretical)
        # No system has proven combat intercept of Mach 2.8 sea-skimming cruise missiles
        # Quasi-ballistic (Pralay): faster than cruise but predictable trajectory
        # Ballistic (Prithvi/Shaheen): high speed but ballistic arc, needs dedicated BMD

        # INDIA — S-400 is the only system with theoretical supersonic intercept
        "s400": {"subsonic": 0.95, "supersonic": 0.35, "quasi_ballistic": 0.45, "ballistic": 0.40},
        "barak8": {"subsonic": 0.88, "supersonic": 0.10, "quasi_ballistic": 0.30, "ballistic": 0.25},
        "mrsam": {"subsonic": 0.88, "supersonic": 0.10, "quasi_ballistic": 0.30, "ballistic": 0.25},
        "akash": {"subsonic": 0.75, "supersonic": 0.03, "quasi_ballistic": 0.12, "ballistic": 0.05},
        "spyder": {"subsonic": 0.80, "supersonic": 0.03, "quasi_ballistic": 0.08, "ballistic": 0.03},

        # PAKISTAN — Chinese systems, zero capability against Mach 2.8 supersonic cruise missiles
        "hq9": {"subsonic": 0.80, "supersonic": 0.0, "quasi_ballistic": 0.20, "ballistic": 0.15},
        "hq16": {"subsonic": 0.70, "supersonic": 0.0, "quasi_ballistic": 0.08, "ballistic": 0.05},
        "spada2000": {"subsonic": 0.65, "supersonic": 0.0, "quasi_ballistic": 0.03, "ballistic": 0.01},
        "fm90": {"subsonic": 0.55, "supersonic": 0.0, "quasi_ballistic": 0.01, "ballistic": 0.01},
    }

    # Target hardness (damage required to destroy)
    TARGET_HARDNESS = {
        "airbase_runway": 80,
        "airbase_hangar": 60,
        "hardened_shelter": 150,
        "sam_site": 50,
        "radar": 30,
        "fuel_depot": 40,
        "ammo_depot": 35,
        "command_post": 70,
        "ground_unit": 40,
        "bridge": 100,
    }

    def resolve_strike(
        self,
        strike: MissileStrike,
        defending_sams: list,
        target_hardness: float,
        weather_modifier: float = 1.0,
        ew_modifier: float = 1.0,  # Electronic warfare effects
    ) -> CombatReport:
        """Resolve a missile strike including air defense."""

        missile_stats = self.MISSILE_STATS.get(
            strike.missile_type.lower(),
            {"accuracy": 75, "damage": 70, "speed": "subsonic", "detectability": 50}
        )

        # Phase 1: Air defense interception
        interception = self._resolve_interception(
            strike.missiles_fired,
            missile_stats,
            defending_sams,
            ew_modifier
        )

        missiles_through = interception.missiles_leaked

        # Phase 2: Strike damage
        hits = 0
        total_damage = 0.0

        for _ in range(missiles_through):
            hit_chance = (missile_stats["accuracy"] / 100.0) * weather_modifier
            if self.hit_check(hit_chance):
                hits += 1
                damage = self.roll(missile_stats["damage"], variance=0.15)
                total_damage += damage

        # Damage vs hardness
        destruction_threshold = target_hardness
        damage_ratio = total_damage / max(1, destruction_threshold)

        # Determine result
        if damage_ratio >= 1.5:
            result = CombatResult.DECISIVE_VICTORY
        elif damage_ratio >= 1.0:
            result = CombatResult.VICTORY
        elif damage_ratio >= 0.5:
            result = CombatResult.MARGINAL
        elif hits > 0:
            result = CombatResult.STALEMATE
        else:
            result = CombatResult.DEFEAT

        report = CombatReport(
            attacker_id=strike.battery_id,
            defender_id=strike.target_id,
            turn=0,  # Set by caller
            phase="missiles",
            result=result,
            attacker_losses={"missiles_fired": strike.missiles_fired},
            defender_losses={
                "missiles_intercepted": interception.missiles_intercepted,
                "damage_taken": total_damage,
            },
            attacker_damage=0,
            defender_damage=total_damage,
            notes=[
                f"Fired {strike.missiles_fired} {strike.missile_type}",
                f"Intercepted {interception.missiles_intercepted}, {missiles_through} leaked",
                f"Hits: {hits}, Total damage: {total_damage:.1f}",
            ]
        )

        return report

    def _resolve_interception(
        self,
        missiles_incoming: int,
        missile_stats: dict,
        defending_sams: list,
        ew_modifier: float
    ) -> InterceptionResult:
        """Resolve air defense interception of incoming missiles."""

        missiles_remaining = missiles_incoming
        total_intercepted = 0
        total_rounds_used = 0

        missile_speed = missile_stats.get("speed", "subsonic")
        detectability = missile_stats.get("detectability", 50) / 100.0

        for sam in defending_sams:
            if missiles_remaining <= 0:
                break

            sam_type = sam.get("type", "").lower()
            sam_rounds = sam.get("rounds", 10)
            sam_ready = sam.get("ready", True)

            if not sam_ready or sam_rounds <= 0:
                continue

            effectiveness = self.SAM_EFFECTIVENESS.get(sam_type, {})
            base_intercept = effectiveness.get(missile_speed, 0.5)

            # Detection modifier
            detect_chance = min(1.0, detectability * 1.5)

            # EW degradation
            effective_intercept = base_intercept * ew_modifier * detect_chance

            # Attempt interceptions
            rounds_to_use = min(sam_rounds, missiles_remaining * 2)  # 2 rounds per missile
            total_rounds_used += rounds_to_use

            for _ in range(missiles_remaining):
                if rounds_to_use < 2:
                    break
                rounds_to_use -= 2

                if self.hit_check(effective_intercept):
                    total_intercepted += 1
                    missiles_remaining -= 1

        return InterceptionResult(
            missiles_incoming=missiles_incoming,
            missiles_intercepted=total_intercepted,
            missiles_leaked=missiles_remaining,
            interceptor_rounds_used=total_rounds_used
        )

    def calculate_airbase_damage(
        self,
        damage: float,
        airbase
    ) -> dict:
        """Calculate specific damage to airbase components."""
        damage_distribution = {
            "runway": 0.4,
            "fuel": 0.2,
            "ammo": 0.15,
            "shelters": 0.15,
            "maintenance": 0.1,
        }

        results = {}
        for component, fraction in damage_distribution.items():
            component_damage = damage * fraction * self.roll(1.0, 0.3)
            results[component] = component_damage

        return results

    def apply_airbase_damage(self, airbase, damage_dict: dict):
        """Apply damage to airbase components."""
        if "runway" in damage_dict:
            airbase.runway_status = max(0, airbase.runway_status - damage_dict["runway"])
        if "fuel" in damage_dict:
            airbase.fuel_storage = max(0, airbase.fuel_storage - damage_dict["fuel"] * 0.5)
        if "ammo" in damage_dict:
            airbase.ammo_storage = max(0, airbase.ammo_storage - damage_dict["ammo"] * 0.5)
