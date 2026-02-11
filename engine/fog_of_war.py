"""
Fog of War and intelligence system for wargame simulation.

Handles:
- Unit detection and tracking
- Intelligence gathering
- Information decay
- Reconnaissance
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import random


class IntelQuality(Enum):
    NONE = "none"
    SUSPECTED = "suspected"  # Something is there
    DETECTED = "detected"  # Unit type known
    IDENTIFIED = "identified"  # Unit ID and approximate strength
    CONFIRMED = "confirmed"  # Accurate current information


@dataclass
class IntelReport:
    """Intelligence report on an enemy unit."""
    unit_id: str
    faction: str
    quality: IntelQuality
    last_updated: int  # Turn number
    reported_location: Optional[tuple[int, int]] = None
    reported_type: Optional[str] = None
    reported_strength: Optional[int] = None
    confidence: float = 0.5  # 0-1
    source: str = "unknown"  # "visual", "sigint", "humint", "isr", "satellite"


@dataclass
class SensorCoverage:
    """Sensor coverage for detection."""
    sensor_id: str
    sensor_type: str  # "radar", "visual", "sigint", "satellite"
    location: tuple[int, int]
    range_hexes: int
    detection_rating: float  # 0-100
    identification_rating: float  # 0-100
    active: bool = True


class FogOfWar:
    """Manages fog of war and intelligence for both factions."""

    # Detection modifiers by terrain
    TERRAIN_DETECTION_MOD = {
        "plains": 1.0,
        "hills": 0.7,
        "mountain": 0.5,
        "forest": 0.4,
        "urban": 0.6,
        "desert": 1.1,
        "marsh": 0.7,
    }

    # Unit size visibility
    UNIT_SIZE_VISIBILITY = {
        "brigade": 1.0,
        "division": 1.2,
        "corps": 1.4,
        "battalion": 0.8,
        "company": 0.6,
        "squad": 0.3,
    }

    # Intel decay per turn (quality degrades)
    INTEL_DECAY = {
        IntelQuality.CONFIRMED: IntelQuality.IDENTIFIED,
        IntelQuality.IDENTIFIED: IntelQuality.DETECTED,
        IntelQuality.DETECTED: IntelQuality.SUSPECTED,
        IntelQuality.SUSPECTED: IntelQuality.NONE,
    }

    def __init__(self, rng_seed: Optional[int] = None):
        self.rng = random.Random(rng_seed)

        # Intel databases for each faction (what they know about enemy)
        self.india_intel: dict[str, IntelReport] = {}
        self.pakistan_intel: dict[str, IntelReport] = {}

        # Sensor coverage
        self.india_sensors: list[SensorCoverage] = []
        self.pakistan_sensors: list[SensorCoverage] = []

    def get_faction_intel(self, faction: str) -> dict[str, IntelReport]:
        """Get intel database for a faction."""
        return self.india_intel if faction == "india" else self.pakistan_intel

    def get_faction_sensors(self, faction: str) -> list[SensorCoverage]:
        """Get sensors for a faction."""
        return self.india_sensors if faction == "india" else self.pakistan_sensors

    def process_detection_turn(
        self,
        observing_faction: str,
        enemy_units: list,
        hex_map,
        current_turn: int,
    ) -> list[IntelReport]:
        """Process detection for one turn, update intel."""
        intel_db = self.get_faction_intel(observing_faction)
        sensors = self.get_faction_sensors(observing_faction)
        friendly_units = []  # Would be passed in

        new_reports = []

        for enemy in enemy_units:
            if not enemy.location.hex_q or not enemy.location.hex_r:
                continue

            enemy_loc = (enemy.location.hex_q, enemy.location.hex_r)
            cell = hex_map.get_cell(*enemy_loc)
            terrain = cell.terrain.value if cell else "plains"

            # Get terrain and concealment modifiers
            terrain_mod = self.TERRAIN_DETECTION_MOD.get(terrain, 1.0)
            concealment = hex_map.get_concealment(cell) if cell else 30

            # Unit's own concealment efforts
            unit_concealment = 1.0 - (enemy.state.dug_in * 0.15)

            # Check each sensor
            best_detection = IntelQuality.NONE
            best_confidence = 0.0
            source = "unknown"

            for sensor in sensors:
                if not sensor.active:
                    continue

                # Range check
                distance = hex_map.hex_distance(
                    sensor.location[0], sensor.location[1],
                    enemy_loc[0], enemy_loc[1]
                )

                if distance > sensor.range_hexes:
                    continue

                # Detection calculation
                range_factor = 1.0 - (distance / sensor.range_hexes) * 0.5
                detection_chance = (
                    sensor.detection_rating / 100.0 *
                    range_factor *
                    terrain_mod *
                    unit_concealment *
                    (1.0 - concealment / 200.0)
                )

                if self.rng.random() < detection_chance:
                    # Detected - now check identification
                    id_chance = (
                        sensor.identification_rating / 100.0 *
                        range_factor *
                        terrain_mod
                    )

                    if self.rng.random() < id_chance * 0.5:
                        quality = IntelQuality.CONFIRMED
                        confidence = 0.9
                    elif self.rng.random() < id_chance:
                        quality = IntelQuality.IDENTIFIED
                        confidence = 0.7
                    else:
                        quality = IntelQuality.DETECTED
                        confidence = 0.5

                    if quality.value > best_detection.value or confidence > best_confidence:
                        best_detection = quality
                        best_confidence = confidence
                        source = sensor.sensor_type

            # Update or create intel report
            if best_detection != IntelQuality.NONE:
                report = IntelReport(
                    unit_id=enemy.id,
                    faction=enemy.faction.value,
                    quality=best_detection,
                    last_updated=current_turn,
                    reported_location=enemy_loc,
                    reported_type=enemy.unit_type if best_detection.value >= IntelQuality.DETECTED.value else None,
                    reported_strength=self._estimate_strength(enemy, best_confidence) if best_detection.value >= IntelQuality.IDENTIFIED.value else None,
                    confidence=best_confidence,
                    source=source,
                )

                # Only update if better than existing
                existing = intel_db.get(enemy.id)
                if not existing or report.quality.value >= existing.quality.value:
                    intel_db[enemy.id] = report
                    new_reports.append(report)

        return new_reports

    def decay_intel(self, faction: str, current_turn: int):
        """Decay old intelligence."""
        intel_db = self.get_faction_intel(faction)
        to_remove = []

        for unit_id, report in intel_db.items():
            turns_old = current_turn - report.last_updated

            # Decay based on age
            if turns_old >= 4:  # Very old
                new_quality = self.INTEL_DECAY.get(report.quality, IntelQuality.NONE)
                if new_quality == IntelQuality.NONE:
                    to_remove.append(unit_id)
                else:
                    report.quality = new_quality
                    report.confidence *= 0.8

            elif turns_old >= 2:  # Moderately old
                report.confidence *= 0.9

        for unit_id in to_remove:
            del intel_db[unit_id]

    def _estimate_strength(self, unit, confidence: float) -> int:
        """Estimate unit strength with some error."""
        actual = unit.state.strength_current
        error = 1.0 + (1.0 - confidence) * self.rng.uniform(-0.3, 0.3)
        return int(actual * error)

    def add_sensor(
        self,
        faction: str,
        sensor: SensorCoverage,
    ):
        """Add a sensor to faction's coverage."""
        sensors = self.get_faction_sensors(faction)
        sensors.append(sensor)

    def remove_sensor(self, faction: str, sensor_id: str):
        """Remove a sensor (destroyed/moved)."""
        sensors = self.get_faction_sensors(faction)
        sensors[:] = [s for s in sensors if s.sensor_id != sensor_id]

    def add_manual_intel(
        self,
        faction: str,
        report: IntelReport,
    ):
        """Add intel from external source (HUMINT, allied sharing, etc.)."""
        intel_db = self.get_faction_intel(faction)
        existing = intel_db.get(report.unit_id)

        if not existing or report.quality.value > existing.quality.value:
            intel_db[report.unit_id] = report

    def get_known_enemies(
        self,
        faction: str,
        min_quality: IntelQuality = IntelQuality.SUSPECTED,
    ) -> list[IntelReport]:
        """Get all known enemy units above quality threshold."""
        intel_db = self.get_faction_intel(faction)
        return [
            report for report in intel_db.values()
            if report.quality.value >= min_quality.value
        ]

    def get_unit_intel(
        self,
        faction: str,
        unit_id: str,
    ) -> Optional[IntelReport]:
        """Get intel on a specific enemy unit."""
        intel_db = self.get_faction_intel(faction)
        return intel_db.get(unit_id)

    def is_unit_detected(
        self,
        observing_faction: str,
        unit_id: str,
    ) -> bool:
        """Check if a unit is detected by the observing faction."""
        intel_db = self.get_faction_intel(observing_faction)
        report = intel_db.get(unit_id)
        return report is not None and report.quality.value >= IntelQuality.DETECTED.value

    def get_visible_state(
        self,
        faction: str,
        all_units: list,
        hex_map,
    ) -> dict:
        """Get game state as visible to a faction (for agent)."""
        intel_db = self.get_faction_intel(faction)

        visible_state = {
            "own_units": [],
            "known_enemies": [],
            "suspected_enemies": [],
        }

        for unit in all_units:
            if unit.faction.value == faction:
                # Full visibility of own units
                visible_state["own_units"].append({
                    "id": unit.id,
                    "type": unit.unit_type,
                    "location": (unit.location.hex_q, unit.location.hex_r),
                    "strength": unit.state.strength_current,
                    "status": unit.status.value,
                    "supply": unit.state.supply_level,
                })
            else:
                # Enemy unit - check what we know
                report = intel_db.get(unit.id)
                if report:
                    enemy_info = {
                        "id": unit.id,
                        "intel_quality": report.quality.value,
                        "confidence": report.confidence,
                        "last_seen_turn": report.last_updated,
                    }

                    if report.reported_location:
                        enemy_info["location"] = report.reported_location
                    if report.reported_type:
                        enemy_info["type"] = report.reported_type
                    if report.reported_strength:
                        enemy_info["estimated_strength"] = report.reported_strength

                    if report.quality.value >= IntelQuality.DETECTED.value:
                        visible_state["known_enemies"].append(enemy_info)
                    else:
                        visible_state["suspected_enemies"].append(enemy_info)

        return visible_state

    def create_awacs_sensor(
        self,
        sensor_id: str,
        location: tuple[int, int],
    ) -> SensorCoverage:
        """Create AWACS-type sensor."""
        return SensorCoverage(
            sensor_id=sensor_id,
            sensor_type="radar",
            location=location,
            range_hexes=40,  # ~400km
            detection_rating=90,
            identification_rating=75,
        )

    def create_ground_radar(
        self,
        sensor_id: str,
        location: tuple[int, int],
    ) -> SensorCoverage:
        """Create ground-based radar sensor."""
        return SensorCoverage(
            sensor_id=sensor_id,
            sensor_type="radar",
            location=location,
            range_hexes=20,
            detection_rating=80,
            identification_rating=60,
        )

    def create_recon_coverage(
        self,
        sensor_id: str,
        location: tuple[int, int],
        range_hexes: int = 3,
    ) -> SensorCoverage:
        """Create visual/recon sensor coverage."""
        return SensorCoverage(
            sensor_id=sensor_id,
            sensor_type="visual",
            location=location,
            range_hexes=range_hexes,
            detection_rating=70,
            identification_rating=80,
        )

    def get_intel_summary(self, faction: str) -> dict:
        """Get summary of intel for a faction."""
        intel_db = self.get_faction_intel(faction)

        quality_counts = {q.value: 0 for q in IntelQuality}
        for report in intel_db.values():
            quality_counts[report.quality.value] += 1

        return {
            "total_tracked": len(intel_db),
            "by_quality": quality_counts,
            "avg_confidence": sum(r.confidence for r in intel_db.values()) / max(1, len(intel_db)),
        }
