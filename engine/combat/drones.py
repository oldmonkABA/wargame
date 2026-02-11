"""
Drone combat resolution - UAVs and loitering munitions.

Handles:
- ISR drone missions
- UCAV strikes
- Loitering munition attacks
- Drone swarm operations
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import CombatResolver, CombatReport, CombatResult


@dataclass
class DroneMission:
    """A drone mission."""
    unit_id: str
    mission_type: str  # "isr", "strike", "sead", "loitering", "swarm"
    drone_count: int
    drone_type: str
    target_id: Optional[str] = None
    target_location: Optional[tuple[int, int]] = None
    loiter_time_hours: float = 0  # For loitering munitions


@dataclass
class DroneEngagement:
    """Result of drone operations."""
    drones_lost: int
    targets_destroyed: int
    targets_damaged: int
    intelligence_gathered: dict = field(default_factory=dict)


class DroneCombat(CombatResolver):
    """Resolves drone/UAV operations."""

    def __init__(self, swarm_config: dict = None, rng_seed=None):
        super().__init__(rng_seed)
        self.swarm_config = swarm_config or {}

    # Drone characteristics
    DRONE_STATS = {
        # ISR drones
        "heron": {"type": "isr", "endurance": 24, "detection": 85, "stealth": 40},
        "searcher": {"type": "isr", "endurance": 16, "detection": 70, "stealth": 35},
        "shahpar": {"type": "isr", "endurance": 8, "detection": 60, "stealth": 30},

        # UCAV / Strike drones
        "harop": {"type": "loitering", "damage": 80, "accuracy": 85, "stealth": 60},
        "mq9": {"type": "ucav", "damage": 75, "accuracy": 80, "stealth": 45, "weapons": 4},
        "wing_loong": {"type": "ucav", "damage": 70, "accuracy": 75, "stealth": 40, "weapons": 4},
        "burraq": {"type": "ucav", "damage": 65, "accuracy": 70, "stealth": 35, "weapons": 2},

        # Loitering munitions
        "switchblade": {"type": "loitering", "damage": 40, "accuracy": 80, "stealth": 70},
        "hero_120": {"type": "loitering", "damage": 60, "accuracy": 82, "stealth": 65},
    }

    # Target vulnerability
    VULNERABILITY = {
        "radar": 2.0,  # High value, vulnerable
        "sam_site": 1.5,
        "artillery": 1.3,
        "logistics": 1.4,
        "command_post": 1.8,
        "armor": 0.6,
        "infantry": 0.8,
    }

    def resolve_strike_mission(
        self,
        mission: DroneMission,
        drone_stats: dict,
        target_unit,
        air_defense_coverage: list,
        ew_degradation: float = 0.0,  # EW jamming effect
        weather_modifier: float = 1.0,
    ) -> tuple[CombatReport, DroneEngagement]:
        """Resolve drone strike mission."""

        drone_type = mission.drone_type.lower()
        stats = self.DRONE_STATS.get(drone_type, {
            "type": "ucav", "damage": 60, "accuracy": 70, "stealth": 40
        })
        stats.update(drone_stats)

        drone_count = mission.drone_count
        losses = 0

        is_loitering = stats.get("type") == "loitering"

        # Air defense engagement
        for ad in air_defense_coverage:
            if drone_count <= losses:
                break

            ad_effectiveness = ad.get("effectiveness", 0.5)

            # Drone stealth reduces detection
            stealth = stats.get("stealth", 40)
            detection_mod = 1.0 - (stealth / 200.0)
            ad_effectiveness *= detection_mod

            # Small drones harder to hit
            if is_loitering:
                ad_effectiveness *= 0.6

            # EW degradation affects AD tracking
            ad_effectiveness *= (1.0 - ew_degradation)

            engagements = min(ad.get("missiles", 4), drone_count - losses)
            for _ in range(engagements):
                if self.hit_check(ad_effectiveness):
                    losses += 1

        # Strike phase
        surviving = drone_count - losses
        if surviving <= 0:
            engagement = DroneEngagement(drones_lost=losses, targets_destroyed=0, targets_damaged=0)
            return self._create_report(mission, CombatResult.DEFEAT, engagement), engagement

        # Target classification
        target_type = self._classify_target(target_unit)
        vulnerability = self.VULNERABILITY.get(target_type, 1.0)

        # Attack parameters
        accuracy = stats.get("accuracy", 70)
        damage = stats.get("damage", 60)

        # EW can degrade drone accuracy
        accuracy *= (1.0 - ew_degradation * 0.5)

        targets_destroyed = 0
        targets_damaged = 0

        if is_loitering:
            # Loitering munitions are one-shot, one-kill attempts
            for _ in range(surviving):
                hit_chance = (accuracy / 100.0) * weather_modifier
                if self.hit_check(hit_chance):
                    if self.hit_check(damage / 100.0 * vulnerability):
                        targets_destroyed += 1
                    else:
                        targets_damaged += 1
            losses = drone_count  # All expended
        else:
            # UCAVs can carry multiple weapons
            weapons_per_drone = stats.get("weapons", 2)
            total_weapons = surviving * weapons_per_drone

            for _ in range(total_weapons):
                hit_chance = (accuracy / 100.0) * weather_modifier
                if self.hit_check(hit_chance):
                    if self.hit_check(damage / 100.0 * vulnerability * 0.5):
                        targets_destroyed += 1
                    else:
                        targets_damaged += 1

        # Determine result
        effectiveness = (targets_destroyed * 2 + targets_damaged) / max(1, drone_count)
        if effectiveness >= 1.5:
            result = CombatResult.DECISIVE_VICTORY
        elif effectiveness >= 1.0:
            result = CombatResult.VICTORY
        elif effectiveness >= 0.5:
            result = CombatResult.MARGINAL
        elif targets_destroyed + targets_damaged > 0:
            result = CombatResult.STALEMATE
        else:
            result = CombatResult.DEFEAT

        engagement = DroneEngagement(
            drones_lost=losses,
            targets_destroyed=targets_destroyed,
            targets_damaged=targets_damaged,
        )

        return self._create_report(mission, result, engagement), engagement

    def resolve_isr_mission(
        self,
        mission: DroneMission,
        target_area: tuple[int, int],
        area_radius: int,
        enemy_units: list,
        air_defense_coverage: list,
        ew_degradation: float = 0.0,
        weather_modifier: float = 1.0,
    ) -> tuple[CombatReport, DroneEngagement]:
        """Resolve ISR/reconnaissance drone mission."""

        drone_type = mission.drone_type.lower()
        stats = self.DRONE_STATS.get(drone_type, {
            "type": "isr", "endurance": 12, "detection": 70, "stealth": 40
        })

        drone_count = mission.drone_count
        losses = 0

        # Air defense during loiter
        # Lower chance since ISR drones stay at standoff
        for ad in air_defense_coverage:
            if drone_count <= losses:
                break

            # Only long-range AD can engage
            ad_range = ad.get("range_km", 20)
            if ad_range < 50:
                continue

            ad_effectiveness = ad.get("effectiveness", 0.3) * 0.5
            stealth = stats.get("stealth", 40)
            ad_effectiveness *= (1.0 - stealth / 200.0)

            if self.hit_check(ad_effectiveness):
                losses += 1

        surviving = drone_count - losses

        # Intelligence gathering
        detection_rating = stats.get("detection", 70)
        detection_rating *= (1.0 - ew_degradation * 0.3)
        detection_rating *= weather_modifier

        intelligence = {
            "units_detected": [],
            "positions_confirmed": [],
            "strength_estimates": {},
        }

        for unit in enemy_units:
            # Detection chance based on unit concealment
            unit_concealment = unit.state.dug_in * 15 + 20  # Base concealment
            detect_chance = (detection_rating / 100.0) * (1.0 - unit_concealment / 200.0)

            if surviving > 0 and self.hit_check(detect_chance):
                intelligence["units_detected"].append(unit.id)
                intelligence["positions_confirmed"].append({
                    "unit_id": unit.id,
                    "location": (unit.location.hex_q, unit.location.hex_r)
                })
                # Strength estimate accuracy
                accuracy = self.roll(0.8, 0.2)
                intelligence["strength_estimates"][unit.id] = {
                    "estimated": int(unit.state.strength_current * accuracy),
                    "accuracy": accuracy
                }

        units_found = len(intelligence["units_detected"])
        total_units = len(enemy_units)

        if total_units > 0:
            coverage = units_found / total_units
            if coverage >= 0.8:
                result = CombatResult.DECISIVE_VICTORY
            elif coverage >= 0.5:
                result = CombatResult.VICTORY
            elif coverage >= 0.3:
                result = CombatResult.MARGINAL
            elif units_found > 0:
                result = CombatResult.STALEMATE
            else:
                result = CombatResult.DEFEAT
        else:
            result = CombatResult.STALEMATE

        engagement = DroneEngagement(
            drones_lost=losses,
            targets_destroyed=0,
            targets_damaged=0,
            intelligence_gathered=intelligence,
        )

        report = CombatReport(
            attacker_id=mission.unit_id,
            defender_id="area_recon",
            turn=0,
            phase="drone_isr",
            result=result,
            attacker_losses={"drones": losses},
            notes=[
                f"ISR mission: {surviving} drones active",
                f"Units detected: {units_found}/{total_units}",
                f"Detection rating: {detection_rating:.0f}%",
            ]
        )

        return report, engagement

    def resolve_sead_swarm(
        self,
        mission: DroneMission,
        target_sam: dict,
        escort_drones: int = 0,  # Decoy/jammer drones
    ) -> tuple[CombatReport, DroneEngagement]:
        """Resolve drone swarm attack on air defense."""

        drone_count = mission.drone_count
        total_drones = drone_count + escort_drones

        sam_missiles = target_sam.get("missiles", 20)
        sam_effectiveness = target_sam.get("effectiveness", 0.6)

        # Override with YAML swarm saturation mechanics when available
        if self.swarm_config and "saturation_mechanics" in self.swarm_config:
            per_system = self.swarm_config["saturation_mechanics"].get("per_system_pk", {})
            sam_type = target_sam.get("type", "").lower().replace("-", "").replace(" ", "")
            for sys_key, sys_data in per_system.items():
                if sys_key in sam_type:
                    sam_effectiveness = sys_data["base_pk"]
                    sam_missiles = sys_data["intercept_capacity"]
                    break

        # Swarm saturation - effectiveness degrades with numbers
        if total_drones > sam_missiles:
            saturation_factor = sam_missiles / total_drones
        else:
            saturation_factor = 1.0

        losses = 0
        # SAM engages swarm
        for _ in range(min(sam_missiles, total_drones)):
            pk = sam_effectiveness * saturation_factor * 0.5  # Small targets
            if self.hit_check(pk):
                if escort_drones > 0:
                    escort_drones -= 1  # Escorts sacrificed first
                else:
                    losses += 1

        # Surviving strike drones attack
        surviving = drone_count - losses
        sam_damage = 0.0

        for _ in range(surviving):
            if self.hit_check(0.75):  # Loitering munition hit
                sam_damage += self.roll(30, 0.2)

        if sam_damage >= 80:
            result = CombatResult.DECISIVE_VICTORY
        elif sam_damage >= 50:
            result = CombatResult.VICTORY
        elif sam_damage >= 25:
            result = CombatResult.MARGINAL
        else:
            result = CombatResult.STALEMATE

        engagement = DroneEngagement(
            drones_lost=losses + (mission.drone_count - losses),  # All strike drones expended
            targets_destroyed=1 if sam_damage >= 80 else 0,
            targets_damaged=1 if 25 <= sam_damage < 80 else 0,
        )

        report = CombatReport(
            attacker_id=mission.unit_id,
            defender_id=target_sam.get("id", "sam_site"),
            turn=0,
            phase="drone_sead",
            result=result,
            attacker_losses={"drones": drone_count, "escorts": escort_drones - max(0, escort_drones)},
            defender_losses={"damage": sam_damage},
            notes=[
                f"Swarm attack: {total_drones} total drones",
                f"SAM damage: {sam_damage:.0f}%",
            ]
        )

        return report, engagement

    def _classify_target(self, target_unit) -> str:
        """Classify target for vulnerability."""
        if target_unit is None:
            return "logistics"

        unit_type = target_unit.unit_type.lower()

        if "radar" in unit_type:
            return "radar"
        elif "sam" in unit_type or "air_defense" in unit_type:
            return "sam_site"
        elif "artillery" in unit_type:
            return "artillery"
        elif "command" in unit_type or "hq" in unit_type:
            return "command_post"
        elif "armor" in unit_type:
            return "armor"
        elif "logistics" in unit_type:
            return "logistics"
        else:
            return "infantry"

    def _create_report(
        self,
        mission: DroneMission,
        result: CombatResult,
        engagement: DroneEngagement
    ) -> CombatReport:
        """Create combat report."""
        return CombatReport(
            attacker_id=mission.unit_id,
            defender_id=mission.target_id or "target",
            turn=0,
            phase="drone",
            result=result,
            attacker_losses={"drones": engagement.drones_lost},
            defender_losses={
                "destroyed": engagement.targets_destroyed,
                "damaged": engagement.targets_damaged,
            },
            notes=[
                f"Mission: {mission.mission_type}",
                f"Drones: {mission.drone_count} {mission.drone_type}",
            ]
        )
