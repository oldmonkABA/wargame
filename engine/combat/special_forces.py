"""
Special Forces combat resolution - SF/SOF operations.

Handles:
- Direct action (raids, ambushes)
- Reconnaissance
- Sabotage
- Personnel recovery
- Unconventional warfare
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import CombatResolver, CombatReport, CombatResult


@dataclass
class SFMission:
    """A special forces mission."""
    unit_id: str
    mission_type: str  # "raid", "recon", "sabotage", "da", "sr", "personnel_recovery"
    team_size: int
    target_id: Optional[str] = None
    target_location: tuple[int, int] = (0, 0)
    insertion_method: str = "ground"  # "ground", "helo", "halo", "water"
    extraction_planned: bool = True


@dataclass
class SFResult:
    """Result of special forces operation."""
    mission_success: bool
    objective_achieved: float  # 0-1, partial success possible
    casualties: int
    captured: int
    enemy_casualties: int
    intel_gathered: dict = field(default_factory=dict)
    damage_inflicted: float = 0.0
    compromised: bool = False  # Was the team detected


class SpecialForcesCombat(CombatResolver):
    """Resolves special forces operations."""

    # SF unit characteristics
    SF_STATS = {
        "para_sf": {"skill": 90, "stealth": 85, "firepower": 70, "endurance": 85},
        "marcos": {"skill": 92, "stealth": 88, "firepower": 75, "endurance": 88},
        "garud": {"skill": 85, "stealth": 80, "firepower": 72, "endurance": 82},
        "ssg": {"skill": 88, "stealth": 85, "firepower": 72, "endurance": 85},
        "ssgn": {"skill": 90, "stealth": 90, "firepower": 70, "endurance": 88},
        "zarrar": {"skill": 82, "stealth": 78, "firepower": 70, "endurance": 80},
    }

    # Mission difficulty modifiers
    MISSION_DIFFICULTY = {
        "raid": 1.2,
        "recon": 0.7,
        "sabotage": 1.0,
        "da": 1.3,  # Direct action
        "sr": 0.6,  # Special reconnaissance
        "personnel_recovery": 1.5,
    }

    # Target security levels
    SECURITY_LEVEL = {
        "low": 0.3,
        "medium": 0.5,
        "high": 0.7,
        "very_high": 0.9,
    }

    def resolve_mission(
        self,
        mission: SFMission,
        sf_stats: dict,
        target_security: str,
        target_troops: int,
        terrain_advantage: float = 1.0,  # Terrain helps SF
        intel_quality: float = 0.5,  # 0-1, how good is pre-mission intel
        support_available: bool = False,  # Air/artillery on call
    ) -> tuple[CombatReport, SFResult]:
        """Resolve a special forces mission."""

        # Get SF team characteristics
        sf_type = sf_stats.get("type", "").lower()
        base_stats = self.SF_STATS.get(sf_type, {
            "skill": 80, "stealth": 75, "firepower": 65, "endurance": 80
        })
        base_stats.update(sf_stats)

        skill = base_stats.get("skill", 80)
        stealth = base_stats.get("stealth", 75)
        firepower = base_stats.get("firepower", 65)

        # Mission difficulty
        difficulty = self.MISSION_DIFFICULTY.get(mission.mission_type, 1.0)
        security = self.SECURITY_LEVEL.get(target_security, 0.5)

        # Phase 1: Infiltration
        infiltration_success, compromised = self._resolve_infiltration(
            mission, stealth, security, intel_quality
        )

        if not infiltration_success:
            # Mission fails at infiltration
            casualties = self._calculate_casualties(
                mission.team_size, security, compromised=True, fighting=True
            )
            result = SFResult(
                mission_success=False,
                objective_achieved=0.0,
                casualties=casualties,
                captured=0,
                enemy_casualties=0,
                compromised=True,
            )
            return self._create_report(mission, CombatResult.DEFEAT, result), result

        # Phase 2: Mission execution
        objective_achieved, enemy_casualties, damage = self._execute_mission(
            mission, skill, firepower, target_troops, difficulty, intel_quality, support_available
        )

        # Phase 3: Extraction (if planned)
        extraction_casualties = 0
        captured = 0

        if mission.extraction_planned:
            extraction_success, extraction_casualties, captured = self._resolve_extraction(
                mission, stealth, security, compromised, target_troops - enemy_casualties
            )
        else:
            # Stay behind / exfiltrate independently
            if self.hit_check(stealth / 100.0):
                extraction_casualties = 0
            else:
                extraction_casualties = self._calculate_casualties(
                    mission.team_size, security * 0.5, compromised=compromised
                )

        total_casualties = extraction_casualties
        mission_success = objective_achieved >= 0.7

        # Determine overall result
        if mission_success and total_casualties == 0:
            result_enum = CombatResult.DECISIVE_VICTORY
        elif mission_success and total_casualties <= mission.team_size * 0.2:
            result_enum = CombatResult.VICTORY
        elif objective_achieved >= 0.5:
            result_enum = CombatResult.MARGINAL
        elif objective_achieved > 0:
            result_enum = CombatResult.STALEMATE
        else:
            result_enum = CombatResult.DEFEAT

        result = SFResult(
            mission_success=mission_success,
            objective_achieved=objective_achieved,
            casualties=total_casualties,
            captured=captured,
            enemy_casualties=enemy_casualties,
            damage_inflicted=damage,
            compromised=compromised,
        )

        return self._create_report(mission, result_enum, result), result

    def _resolve_infiltration(
        self,
        mission: SFMission,
        stealth: float,
        security: float,
        intel_quality: float,
    ) -> tuple[bool, bool]:
        """Resolve infiltration phase. Returns (success, compromised)."""

        # Insertion method affects detection chance
        insertion_mod = {
            "ground": 1.0,
            "helo": 1.3,  # Noisier
            "halo": 0.7,  # Stealthier
            "water": 0.8,
        }
        mod = insertion_mod.get(mission.insertion_method, 1.0)

        # Detection chance
        detection_chance = security * mod * (1.0 - stealth / 200.0) * (1.0 - intel_quality * 0.3)

        if self.hit_check(detection_chance):
            # Detected - can they still proceed?
            if self.hit_check(stealth / 100.0 * 0.5):
                return True, True  # Proceed but compromised
            else:
                return False, True  # Mission aborted
        else:
            return True, False  # Clean infiltration

    def _execute_mission(
        self,
        mission: SFMission,
        skill: float,
        firepower: float,
        target_troops: int,
        difficulty: float,
        intel_quality: float,
        support_available: bool,
    ) -> tuple[float, int, float]:
        """Execute mission objective. Returns (achievement, enemy_casualties, damage)."""

        # Base success chance
        success_chance = (skill / 100.0) * (1.0 + intel_quality * 0.3) / difficulty

        if support_available:
            success_chance *= 1.2
            firepower *= 1.5

        # Roll for success
        achievement = 0.0
        enemy_casualties = 0
        damage = 0.0

        if self.hit_check(success_chance):
            achievement = self.roll(0.9, 0.1)  # 80-100% success

            if mission.mission_type in ("raid", "da"):
                # Combat mission - casualties and damage
                enemy_casualties = int(target_troops * self.roll(0.3, 0.2) * firepower / 100.0)
                damage = self.roll(70, 0.2)

            elif mission.mission_type == "sabotage":
                # Sabotage - primarily damage
                damage = self.roll(80, 0.15)
                enemy_casualties = int(self.roll(3, 0.5))

            elif mission.mission_type in ("recon", "sr"):
                # Recon - intel gathering, minimal contact
                enemy_casualties = 0
                damage = 0

        elif self.hit_check(success_chance * 0.7):
            # Partial success
            achievement = self.roll(0.5, 0.2)
            if mission.mission_type in ("raid", "da", "sabotage"):
                damage = self.roll(40, 0.3)
                enemy_casualties = int(target_troops * self.roll(0.1, 0.3) * firepower / 100.0)

        return achievement, enemy_casualties, damage

    def _resolve_extraction(
        self,
        mission: SFMission,
        stealth: float,
        security: float,
        compromised: bool,
        remaining_enemy: int,
    ) -> tuple[bool, int, int]:
        """Resolve extraction phase. Returns (success, casualties, captured)."""

        # Extraction is harder if compromised
        if compromised:
            security *= 1.5

        # Pursuit intensity
        pursuit = security * (remaining_enemy / max(1, remaining_enemy + 10))

        extraction_chance = (stealth / 100.0) * (1.0 - pursuit * 0.5)

        casualties = 0
        captured = 0

        if self.hit_check(extraction_chance):
            # Clean extraction
            return True, 0, 0
        else:
            # Fighting extraction
            casualties = self._calculate_casualties(
                mission.team_size, security, compromised=True, fighting=True
            )

            # Some might be captured
            if casualties > 0 and self.hit_check(0.2):
                captured = min(casualties, self.rng.randint(1, 2))
                casualties -= captured

            return casualties < mission.team_size, casualties, captured

    def _calculate_casualties(
        self,
        team_size: int,
        security: float,
        compromised: bool = False,
        fighting: bool = False,
    ) -> int:
        """Calculate SF casualties."""
        base_rate = 0.05  # 5% base

        if compromised:
            base_rate *= 2
        if fighting:
            base_rate *= 1.5

        base_rate *= security

        casualties = int(team_size * base_rate * self.roll(1.0, 0.5))
        return min(team_size, max(0, casualties))

    def resolve_recon(
        self,
        mission: SFMission,
        sf_stats: dict,
        target_area_units: list,
        observation_time_turns: int,
    ) -> tuple[CombatReport, SFResult]:
        """Resolve special reconnaissance mission."""

        stealth = sf_stats.get("stealth", 75)
        skill = sf_stats.get("skill", 80)

        intel = {
            "units_identified": [],
            "positions": [],
            "strength_estimates": {},
            "activity_patterns": [],
            "vulnerabilities": [],
        }

        compromised = False

        # Each turn of observation
        for turn in range(observation_time_turns):
            # Risk of detection each turn
            if self.hit_check(0.1 * (1.0 - stealth / 200.0)):
                compromised = True
                break

            # Gather intel on units
            for unit in target_area_units:
                if unit.id not in intel["units_identified"]:
                    detect_chance = (skill / 100.0) * 0.5  # 50% per turn
                    if self.hit_check(detect_chance):
                        intel["units_identified"].append(unit.id)
                        intel["positions"].append({
                            "unit_id": unit.id,
                            "location": (unit.location.hex_q, unit.location.hex_r),
                            "accuracy": self.roll(0.9, 0.1)
                        })
                        intel["strength_estimates"][unit.id] = int(
                            unit.state.strength_current * self.roll(1.0, 0.15)
                        )

        # Identify vulnerabilities
        if len(intel["units_identified"]) > 0 and self.hit_check(skill / 100.0):
            intel["vulnerabilities"] = ["supply_route", "command_post"]  # Example

        objective = len(intel["units_identified"]) / max(1, len(target_area_units))

        if compromised:
            casualties = self._calculate_casualties(mission.team_size, 0.5, compromised=True)
        else:
            casualties = 0

        result = SFResult(
            mission_success=objective >= 0.5 and not compromised,
            objective_achieved=objective,
            casualties=casualties,
            captured=0,
            enemy_casualties=0,
            intel_gathered=intel,
            compromised=compromised,
        )

        if objective >= 0.8 and not compromised:
            result_enum = CombatResult.DECISIVE_VICTORY
        elif objective >= 0.5:
            result_enum = CombatResult.VICTORY
        elif objective >= 0.3:
            result_enum = CombatResult.MARGINAL
        else:
            result_enum = CombatResult.DEFEAT

        return self._create_report(mission, result_enum, result), result

    def _create_report(
        self,
        mission: SFMission,
        result: CombatResult,
        sf_result: SFResult
    ) -> CombatReport:
        """Create combat report."""
        return CombatReport(
            attacker_id=mission.unit_id,
            defender_id=mission.target_id or "target_area",
            turn=0,
            phase="special_forces",
            result=result,
            attacker_losses={
                "casualties": sf_result.casualties,
                "captured": sf_result.captured,
            },
            defender_losses={
                "casualties": sf_result.enemy_casualties,
            },
            defender_damage=sf_result.damage_inflicted,
            location=mission.target_location,
            notes=[
                f"Mission: {mission.mission_type}",
                f"Team size: {mission.team_size}",
                f"Objective achieved: {sf_result.objective_achieved:.0%}",
                f"Compromised: {sf_result.compromised}",
            ]
        )
