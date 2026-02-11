"""
Artillery combat resolution - tube and rocket artillery.

Handles:
- Preparatory bombardment
- Counter-battery fire
- Fire support missions
- Rocket artillery (MLRS)
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import CombatResolver, CombatReport, CombatResult


@dataclass
class FireMission:
    """An artillery fire mission."""
    battery_id: str
    target_id: str
    target_type: str  # "ground_unit", "fortification", "assembly_area", "logistics"
    target_location: tuple[int, int]
    rounds: int
    mission_type: str  # "bombardment", "suppression", "counter_battery", "smoke"


@dataclass
class ArtilleryEffect:
    """Effect of artillery fire."""
    casualties: int
    equipment_destroyed: int
    suppression: float
    fortification_damage: float
    area_denial_turns: int = 0  # For sustained fire/mines


class ArtilleryCombat(CombatResolver):
    """Resolves artillery fire missions."""

    # Artillery system characteristics
    ARTILLERY_STATS = {
        # Tube artillery
        "m777": {"range_km": 30, "accuracy": 75, "rate": 5, "damage": 60, "type": "tube"},
        "dhanush": {"range_km": 38, "accuracy": 70, "damage": 65, "type": "tube"},
        "k9_vajra": {"range_km": 40, "accuracy": 75, "damage": 70, "type": "sp"},
        "m109": {"range_km": 30, "accuracy": 70, "damage": 60, "type": "sp"},
        "sh15": {"range_km": 53, "accuracy": 72, "damage": 65, "type": "sp"},

        # Rocket artillery (MLRS)
        "pinaka": {"range_km": 75, "accuracy": 65, "damage": 85, "type": "mlrs", "salvo": 12},
        "smerch": {"range_km": 90, "accuracy": 60, "damage": 90, "type": "mlrs", "salvo": 12},
        "a100": {"range_km": 100, "accuracy": 60, "damage": 88, "type": "mlrs", "salvo": 10},
    }

    # Target vulnerability
    TARGET_VULNERABILITY = {
        "infantry_in_open": 1.5,
        "infantry_dug_in": 0.6,
        "mechanized": 0.8,
        "armor": 0.4,
        "artillery": 1.2,  # Counter-battery
        "logistics": 1.3,
        "fortification": 0.5,
        "airbase": 0.7,
    }

    def resolve_fire_mission(
        self,
        mission: FireMission,
        battery_stats: dict,
        target_unit,
        terrain_concealment: float,
        counter_battery_active: bool = False,
        weather_modifier: float = 1.0,
    ) -> tuple[CombatReport, ArtilleryEffect]:
        """Resolve an artillery fire mission."""

        # Get artillery characteristics
        arty_type = battery_stats.get("type", "tube").lower()
        arty_stats = self.ARTILLERY_STATS.get(arty_type, {
            "accuracy": 65, "damage": 60, "type": "tube"
        })

        accuracy = battery_stats.get("accuracy", arty_stats.get("accuracy", 65))
        damage = battery_stats.get("damage", arty_stats.get("damage", 60))
        is_mlrs = arty_stats.get("type") == "mlrs"

        # Concealment reduces effectiveness
        concealment_mod = 1.0 - (terrain_concealment / 200.0)

        # Weather effects
        accuracy *= weather_modifier

        # Target vulnerability
        target_type = self._classify_target(target_unit)
        vulnerability = self.TARGET_VULNERABILITY.get(target_type, 1.0)

        # Calculate hits
        if is_mlrs:
            # MLRS fires salvos, area effect
            salvo_size = arty_stats.get("salvo", 12)
            effective_rounds = mission.rounds * salvo_size * 0.3  # Area coverage
        else:
            effective_rounds = mission.rounds

        hits = 0
        for _ in range(int(effective_rounds)):
            hit_chance = (accuracy / 100.0) * concealment_mod
            if self.hit_check(hit_chance):
                hits += 1

        # Calculate damage
        base_damage = hits * damage * vulnerability

        # Casualties (against personnel)
        if target_unit:
            strength = target_unit.state.strength_current
            casualty_rate = (base_damage / 1000.0) * self.roll(1.0, 0.3)
            casualties = int(strength * casualty_rate)
        else:
            casualties = 0

        # Suppression effect (temporary combat penalty)
        suppression = min(80, base_damage * 0.5)

        # Equipment destruction (for mechanized/armor)
        equipment_destroyed = 0
        if target_type in ("mechanized", "armor"):
            equip_hits = int(hits * 0.1 * vulnerability)
            equipment_destroyed = equip_hits

        # Fortification damage
        fort_damage = 0.0
        if mission.mission_type == "bombardment" and target_type == "fortification":
            fort_damage = base_damage * 0.3

        effect = ArtilleryEffect(
            casualties=casualties,
            equipment_destroyed=equipment_destroyed,
            suppression=suppression,
            fortification_damage=fort_damage,
        )

        # Determine result
        effectiveness = base_damage / 100.0
        if effectiveness >= 1.5:
            result = CombatResult.DECISIVE_VICTORY
        elif effectiveness >= 1.0:
            result = CombatResult.VICTORY
        elif effectiveness >= 0.5:
            result = CombatResult.MARGINAL
        elif hits > 0:
            result = CombatResult.STALEMATE
        else:
            result = CombatResult.DEFEAT

        report = CombatReport(
            attacker_id=mission.battery_id,
            defender_id=mission.target_id,
            turn=0,
            phase="artillery",
            result=result,
            attacker_losses={"rounds_expended": mission.rounds},
            defender_losses={
                "casualties": casualties,
                "equipment": equipment_destroyed,
            },
            defender_damage=base_damage,
            location=mission.target_location,
            notes=[
                f"Rounds fired: {mission.rounds}, Hits: {hits}",
                f"Casualties: {casualties}, Suppression: {suppression:.0f}%",
                f"Target type: {target_type}",
            ]
        )

        return report, effect

    def _classify_target(self, target_unit) -> str:
        """Classify target for vulnerability calculation."""
        if target_unit is None:
            return "fortification"

        unit_type = target_unit.unit_type.lower()

        if "armor" in unit_type or "tank" in unit_type:
            return "armor"
        elif "mech" in unit_type:
            return "mechanized"
        elif "artillery" in unit_type:
            return "artillery"
        elif target_unit.state.dug_in >= 2:
            return "infantry_dug_in"
        else:
            return "infantry_in_open"

    def resolve_counter_battery(
        self,
        firing_battery_id: str,
        target_battery,
        counter_battery_radar: bool,
        response_time_minutes: int,
    ) -> tuple[CombatReport, ArtilleryEffect]:
        """Resolve counter-battery fire."""

        # Counter-battery effectiveness depends on:
        # 1. Radar detection (weapon-locating radar)
        # 2. Response time
        # 3. Target mobility

        base_effectiveness = 0.3  # 30% base chance to hit

        if counter_battery_radar:
            base_effectiveness += 0.3

        # Response time penalty (enemy may move)
        if response_time_minutes > 10:
            base_effectiveness *= 0.5
        elif response_time_minutes > 5:
            base_effectiveness *= 0.7

        # Mobile artillery harder to hit
        is_mobile = target_battery.type_data.get("mobile", False)
        if is_mobile:
            base_effectiveness *= 0.6

        # Simulate counter-battery strike
        mission = FireMission(
            battery_id=firing_battery_id,
            target_id=target_battery.id,
            target_type="artillery",
            target_location=(0, 0),
            rounds=24,  # Standard counter-battery mission
            mission_type="counter_battery",
        )

        # Override accuracy with counter-battery effectiveness
        battery_stats = {"accuracy": base_effectiveness * 100, "damage": 70}

        return self.resolve_fire_mission(
            mission, battery_stats, target_battery,
            terrain_concealment=30,  # Artillery typically has some concealment
        )

    def calculate_suppression_zone(
        self,
        battery_count: int,
        artillery_type: str,
        duration_turns: int,
    ) -> dict:
        """Calculate area denial/suppression zone."""

        stats = self.ARTILLERY_STATS.get(artillery_type.lower(), {})
        is_mlrs = stats.get("type") == "mlrs"

        if is_mlrs:
            # MLRS creates larger suppression zones
            radius_hexes = 2
            suppression_level = 60
        else:
            radius_hexes = 1
            suppression_level = 40

        suppression_level *= min(2.0, battery_count / 4.0)

        return {
            "radius_hexes": radius_hexes,
            "suppression_level": min(80, suppression_level),
            "duration_turns": duration_turns,
            "movement_penalty": 0.5,  # 50% movement in zone
        }

    def apply_effects(self, target_unit, effect: ArtilleryEffect):
        """Apply artillery effects to target unit."""
        if target_unit:
            target_unit.take_losses(effect.casualties, 0)
            target_unit.apply_suppression(effect.suppression)
