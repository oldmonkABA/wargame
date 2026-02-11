"""
Electronic Warfare resolution - jamming, cyber, SIGINT.

Handles:
- Radar jamming
- Communications disruption
- GPS denial
- Cyber attacks on C2
- SIGINT collection
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import CombatResolver, CombatReport, CombatResult


@dataclass
class EWMission:
    """An electronic warfare mission."""
    unit_id: str
    mission_type: str  # "jam_radar", "jam_comms", "gps_denial", "cyber", "sigint"
    target_id: Optional[str] = None
    target_area: Optional[tuple[int, int]] = None
    area_radius_km: int = 50
    duration_turns: int = 1


@dataclass
class EWEffect:
    """Effect of electronic warfare."""
    radar_degradation: float = 0.0  # 0-1, reduces detection/tracking
    comms_degradation: float = 0.0  # 0-1, reduces coordination
    gps_degradation: float = 0.0  # 0-1, reduces precision munitions
    cyber_damage: float = 0.0  # 0-100, damage to C2 systems
    intel_gathered: dict = field(default_factory=dict)
    affected_units: list = field(default_factory=list)


class ElectronicWarfare(CombatResolver):
    """Resolves electronic warfare operations."""

    # EW system characteristics
    EW_SYSTEMS = {
        # Airborne jammers
        "growler": {"type": "airborne", "power": 90, "range_km": 150, "spectrum": ["radar", "comms"]},
        "kj500": {"type": "airborne", "power": 85, "range_km": 200, "spectrum": ["radar"]},

        # Ground-based
        "krasukha": {"type": "ground", "power": 85, "range_km": 300, "spectrum": ["radar", "gps"]},
        "samyukta": {"type": "ground", "power": 70, "range_km": 150, "spectrum": ["radar", "comms"]},

        # Tactical
        "shortstop": {"type": "tactical", "power": 50, "range_km": 30, "spectrum": ["comms"]},
    }

    # Target vulnerability to EW
    VULNERABILITY = {
        "awacs": 0.6,  # Hardened but high value
        "fighter": 0.8,
        "sam_radar": 0.9,
        "artillery_radar": 1.0,
        "ground_comms": 0.7,
        "gps_guided": 1.2,  # Very vulnerable
    }

    def resolve_jamming(
        self,
        mission: EWMission,
        ew_stats: dict,
        target_units: list,
        target_ew_defense: float = 0.0,  # Target's ECCM capability
    ) -> tuple[CombatReport, EWEffect]:
        """Resolve radar/comms jamming mission."""

        ew_type = ew_stats.get("type", "ground")
        power = ew_stats.get("power", 70)
        spectrum = ew_stats.get("spectrum", ["radar"])

        # ECCM reduces jamming effectiveness
        effective_power = power * (1.0 - target_ew_defense / 200.0)

        effect = EWEffect()

        if "radar" in spectrum and mission.mission_type in ("jam_radar", "jam_comms"):
            # Calculate radar degradation
            base_degradation = effective_power / 100.0
            effect.radar_degradation = min(0.8, base_degradation * self.roll(1.0, 0.2))

        if "comms" in spectrum and mission.mission_type in ("jam_comms", "jam_radar"):
            # Communications jamming
            base_degradation = effective_power / 100.0 * 0.8  # Slightly less effective
            effect.comms_degradation = min(0.7, base_degradation * self.roll(1.0, 0.2))

        if "gps" in spectrum or mission.mission_type == "gps_denial":
            # GPS jamming
            base_degradation = effective_power / 100.0 * 0.9
            effect.gps_degradation = min(0.9, base_degradation * self.roll(1.0, 0.15))

        # Determine affected units
        for unit in target_units:
            vulnerability = self._get_vulnerability(unit)
            if self.hit_check(effective_power / 100.0 * vulnerability):
                effect.affected_units.append(unit.id)

        # Determine result based on effectiveness
        avg_degradation = (effect.radar_degradation + effect.comms_degradation + effect.gps_degradation) / 3
        if avg_degradation >= 0.6:
            result = CombatResult.DECISIVE_VICTORY
        elif avg_degradation >= 0.4:
            result = CombatResult.VICTORY
        elif avg_degradation >= 0.2:
            result = CombatResult.MARGINAL
        elif len(effect.affected_units) > 0:
            result = CombatResult.STALEMATE
        else:
            result = CombatResult.DEFEAT

        report = CombatReport(
            attacker_id=mission.unit_id,
            defender_id=mission.target_id or "area_jam",
            turn=0,
            phase="ew",
            result=result,
            notes=[
                f"Mission: {mission.mission_type}",
                f"Radar degradation: {effect.radar_degradation:.0%}",
                f"Comms degradation: {effect.comms_degradation:.0%}",
                f"Units affected: {len(effect.affected_units)}",
            ]
        )

        return report, effect

    def resolve_cyber_attack(
        self,
        mission: EWMission,
        target_system: str,  # "c2", "air_defense", "logistics", "comms"
        target_cyber_defense: float,  # 0-100
        attack_sophistication: float,  # 0-100
    ) -> tuple[CombatReport, EWEffect]:
        """Resolve cyber attack on enemy systems."""

        effect = EWEffect()

        # Cyber attack success probability
        base_success = attack_sophistication / 100.0
        defense_mod = 1.0 - (target_cyber_defense / 200.0)
        success_chance = base_success * defense_mod

        if self.hit_check(success_chance):
            # Determine damage based on target
            damage_ranges = {
                "c2": (30, 60),  # Command and control
                "air_defense": (20, 50),
                "logistics": (25, 55),
                "comms": (35, 65),
            }

            min_dmg, max_dmg = damage_ranges.get(target_system, (20, 40))
            effect.cyber_damage = self.rng.uniform(min_dmg, max_dmg)

            # Cascading effects
            if target_system == "c2":
                effect.comms_degradation = effect.cyber_damage / 200.0
            elif target_system == "air_defense":
                effect.radar_degradation = effect.cyber_damage / 150.0

            result = CombatResult.VICTORY if effect.cyber_damage >= 40 else CombatResult.MARGINAL
        else:
            result = CombatResult.DEFEAT

        report = CombatReport(
            attacker_id=mission.unit_id,
            defender_id=f"cyber_{target_system}",
            turn=0,
            phase="cyber",
            result=result,
            defender_damage=effect.cyber_damage,
            notes=[
                f"Target system: {target_system}",
                f"Attack sophistication: {attack_sophistication:.0f}",
                f"Damage: {effect.cyber_damage:.1f}%",
            ]
        )

        return report, effect

    def resolve_sigint(
        self,
        mission: EWMission,
        sigint_capability: float,  # 0-100
        target_comms_activity: float,  # 0-100, how much the enemy is transmitting
        target_comsec: float,  # 0-100, communications security
    ) -> tuple[CombatReport, EWEffect]:
        """Resolve SIGINT collection mission."""

        effect = EWEffect()

        # Base intercept probability
        intercept_chance = (sigint_capability / 100.0) * (target_comms_activity / 100.0)
        comsec_mod = 1.0 - (target_comsec / 200.0)
        intercept_chance *= comsec_mod

        intel = {
            "unit_locations": [],
            "order_of_battle": False,
            "intentions": False,
            "supply_status": False,
        }

        # Roll for different intelligence types
        if self.hit_check(intercept_chance):
            intel["unit_locations"] = ["partial"]  # Would be filled with actual data

        if self.hit_check(intercept_chance * 0.7):
            intel["order_of_battle"] = True

        if self.hit_check(intercept_chance * 0.5):
            intel["intentions"] = True  # Enemy plans

        if self.hit_check(intercept_chance * 0.8):
            intel["supply_status"] = True

        effect.intel_gathered = intel

        # Rate success
        intel_value = sum([
            1 if intel["unit_locations"] else 0,
            2 if intel["order_of_battle"] else 0,
            3 if intel["intentions"] else 0,
            1 if intel["supply_status"] else 0,
        ])

        if intel_value >= 5:
            result = CombatResult.DECISIVE_VICTORY
        elif intel_value >= 3:
            result = CombatResult.VICTORY
        elif intel_value >= 1:
            result = CombatResult.MARGINAL
        else:
            result = CombatResult.DEFEAT

        report = CombatReport(
            attacker_id=mission.unit_id,
            defender_id="sigint_target",
            turn=0,
            phase="sigint",
            result=result,
            notes=[
                f"Intercept capability: {sigint_capability:.0f}%",
                f"Enemy COMSEC: {target_comsec:.0f}%",
                f"Intel gathered: OOB={intel['order_of_battle']}, Intentions={intel['intentions']}",
            ]
        )

        return report, effect

    def _get_vulnerability(self, unit) -> float:
        """Get unit's vulnerability to EW."""
        unit_type = unit.unit_type.lower()

        if "awacs" in unit_type or "aew" in unit_type:
            return self.VULNERABILITY["awacs"]
        elif "sam" in unit_type or "air_defense" in unit_type:
            return self.VULNERABILITY["sam_radar"]
        elif "aircraft" in unit_type or unit.category.value == "aircraft":
            return self.VULNERABILITY["fighter"]
        elif "artillery" in unit_type:
            return self.VULNERABILITY["artillery_radar"]
        else:
            return self.VULNERABILITY["ground_comms"]

    def calculate_area_effect(
        self,
        center: tuple[int, int],
        radius_hexes: int,
        effect: EWEffect,
    ) -> dict:
        """Calculate EW effect over an area."""
        # Effect degrades with distance from jammer
        return {
            "center": center,
            "radius": radius_hexes,
            "degradation_at_edge": 0.5,  # 50% effect at edge
            "radar_effect": effect.radar_degradation,
            "comms_effect": effect.comms_degradation,
            "gps_effect": effect.gps_degradation,
        }

    def apply_ew_effects(self, units: list, effect: EWEffect):
        """Apply EW effects to affected units."""
        for unit in units:
            if unit.id in effect.affected_units:
                # Reduce unit effectiveness
                # This would modify combat calculations
                pass
