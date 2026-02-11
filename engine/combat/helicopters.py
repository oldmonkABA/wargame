"""
Helicopter combat resolution - attack and transport helicopters.

Handles:
- Attack helicopter strikes (anti-armor, CAS)
- Air assault operations
- CSAR (Combat Search and Rescue)
- Scout/recon missions
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import CombatResolver, CombatReport, CombatResult


@dataclass
class HelicopterMission:
    """A helicopter mission."""
    unit_id: str
    mission_type: str  # "attack", "cas", "air_assault", "scout", "csar"
    helicopter_count: int
    helicopter_type: str
    target_id: Optional[str] = None
    target_location: Optional[tuple[int, int]] = None
    payload: list[str] = field(default_factory=list)  # Troops for air assault


@dataclass
class HelicopterEngagement:
    """Result of helicopter operations."""
    helicopters_lost: int
    helicopters_damaged: int
    target_casualties: int
    target_equipment_destroyed: int
    troops_inserted: int = 0  # For air assault


class HelicopterCombat(CombatResolver):
    """Resolves helicopter combat operations."""

    # Helicopter characteristics
    HELICOPTER_STATS = {
        # Attack helicopters
        "apache": {"attack": 90, "defense": 60, "speed": 75, "armor_pen": 85, "type": "attack"},
        "lch": {"attack": 75, "defense": 55, "speed": 70, "armor_pen": 70, "type": "attack"},
        "rudra": {"attack": 65, "defense": 50, "speed": 70, "armor_pen": 60, "type": "attack"},
        "cobra": {"attack": 75, "defense": 55, "speed": 70, "armor_pen": 75, "type": "attack"},
        "t129": {"attack": 80, "defense": 58, "speed": 72, "armor_pen": 78, "type": "attack"},
        "z10": {"attack": 82, "defense": 55, "speed": 70, "armor_pen": 80, "type": "attack"},

        # Transport/utility
        "chinook": {"attack": 20, "defense": 40, "speed": 65, "capacity": 40, "type": "transport"},
        "mi17": {"attack": 30, "defense": 45, "speed": 60, "capacity": 30, "type": "transport"},
    }

    # Target vulnerability to helicopter attack
    VULNERABILITY = {
        "armor": 0.8,  # Helicopters are tank-killers
        "mechanized": 1.2,
        "infantry": 1.0,
        "artillery": 1.5,
        "logistics": 1.8,
        "air_defense": 0.4,  # Dangerous to attack
    }

    def resolve_attack_mission(
        self,
        mission: HelicopterMission,
        heli_stats: dict,
        target_unit,
        air_defense_coverage: list,
        terrain_concealment: float,
        weather_modifier: float = 1.0,
    ) -> tuple[CombatReport, HelicopterEngagement]:
        """Resolve attack helicopter strike."""

        # Get helicopter characteristics
        heli_type = mission.helicopter_type.lower()
        stats = self.HELICOPTER_STATS.get(heli_type, {
            "attack": 70, "defense": 50, "armor_pen": 70
        })
        stats.update(heli_stats)

        helicopter_count = mission.helicopter_count
        losses = 0
        damaged = 0

        # Phase 1: Air defense engagement
        for ad in air_defense_coverage:
            if helicopter_count <= losses:
                break

            ad_effectiveness = ad.get("effectiveness", 0.5)
            ad_type = ad.get("type", "manpads")

            # Different AD types vs helicopters
            if ad_type in ("manpads", "shorad"):
                ad_effectiveness *= 1.2  # More effective vs low-flying helos
            elif ad_type in ("sam", "mrsam"):
                ad_effectiveness *= 0.7  # Less effective

            # Helicopter defense/evasion
            defense_mod = stats.get("defense", 50) / 100.0
            ad_effectiveness *= (1.0 - defense_mod * 0.5)

            engagements = min(ad.get("missiles", 4), helicopter_count - losses)
            for _ in range(engagements):
                if self.hit_check(ad_effectiveness):
                    if self.hit_check(0.7):  # Kill vs damage
                        losses += 1
                    else:
                        damaged += 1

        # Phase 2: Attack run
        surviving = helicopter_count - losses
        if surviving <= 0:
            engagement = HelicopterEngagement(
                helicopters_lost=losses,
                helicopters_damaged=damaged,
                target_casualties=0,
                target_equipment_destroyed=0,
            )
            return self._create_report(mission, CombatResult.DEFEAT, engagement), engagement

        # Target classification
        target_type = self._classify_target(target_unit)
        vulnerability = self.VULNERABILITY.get(target_type, 1.0)

        # Attack effectiveness
        attack_rating = stats.get("attack", 70)
        armor_pen = stats.get("armor_pen", 70)

        # Concealment reduces accuracy
        concealment_mod = 1.0 - (terrain_concealment / 200.0)

        # Calculate damage
        hits = 0
        equipment_destroyed = 0

        for _ in range(surviving):
            hit_chance = (attack_rating / 100.0) * concealment_mod * weather_modifier
            if self.hit_check(hit_chance):
                hits += 1
                # Equipment kills (for armor/mech targets)
                if target_type in ("armor", "mechanized"):
                    if self.hit_check(armor_pen / 100.0):
                        equipment_destroyed += 1

        # Calculate casualties
        casualty_rate = hits * 0.02 * vulnerability  # 2% per hit base
        casualties = int(target_unit.state.strength_current * casualty_rate * self.roll(1.0, 0.3))

        # Determine result
        effectiveness = (hits + equipment_destroyed * 2) / max(1, helicopter_count)
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

        engagement = HelicopterEngagement(
            helicopters_lost=losses,
            helicopters_damaged=damaged,
            target_casualties=casualties,
            target_equipment_destroyed=equipment_destroyed,
        )

        return self._create_report(mission, result, engagement), engagement

    def resolve_air_assault(
        self,
        mission: HelicopterMission,
        troops_count: int,
        landing_zone_security: str,  # "cold", "warm", "hot"
        air_defense_coverage: list,
        weather_modifier: float = 1.0,
    ) -> tuple[CombatReport, HelicopterEngagement]:
        """Resolve air assault/insertion operation."""

        helicopter_count = mission.helicopter_count
        losses = 0
        damaged = 0
        troops_lost = 0

        # LZ security affects risk
        lz_risk = {"cold": 0.0, "warm": 0.3, "hot": 0.7}
        risk_level = lz_risk.get(landing_zone_security, 0.3)

        # Air defense during approach
        for ad in air_defense_coverage:
            if helicopter_count <= losses:
                break

            ad_effectiveness = ad.get("effectiveness", 0.4) * weather_modifier

            engagements = min(ad.get("missiles", 4), helicopter_count - losses)
            for _ in range(engagements):
                if self.hit_check(ad_effectiveness):
                    if self.hit_check(0.6):
                        losses += 1
                        # Troops lost with helicopter
                        troops_per_helo = troops_count // helicopter_count
                        troops_lost += troops_per_helo
                    else:
                        damaged += 1

        # LZ risk (ground fire during landing)
        surviving_helos = helicopter_count - losses
        for _ in range(surviving_helos):
            if self.hit_check(risk_level * 0.3):
                if self.hit_check(0.4):
                    losses += 1
                    troops_per_helo = troops_count // helicopter_count
                    troops_lost += troops_per_helo
                else:
                    damaged += 1

        # Troops inserted
        troops_inserted = troops_count - troops_lost

        if troops_inserted >= troops_count * 0.8:
            result = CombatResult.DECISIVE_VICTORY
        elif troops_inserted >= troops_count * 0.6:
            result = CombatResult.VICTORY
        elif troops_inserted >= troops_count * 0.4:
            result = CombatResult.MARGINAL
        elif troops_inserted > 0:
            result = CombatResult.STALEMATE
        else:
            result = CombatResult.DEFEAT

        engagement = HelicopterEngagement(
            helicopters_lost=losses,
            helicopters_damaged=damaged,
            target_casualties=0,
            target_equipment_destroyed=0,
            troops_inserted=troops_inserted,
        )

        report = CombatReport(
            attacker_id=mission.unit_id,
            defender_id="landing_zone",
            turn=0,
            phase="helicopter_air_assault",
            result=result,
            attacker_losses={
                "helicopters": losses,
                "troops": troops_lost,
            },
            notes=[
                f"LZ security: {landing_zone_security}",
                f"Troops inserted: {troops_inserted}/{troops_count}",
                f"Helicopters lost: {losses}, damaged: {damaged}",
            ]
        )

        return report, engagement

    def _classify_target(self, target_unit) -> str:
        """Classify target for vulnerability."""
        unit_type = target_unit.unit_type.lower()

        if "armor" in unit_type or "tank" in unit_type:
            return "armor"
        elif "mech" in unit_type:
            return "mechanized"
        elif "artillery" in unit_type:
            return "artillery"
        elif "air_defense" in unit_type or "sam" in unit_type:
            return "air_defense"
        elif "logistics" in unit_type or "supply" in unit_type:
            return "logistics"
        else:
            return "infantry"

    def _create_report(
        self,
        mission: HelicopterMission,
        result: CombatResult,
        engagement: HelicopterEngagement
    ) -> CombatReport:
        """Create combat report from engagement."""
        return CombatReport(
            attacker_id=mission.unit_id,
            defender_id=mission.target_id or "target",
            turn=0,
            phase="helicopter",
            result=result,
            attacker_losses={
                "helicopters_lost": engagement.helicopters_lost,
                "helicopters_damaged": engagement.helicopters_damaged,
            },
            defender_losses={
                "casualties": engagement.target_casualties,
                "equipment": engagement.target_equipment_destroyed,
            },
            notes=[
                f"Mission: {mission.mission_type}",
                f"Force: {mission.helicopter_count} {mission.helicopter_type}",
            ]
        )
