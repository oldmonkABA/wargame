"""
Air combat resolution - air superiority and strike missions.

Handles:
- BVR (Beyond Visual Range) engagements
- WVR (Within Visual Range) dogfights
- Air-to-ground strikes
- SEAD (Suppression of Enemy Air Defense)
"""

from dataclasses import dataclass, field
from typing import Optional
from .base import CombatResolver, CombatReport, CombatResult


@dataclass
class AirMission:
    """An air mission being executed."""
    squadron_id: str
    mission_type: str  # "cap", "sweep", "escort", "strike", "sead", "cas"
    aircraft_count: int
    aircraft_type: str
    target_id: Optional[str] = None
    target_location: Optional[tuple[int, int]] = None
    loadout: list[str] = field(default_factory=list)


@dataclass
class AirEngagement:
    """Result of an air-to-air engagement."""
    attacker_losses: int
    defender_losses: int
    attacker_damaged: int
    defender_damaged: int
    attacker_rtb: int  # Returned to base (winchester/damaged)
    defender_rtb: int


class AirCombat(CombatResolver):
    """Resolves air combat engagements."""

    # BVR missile effectiveness
    BVR_MISSILES = {
        "meteor": {"range": 150, "pk": 0.85, "eccm": 90},
        "aim120": {"range": 105, "pk": 0.75, "eccm": 80},
        "r77": {"range": 80, "pk": 0.70, "eccm": 70},
        "pl15": {"range": 200, "pk": 0.80, "eccm": 85},
        "mica": {"range": 80, "pk": 0.78, "eccm": 75},
        "derby": {"range": 50, "pk": 0.70, "eccm": 65},
    }

    # WVR missile effectiveness
    WVR_MISSILES = {
        "aim9x": {"pk": 0.90, "agility": 95},
        "r73": {"pk": 0.85, "agility": 90},
        "python5": {"pk": 0.90, "agility": 92},
        "pl10": {"pk": 0.88, "agility": 90},
        "asraam": {"pk": 0.88, "agility": 88},
        "mica_ir": {"pk": 0.85, "agility": 85},
    }

    def resolve_air_to_air(
        self,
        attacker: AirMission,
        defender: AirMission,
        attacker_stats: dict,
        defender_stats: dict,
        weather_modifier: float = 1.0,
    ) -> tuple[CombatReport, AirEngagement]:
        """Resolve air-to-air combat between formations."""

        # Phase 1: BVR engagement
        bvr_result = self._resolve_bvr(
            attacker, defender,
            attacker_stats, defender_stats,
            weather_modifier
        )

        # Remaining aircraft after BVR
        attacker_remaining = attacker.aircraft_count - bvr_result["attacker_losses"]
        defender_remaining = defender.aircraft_count - bvr_result["defender_losses"]

        wvr_result = {"attacker_losses": 0, "defender_losses": 0,
                      "attacker_damaged": 0, "defender_damaged": 0}

        # Phase 2: WVR if both sides have aircraft and want to merge
        if attacker_remaining > 0 and defender_remaining > 0:
            # Simplified: WVR engagement
            wvr_result = self._resolve_wvr(
                attacker_remaining, defender_remaining,
                attacker_stats, defender_stats,
                weather_modifier
            )

        total_attacker_losses = bvr_result["attacker_losses"] + wvr_result["attacker_losses"]
        total_defender_losses = bvr_result["defender_losses"] + wvr_result["defender_losses"]

        # Cap to actual aircraft counts
        total_attacker_losses = min(total_attacker_losses, attacker.aircraft_count)
        total_defender_losses = min(total_defender_losses, defender.aircraft_count)

        # Determine result
        attacker_score = total_defender_losses * 10
        defender_score = total_attacker_losses * 10
        result = self.determine_result(attacker_score + 1, defender_score + 1)

        engagement = AirEngagement(
            attacker_losses=total_attacker_losses,
            defender_losses=total_defender_losses,
            attacker_damaged=wvr_result.get("attacker_damaged", 0),
            defender_damaged=wvr_result.get("defender_damaged", 0),
            attacker_rtb=bvr_result.get("attacker_winchester", 0),
            defender_rtb=bvr_result.get("defender_winchester", 0),
        )

        report = CombatReport(
            attacker_id=attacker.squadron_id,
            defender_id=defender.squadron_id,
            turn=0,
            phase="air",
            result=result,
            attacker_losses={"aircraft": total_attacker_losses},
            defender_losses={"aircraft": total_defender_losses},
            notes=[
                f"BVR: Attacker lost {bvr_result['attacker_losses']}, Defender lost {bvr_result['defender_losses']}",
                f"WVR: Attacker lost {wvr_result['attacker_losses']}, Defender lost {wvr_result['defender_losses']}",
            ]
        )

        return report, engagement

    def _resolve_bvr(
        self,
        attacker: AirMission,
        defender: AirMission,
        attacker_stats: dict,
        defender_stats: dict,
        weather_modifier: float
    ) -> dict:
        """Resolve BVR phase of air combat."""

        result = {
            "attacker_losses": 0, "defender_losses": 0,
            "attacker_winchester": 0, "defender_winchester": 0
        }

        # Radar advantage
        attacker_radar = attacker_stats.get("radar", 70)
        defender_radar = defender_stats.get("radar", 70)

        # EW suite (jamming/countermeasures)
        attacker_ew = attacker_stats.get("ew_suite", 50)
        defender_ew = defender_stats.get("ew_suite", 50)

        # Stealth factor
        attacker_stealth = attacker_stats.get("stealth", 15)
        defender_stealth = defender_stats.get("stealth", 15)

        # Detection ranges (who shoots first)
        attacker_detects = (attacker_radar - defender_stealth) / 100.0
        defender_detects = (defender_radar - attacker_stealth) / 100.0

        # Standoff / first-look: side with better radar can engage from BVR before the other
        # can effectively respond (e.g. Rafale from own airspace, defender still closing).
        if attacker_detects > defender_detects:
            # Attacker has first look — gets 1–2 standoff salvos (only attacker shoots)
            standoff_salvos = 2 if attacker_detects >= defender_detects * 1.5 else 1
            for _ in range(standoff_salvos):
                att_remaining = attacker.aircraft_count - result["attacker_losses"]
                def_remaining = defender.aircraft_count - result["defender_losses"]
                if att_remaining <= 0 or def_remaining <= 0:
                    break
                missiles = min(2, att_remaining)
                for _ in range(missiles):
                    if result["defender_losses"] >= defender.aircraft_count:
                        break
                    base_pk = 0.75
                    pk = base_pk * attacker_detects * (1.0 - defender_ew / 200.0) * weather_modifier
                    if self.hit_check(pk):
                        result["defender_losses"] += 1
        elif defender_detects > attacker_detects:
            # Defender has first look — gets 1–2 standoff salvos (only defender shoots)
            standoff_salvos = 2 if defender_detects >= attacker_detects * 1.5 else 1
            for _ in range(standoff_salvos):
                att_remaining = attacker.aircraft_count - result["attacker_losses"]
                def_remaining = defender.aircraft_count - result["defender_losses"]
                if att_remaining <= 0 or def_remaining <= 0:
                    break
                missiles = min(2, def_remaining)
                for _ in range(missiles):
                    if result["attacker_losses"] >= attacker.aircraft_count:
                        break
                    base_pk = 0.75
                    pk = base_pk * defender_detects * (1.0 - attacker_ew / 200.0) * weather_modifier
                    if self.hit_check(pk):
                        result["attacker_losses"] += 1

        # BVR exchanges (mutual: 2 salvos each, both sides can shoot)
        for salvo in range(2):
            att_remaining = attacker.aircraft_count - result["attacker_losses"]
            def_remaining = defender.aircraft_count - result["defender_losses"]

            if att_remaining <= 0 or def_remaining <= 0:
                break

            # Attacker salvo
            missiles = min(2, att_remaining)
            for _ in range(missiles):
                if result["defender_losses"] >= defender.aircraft_count:
                    break
                base_pk = 0.75  # Average BVR PK
                pk = base_pk * attacker_detects * (1.0 - defender_ew / 200.0) * weather_modifier
                if self.hit_check(pk):
                    result["defender_losses"] += 1

            # Defender salvo
            missiles = min(2, def_remaining)
            for _ in range(missiles):
                if result["attacker_losses"] >= attacker.aircraft_count:
                    break
                base_pk = 0.75
                pk = base_pk * defender_detects * (1.0 - attacker_ew / 200.0) * weather_modifier
                if self.hit_check(pk):
                    result["attacker_losses"] += 1

        # Cap losses to actual aircraft count
        result["attacker_losses"] = min(result["attacker_losses"], attacker.aircraft_count)
        result["defender_losses"] = min(result["defender_losses"], defender.aircraft_count)

        return result

    def _resolve_wvr(
        self,
        attacker_count: int,
        defender_count: int,
        attacker_stats: dict,
        defender_stats: dict,
        weather_modifier: float
    ) -> dict:
        """Resolve WVR dogfight phase."""

        result = {
            "attacker_losses": 0, "defender_losses": 0,
            "attacker_damaged": 0, "defender_damaged": 0
        }

        # Air-to-air rating (dogfight skill)
        attacker_a2a = attacker_stats.get("air_to_air", 70)
        defender_a2a = defender_stats.get("air_to_air", 70)

        # Speed/maneuverability factor
        attacker_speed = attacker_stats.get("speed", 75)
        defender_speed = defender_stats.get("speed", 75)

        # Combat rounds
        rounds = min(3, max(attacker_count, defender_count))

        for _ in range(rounds):
            remaining_att = attacker_count - result["attacker_losses"]
            remaining_def = defender_count - result["defender_losses"]

            if remaining_att <= 0 or remaining_def <= 0:
                break

            # Attacker shots
            att_pk = (attacker_a2a / 100.0) * (attacker_speed / defender_speed) * 0.3 * weather_modifier
            for _ in range(remaining_att):
                if result["defender_losses"] >= defender_count:
                    break
                if self.hit_check(att_pk):
                    if self.hit_check(0.7):  # Kill vs damage
                        result["defender_losses"] += 1
                    else:
                        result["defender_damaged"] += 1

            # Defender shots
            def_pk = (defender_a2a / 100.0) * (defender_speed / attacker_speed) * 0.3 * weather_modifier
            for _ in range(remaining_def):
                if result["attacker_losses"] >= attacker_count:
                    break
                if self.hit_check(def_pk):
                    if self.hit_check(0.7):
                        result["attacker_losses"] += 1
                    else:
                        result["attacker_damaged"] += 1

        # Final cap
        result["attacker_losses"] = min(result["attacker_losses"], attacker_count)
        result["defender_losses"] = min(result["defender_losses"], defender_count)

        return result

    def resolve_strike(
        self,
        striker: AirMission,
        striker_stats: dict,
        target_type: str,
        target_defense: float,
        sam_coverage: list,
        weather_modifier: float = 1.0,
    ) -> CombatReport:
        """Resolve air-to-ground strike mission."""

        aircraft_count = striker.aircraft_count
        losses_to_sam = 0

        # Phase 1: SAM engagement during ingress
        # Aircraft with standoff weapons (SCALP, BrahMos-A, Kh-59, Ra'ad, HAMMER)
        # launch from outside SAM range and never enter the engagement zone.
        # Only aircraft doing direct overfly attacks face SAMs.
        STANDOFF_WEAPONS = {"scalp", "storm_shadow", "brahmos_air", "kh59", "hammer",
                            "raad", "harpoon"}
        aircraft_weapons = set(striker_stats.get("weapons", []))
        has_standoff = bool(aircraft_weapons & STANDOFF_WEAPONS)

        if not has_standoff:
            # Legacy strike (Jaguar, MiG-21, etc.) — must penetrate SAM zone
            for sam in sam_coverage:
                if aircraft_count <= 0:
                    break

                sam_effectiveness = sam.get("effectiveness", 0.3)
                sam_rounds = sam.get("rounds", 8)

                # 1 engagement per aircraft per SAM battery
                engagements = min(sam_rounds // 2, aircraft_count)
                engagements = min(engagements, aircraft_count)

                for _ in range(engagements):
                    pk = sam_effectiveness * weather_modifier
                    pk *= (1.0 - striker_stats.get("ew_suite", 50) / 200.0)
                    stealth = striker_stats.get("stealth", 15)
                    pk *= (1.0 - stealth / 200.0)

                    if self.hit_check(pk):
                        losses_to_sam += 1
                        aircraft_count -= 1
        # else: standoff launch — aircraft stays outside SAM envelope, zero SAM exposure

        # Phase 2: Strike delivery
        remaining = striker.aircraft_count - losses_to_sam
        ground_attack = striker_stats.get("ground_attack", 70)

        hits = 0
        total_damage = 0.0

        for _ in range(remaining):
            # Each aircraft delivers ordnance
            hit_chance = (ground_attack / 100.0) * weather_modifier
            if self.hit_check(hit_chance):
                hits += 1
                damage = self.roll(ground_attack * 0.5, variance=0.25)
                total_damage += damage

        # Result based on damage vs target defense
        effectiveness = total_damage / max(1, target_defense)

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
            attacker_id=striker.squadron_id,
            defender_id=striker.target_id or "ground_target",
            turn=0,
            phase="air_strike",
            result=result,
            attacker_losses={"aircraft": losses_to_sam},
            defender_losses={"damage": total_damage},
            attacker_damage=0,
            defender_damage=total_damage,
            notes=[
                f"Strike force: {striker.aircraft_count}, Lost to SAM: {losses_to_sam}",
                f"Delivered: {remaining} aircraft, Hits: {hits}",
                f"Total damage: {total_damage:.1f}",
            ]
        )

        return report

    def resolve_sead(
        self,
        striker: AirMission,
        striker_stats: dict,
        target_sam: dict,
        escort_count: int = 0,
    ) -> CombatReport:
        """Resolve SEAD mission against air defense."""

        # SEAD aircraft have ARM (Anti-Radiation Missiles)
        aircraft_count = striker.aircraft_count
        sam_rounds = target_sam.get("rounds", 20)
        sam_effectiveness = target_sam.get("effectiveness", 0.3)

        losses = 0
        sam_damage = 0.0

        # SAM shoots at SEAD aircraft — 1 engagement per aircraft
        engagements = min(sam_rounds // 2, aircraft_count)
        engagements = min(engagements, aircraft_count)
        for _ in range(engagements):
            pk = sam_effectiveness * (1.0 - striker_stats.get("ew_suite", 50) / 200.0)
            pk *= (1.0 - striker_stats.get("stealth", 15) / 200.0)
            if self.hit_check(pk):
                losses += 1
                aircraft_count -= 1

        # SEAD aircraft fire ARMs
        remaining = striker.aircraft_count - losses
        for _ in range(remaining):
            # ARM effectiveness
            arm_pk = 0.65 * (striker_stats.get("radar", 70) / 100.0)
            if self.hit_check(arm_pk):
                sam_damage += self.roll(40, 0.2)

        # Assess SAM damage
        if sam_damage >= 80:
            result = CombatResult.DECISIVE_VICTORY
        elif sam_damage >= 50:
            result = CombatResult.VICTORY
        elif sam_damage >= 25:
            result = CombatResult.MARGINAL
        else:
            result = CombatResult.STALEMATE

        report = CombatReport(
            attacker_id=striker.squadron_id,
            defender_id=target_sam.get("id", "sam_site"),
            turn=0,
            phase="sead",
            result=result,
            attacker_losses={"aircraft": losses},
            defender_losses={"damage": sam_damage},
            notes=[
                f"SEAD aircraft: {striker.aircraft_count}, Lost: {losses}",
                f"SAM damage: {sam_damage:.1f}%",
            ]
        )

        return report
