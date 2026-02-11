"""
Ground combat resolution - land warfare between ground forces.

Handles:
- Offensive operations (assault, breakthrough)
- Defensive operations (defend, delay, counterattack)
- Urban warfare
- River crossings
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import CombatResolver, CombatReport, CombatResult


@dataclass
class GroundEngagement:
    """A ground combat engagement."""
    attacker_id: str
    defender_id: str
    location: tuple[int, int]
    attacker_posture: str  # "assault", "probe", "exploitation"
    defender_posture: str  # "defend", "delay", "counterattack"
    terrain: str
    terrain_defense_mod: float = 1.0
    river_crossing: bool = False
    urban: bool = False


@dataclass
class GroundCombatResult:
    """Detailed result of ground combat."""
    attacker_casualties: int
    defender_casualties: int
    attacker_org_loss: float
    defender_org_loss: float
    attacker_equipment_lost: dict = field(default_factory=dict)
    defender_equipment_lost: dict = field(default_factory=dict)
    ground_gained_hexes: int = 0
    defender_retreated: bool = False


class GroundCombat(CombatResolver):
    """Resolves ground combat engagements."""

    # Terrain defense modifiers
    TERRAIN_DEFENSE = {
        "plains": 1.0,
        "hills": 1.4,
        "mountain": 2.5,
        "forest": 1.5,
        "urban": 2.0,
        "desert": 0.9,
        "marsh": 1.2,
    }

    # Posture modifiers
    POSTURE_ATTACK = {
        "assault": 1.2,
        "probe": 0.8,
        "exploitation": 1.0,
    }

    POSTURE_DEFENSE = {
        "defend": 1.5,
        "delay": 1.2,
        "counterattack": 0.9,
    }

    # Unit type effectiveness
    TYPE_VS_TYPE = {
        # Attacker vs Defender
        ("armor", "armor"): 1.0,
        ("armor", "infantry"): 1.4,
        ("armor", "mechanized"): 1.2,
        ("mechanized", "armor"): 0.8,
        ("mechanized", "infantry"): 1.2,
        ("mechanized", "mechanized"): 1.0,
        ("infantry", "armor"): 0.5,
        ("infantry", "infantry"): 1.0,
        ("infantry", "mechanized"): 0.7,
        ("mountain", "infantry"): 1.3,  # Mountain troops in their element
    }

    def resolve_engagement(
        self,
        engagement: GroundEngagement,
        attacker_unit,
        defender_unit,
        attacker_support: dict = None,  # Artillery, air support
        defender_support: dict = None,
        weather_modifier: float = 1.0,
    ) -> tuple[CombatReport, GroundCombatResult]:
        """Resolve a ground combat engagement."""

        attacker_support = attacker_support or {}
        defender_support = defender_support or {}

        # Calculate base combat powers
        attacker_power = attacker_unit.get_combat_power(attack=True)
        defender_power = defender_unit.get_combat_power(attack=False)

        # Apply terrain
        terrain_mod = self.TERRAIN_DEFENSE.get(engagement.terrain, 1.0)
        if engagement.urban:
            terrain_mod = max(terrain_mod, 2.0)
        if engagement.river_crossing:
            terrain_mod *= 1.5  # Major penalty for crossing

        defender_power *= terrain_mod

        # Apply fortifications (from unit dug_in level)
        fort_bonus = 1.0 + (defender_unit.state.dug_in * 0.15)
        defender_power *= fort_bonus

        # Apply posture modifiers
        attack_mod = self.POSTURE_ATTACK.get(engagement.attacker_posture, 1.0)
        defense_mod = self.POSTURE_DEFENSE.get(engagement.defender_posture, 1.0)

        attacker_power *= attack_mod
        defender_power *= defense_mod

        # Unit type matchup
        attacker_type = self._get_unit_category(attacker_unit)
        defender_type = self._get_unit_category(defender_unit)
        type_mod = self.TYPE_VS_TYPE.get((attacker_type, defender_type), 1.0)
        attacker_power *= type_mod

        # Support bonuses
        if attacker_support.get("artillery_support"):
            attacker_power *= 1.15
        if attacker_support.get("air_support"):
            attacker_power *= 1.10
        if defender_support.get("artillery_support"):
            defender_power *= 1.10

        # Weather effects
        attacker_power *= weather_modifier

        # Combat resolution (modified Lanchester)
        combat_ratio = attacker_power / max(1, defender_power)

        # Calculate casualties
        base_casualty_rate = 0.05  # 5% base per engagement
        intensity = min(2.0, (attacker_power + defender_power) / 100)

        attacker_casualties = int(
            attacker_unit.state.strength_current *
            base_casualty_rate * intensity *
            (1.0 / max(0.5, combat_ratio)) *
            self.roll(1.0, 0.3)
        )

        defender_casualties = int(
            defender_unit.state.strength_current *
            base_casualty_rate * intensity *
            combat_ratio *
            self.roll(1.0, 0.3)
        )

        # Organization loss (more significant than casualties)
        attacker_org_loss = self.roll(5 + (10 / max(0.5, combat_ratio)), 0.3)
        defender_org_loss = self.roll(5 + (10 * combat_ratio), 0.3)

        # Determine outcome
        result = self.determine_result(attacker_power, defender_power)

        # Ground gained
        ground_gained = 0
        defender_retreated = False

        if result in (CombatResult.DECISIVE_VICTORY, CombatResult.VICTORY):
            if result == CombatResult.DECISIVE_VICTORY:
                ground_gained = 2
            else:
                ground_gained = 1
            defender_retreated = True
        elif result == CombatResult.MARGINAL:
            ground_gained = 1 if self.hit_check(0.5) else 0

        combat_result = GroundCombatResult(
            attacker_casualties=attacker_casualties,
            defender_casualties=defender_casualties,
            attacker_org_loss=attacker_org_loss,
            defender_org_loss=defender_org_loss,
            ground_gained_hexes=ground_gained,
            defender_retreated=defender_retreated,
        )

        report = CombatReport(
            attacker_id=engagement.attacker_id,
            defender_id=engagement.defender_id,
            turn=0,
            phase="ground",
            result=result,
            attacker_losses={"casualties": attacker_casualties},
            defender_losses={"casualties": defender_casualties},
            attacker_damage=attacker_org_loss,
            defender_damage=defender_org_loss,
            location=engagement.location,
            notes=[
                f"Combat ratio: {combat_ratio:.2f}:1",
                f"Terrain: {engagement.terrain} (x{terrain_mod:.1f})",
                f"Ground gained: {ground_gained} hexes",
            ]
        )

        return report, combat_result

    def _get_unit_category(self, unit) -> str:
        """Get simplified unit category for combat calculations."""
        unit_type = unit.unit_type.lower()

        if "armor" in unit_type or "tank" in unit_type:
            return "armor"
        elif "mech" in unit_type:
            return "mechanized"
        elif "mountain" in unit_type:
            return "mountain"
        else:
            return "infantry"

    def apply_combat_results(
        self,
        attacker_unit,
        defender_unit,
        result: GroundCombatResult,
    ):
        """Apply combat results to units."""
        attacker_unit.take_losses(
            result.attacker_casualties,
            result.attacker_org_loss
        )

        defender_unit.take_losses(
            result.defender_casualties,
            result.defender_org_loss
        )

        if result.defender_retreated:
            from ..units import UnitStatus
            defender_unit.status = UnitStatus.RETREATING

    def calculate_breakthrough(
        self,
        attacker_power: float,
        defender_power: float,
        defender_depth: int,  # Number of defensive lines
    ) -> dict:
        """Calculate if attacker achieves breakthrough."""
        ratio = attacker_power / max(1, defender_power)

        # Need significant superiority for breakthrough
        if ratio >= 3.0 and defender_depth <= 1:
            return {"breakthrough": True, "exploitation_hexes": 3}
        elif ratio >= 2.0 and defender_depth <= 1:
            return {"breakthrough": True, "exploitation_hexes": 2}
        elif ratio >= 2.5 and defender_depth <= 2:
            return {"breakthrough": True, "exploitation_hexes": 1}

        return {"breakthrough": False, "exploitation_hexes": 0}

    def resolve_urban_combat(
        self,
        attacker_unit,
        defender_unit,
        city_size: str,  # "small", "medium", "large"
    ) -> tuple[CombatReport, GroundCombatResult]:
        """Resolve urban/city combat with special rules."""

        # Urban combat heavily favors defender
        size_mod = {"small": 1.5, "medium": 2.0, "large": 2.5}
        urban_defense = size_mod.get(city_size, 2.0)

        engagement = GroundEngagement(
            attacker_id=attacker_unit.id,
            defender_id=defender_unit.id,
            location=(0, 0),
            attacker_posture="assault",
            defender_posture="defend",
            terrain="urban",
            terrain_defense_mod=urban_defense,
            urban=True,
        )

        return self.resolve_engagement(engagement, attacker_unit, defender_unit)
