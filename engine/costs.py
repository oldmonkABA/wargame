"""
Cost-of-war economic tracking for wargame simulation.

Tracks procurement cost of destroyed/expended assets to compute
exchange ratios, ROI per weapon system, and cost-per-VP.
"""

import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CostLedger:
    """Running economic ledger for one faction."""
    assets_destroyed_usd: float = 0.0     # Cost of own assets lost
    assets_killed_usd: float = 0.0        # Cost of enemy assets destroyed
    munitions_expended_usd: float = 0.0   # Cost of ammo/missiles fired
    # Per-category breakdowns
    destroyed_by_category: dict = field(default_factory=dict)
    killed_by_category: dict = field(default_factory=dict)
    expended_by_type: dict = field(default_factory=dict)
    # Per-weapon-system kill tracking (weapon_type -> {kills, cost_destroyed})
    weapon_roi: dict = field(default_factory=dict)


@dataclass
class TurnCosts:
    """Cost data for a single turn."""
    india_destroyed: float = 0.0
    india_killed: float = 0.0
    india_expended: float = 0.0
    pakistan_destroyed: float = 0.0
    pakistan_killed: float = 0.0
    pakistan_expended: float = 0.0
    events: list = field(default_factory=list)


class CostTracker:
    """Loads cost data and tracks economic impact of combat."""

    def __init__(self, data_path: Path):
        self.costs = {}  # flat lookup: unit_type -> cost_usd (millions)
        self.india = CostLedger()
        self.pakistan = CostLedger()
        self.turn_costs: list[TurnCosts] = []
        self._load_costs(data_path)

    def _load_costs(self, data_path: Path):
        """Load cost database from YAML."""
        data_path = Path(data_path)
        cost_path = data_path / "schema" / "costs.yaml"
        if not cost_path.exists():
            logger.warning(f"Cost database not found: {cost_path}")
            return

        with open(cost_path) as f:
            data = yaml.safe_load(f) or {}

        # Flatten all categories into a single lookup
        for category, items in data.items():
            if isinstance(items, dict):
                for unit_type, cost in items.items():
                    if isinstance(cost, (int, float)):
                        self.costs[unit_type] = float(cost)

        logger.info(f"Loaded costs for {len(self.costs)} unit types")

    def _fuzzy_cost_lookup(self, type_str: str) -> float:
        """Look up cost with fuzzy matching (handles variants like mig21_bison -> mig21)."""
        if not type_str:
            return 0
        # Exact match first
        if type_str in self.costs:
            return self.costs[type_str]
        # Try prefix match (mig21_bison -> mig21)
        for cost_key in sorted(self.costs.keys(), key=len, reverse=True):
            if type_str.startswith(cost_key) or cost_key.startswith(type_str):
                return self.costs[cost_key]
        # Try substring match
        type_lower = type_str.lower().replace("-", "").replace(" ", "")
        for cost_key, cost_val in self.costs.items():
            key_lower = cost_key.lower().replace("-", "").replace(" ", "")
            if key_lower in type_lower or type_lower in key_lower:
                return cost_val
        return 0

    def get_unit_cost(self, unit) -> float:
        """Get the cost of a unit in millions USD.

        Tries multiple lookup strategies:
        1. Direct unit_type match (with fuzzy matching)
        2. type_data fields (missile_type, helicopter_type, etc.)
        3. AircraftSquadron special handling (aircraft_type attr)
        4. Category-based default
        """
        count = self._unit_count(unit)

        # Direct type match (fuzzy)
        cost = self._fuzzy_cost_lookup(unit.unit_type)
        if cost > 0:
            return cost * count

        # Check type_data for nested type references
        for key in ("missile_type", "helicopter_type", "aircraft_type",
                     "drone_type", "artillery_type", "sam_type", "type"):
            sub_type = unit.type_data.get(key)
            if sub_type:
                cost = self._fuzzy_cost_lookup(sub_type)
                if cost > 0:
                    return cost * count

        # AircraftSquadron has aircraft_type attribute
        if hasattr(unit, 'aircraft_type'):
            cost = self._fuzzy_cost_lookup(unit.aircraft_type)
            if cost > 0:
                return cost * count

        # Fallback: category defaults
        CATEGORY_DEFAULTS = {
            "aircraft": 40.0,
            "ground": 200.0,
            "artillery": 2.0,
            "helicopter": 20.0,
            "drone": 1.0,
            "missile": 3.0,
            "air_defense": 50.0,
            "special_forces": 0.5,
            "isr": 100.0,
        }
        cat = unit.category.value if hasattr(unit.category, 'value') else str(unit.category)
        default = CATEGORY_DEFAULTS.get(cat, 10.0)
        return default * count

    def _unit_count(self, unit) -> int:
        """Get the 'count' multiplier for a unit (e.g., squadron has multiple aircraft)."""
        # Check type_data for explicit counts
        for key in ("aircraft_count", "helicopter_count", "drone_count",
                     "launcher_count", "gun_count"):
            count = unit.type_data.get(key)
            if count and isinstance(count, (int, float)) and count > 1:
                return int(count)

        # For aircraft squadrons, strength_max = aircraft count
        cat = unit.category.value if hasattr(unit.category, 'value') else str(unit.category)
        if cat in ("aircraft", "helicopter", "drone", "artillery"):
            sm = unit.state.strength_max if hasattr(unit, 'state') else 1
            if sm > 1:
                return sm

        return 1

    def get_per_unit_cost(self, unit) -> float:
        """Get cost of a single sub-unit (one aircraft, one launcher, etc.)."""
        total = self.get_unit_cost(unit)
        count = self._unit_count(unit)
        return total / max(1, count)

    def get_munition_cost(self, unit_type: str, count: int = 1) -> float:
        """Get cost of expended munitions (missiles fired, etc.)."""
        cost = self.costs.get(unit_type, 0)
        return cost * count

    def record_unit_destroyed(self, unit, destroyed_by_faction: str):
        """Record a unit being destroyed."""
        cost = self.get_unit_cost(unit)
        faction = unit.faction.value if hasattr(unit.faction, 'value') else str(unit.faction)
        cat = unit.category.value if hasattr(unit.category, 'value') else str(unit.category)

        # The destroyed unit's faction takes the loss
        if faction == "india":
            self.india.assets_destroyed_usd += cost
            self.india.destroyed_by_category[cat] = (
                self.india.destroyed_by_category.get(cat, 0) + cost
            )
            # The opposing faction gets the kill credit
            self.pakistan.assets_killed_usd += cost
            self.pakistan.killed_by_category[cat] = (
                self.pakistan.killed_by_category.get(cat, 0) + cost
            )
        else:
            self.pakistan.assets_destroyed_usd += cost
            self.pakistan.destroyed_by_category[cat] = (
                self.pakistan.destroyed_by_category.get(cat, 0) + cost
            )
            self.india.assets_killed_usd += cost
            self.india.killed_by_category[cat] = (
                self.india.killed_by_category.get(cat, 0) + cost
            )

    def record_losses(self, unit, losses_count: int, attacker_type: str = ""):
        """Record partial losses (e.g., 3 aircraft lost from a squadron)."""
        per_unit = self.get_per_unit_cost(unit)
        cost = per_unit * losses_count
        faction = unit.faction.value if hasattr(unit.faction, 'value') else str(unit.faction)
        cat = unit.category.value if hasattr(unit.category, 'value') else str(unit.category)

        if faction == "india":
            self.india.assets_destroyed_usd += cost
            self.india.destroyed_by_category[cat] = (
                self.india.destroyed_by_category.get(cat, 0) + cost
            )
            self.pakistan.assets_killed_usd += cost
            self.pakistan.killed_by_category[cat] = (
                self.pakistan.killed_by_category.get(cat, 0) + cost
            )
        else:
            self.pakistan.assets_destroyed_usd += cost
            self.pakistan.destroyed_by_category[cat] = (
                self.pakistan.destroyed_by_category.get(cat, 0) + cost
            )
            self.india.assets_killed_usd += cost
            self.india.killed_by_category[cat] = (
                self.india.killed_by_category.get(cat, 0) + cost
            )

        # Track weapon ROI
        if attacker_type:
            if attacker_type not in (self.india.weapon_roi if faction != "india" else self.pakistan.weapon_roi):
                roi_ledger = self.india.weapon_roi if faction != "india" else self.pakistan.weapon_roi
                if attacker_type not in roi_ledger:
                    roi_ledger[attacker_type] = {"kills": 0, "cost_destroyed": 0.0}
                roi_ledger[attacker_type]["kills"] += losses_count
                roi_ledger[attacker_type]["cost_destroyed"] += cost

    def record_munitions_expended(self, faction: str, munition_type: str, count: int):
        """Record munitions fired (missiles, bombs, etc.)."""
        cost = self.get_munition_cost(munition_type, count)
        ledger = self.india if faction == "india" else self.pakistan
        ledger.munitions_expended_usd += cost
        ledger.expended_by_type[munition_type] = (
            ledger.expended_by_type.get(munition_type, 0) + cost
        )

    def process_combat_reports(self, reports: list, units_manager):
        """Process combat reports from a turn to extract cost data.

        This is the main integration point - called after each turn's combat.
        Extracts losses from report dicts and computes costs.
        """
        turn_costs = TurnCosts()

        for report in reports:
            r = report if isinstance(report, dict) else report.__dict__

            attacker_id = r.get("attacker_id", "")
            defender_id = r.get("defender_id", "")
            attacker = units_manager.get_unit(attacker_id)
            defender = units_manager.get_unit(defender_id)

            attacker_losses = r.get("attacker_losses", {})
            defender_losses = r.get("defender_losses", {})

            event_cost = {
                "phase": r.get("phase", ""),
                "attacker": attacker_id,
                "defender": defender_id,
            }

            # Process attacker losses (aircraft lost, etc.)
            att_loss_cost = 0.0
            if attacker:
                att_faction = attacker.faction.value
                for loss_key in ("aircraft", "helicopters", "drones"):
                    count = attacker_losses.get(loss_key, 0)
                    if count > 0:
                        self.record_losses(attacker, int(count),
                                           defender.unit_type if defender else "")
                        att_loss_cost += self.get_per_unit_cost(attacker) * count

                # Missiles fired = munitions expended
                missiles_fired = attacker_losses.get("missiles_fired", 0)
                if missiles_fired > 0 and attacker:
                    mtype = attacker.type_data.get("missile_type", attacker.unit_type)
                    self.record_munitions_expended(att_faction, mtype, missiles_fired)
                    att_loss_cost += self.get_munition_cost(mtype, missiles_fired)

            # Process defender losses
            def_loss_cost = 0.0
            if defender:
                def_faction = defender.faction.value
                for loss_key in ("aircraft", "helicopters", "drones"):
                    count = defender_losses.get(loss_key, 0)
                    if count > 0:
                        self.record_losses(defender, int(count),
                                           attacker.unit_type if attacker else "")
                        def_loss_cost += self.get_per_unit_cost(defender) * count

                # Damage-based cost (proportional to damage dealt)
                damage = defender_losses.get("damage", defender_losses.get("damage_taken", 0))
                if damage and isinstance(damage, (int, float)) and damage > 0:
                    # Damage as fraction of total unit value
                    unit_cost = self.get_unit_cost(defender)
                    damage_frac = min(1.0, damage / 100.0)
                    damage_cost = unit_cost * damage_frac
                    def_loss_cost += damage_cost

            # Accumulate turn costs
            if attacker:
                att_f = attacker.faction.value
                if att_f == "india":
                    turn_costs.india_destroyed += att_loss_cost
                    turn_costs.india_killed += def_loss_cost
                else:
                    turn_costs.pakistan_destroyed += att_loss_cost
                    turn_costs.pakistan_killed += def_loss_cost

            event_cost["attacker_cost_usd"] = round(att_loss_cost, 2)
            event_cost["defender_cost_usd"] = round(def_loss_cost, 2)
            turn_costs.events.append(event_cost)

        self.turn_costs.append(turn_costs)
        return turn_costs

    def compute_initial_oob_value(self, units_manager) -> dict:
        """Compute total OOB value per faction at game start."""
        india_total = 0.0
        pakistan_total = 0.0
        for uid, unit in units_manager.units.items():
            cost = self.get_unit_cost(unit)
            faction = unit.faction.value if hasattr(unit.faction, 'value') else str(unit.faction)
            if faction == "india":
                india_total += cost
            else:
                pakistan_total += cost
        return {
            "india_oob_value": round(india_total, 1),
            "pakistan_oob_value": round(pakistan_total, 1),
        }

    def get_summary(self) -> dict:
        """Get full economic summary for end-of-game reporting."""
        india_total_spent = self.india.assets_destroyed_usd + self.india.munitions_expended_usd
        pak_total_spent = self.pakistan.assets_destroyed_usd + self.pakistan.munitions_expended_usd

        # Build per-turn cost timeline
        turn_timeline = []
        for i, tc in enumerate(self.turn_costs):
            turn_timeline.append({
                "turn": i + 1,
                "india_destroyed": round(tc.india_destroyed, 1),
                "india_killed": round(tc.india_killed, 1),
                "pakistan_destroyed": round(tc.pakistan_destroyed, 1),
                "pakistan_killed": round(tc.pakistan_killed, 1),
            })

        return {
            "turn_timeline": turn_timeline,
            "india": {
                "assets_lost_usd": round(self.india.assets_destroyed_usd, 1),
                "assets_killed_usd": round(self.india.assets_killed_usd, 1),
                "munitions_expended_usd": round(self.india.munitions_expended_usd, 1),
                "total_cost_of_war_usd": round(india_total_spent, 1),
                "exchange_ratio": round(
                    self.india.assets_killed_usd / max(0.1, india_total_spent), 2
                ),
                "destroyed_by_category": {
                    k: round(v, 1) for k, v in self.india.destroyed_by_category.items()
                },
                "killed_by_category": {
                    k: round(v, 1) for k, v in self.india.killed_by_category.items()
                },
                "munitions_by_type": {
                    k: round(v, 1) for k, v in self.india.expended_by_type.items()
                },
                "weapon_roi": self.india.weapon_roi,
            },
            "pakistan": {
                "assets_lost_usd": round(self.pakistan.assets_destroyed_usd, 1),
                "assets_killed_usd": round(self.pakistan.assets_killed_usd, 1),
                "munitions_expended_usd": round(self.pakistan.munitions_expended_usd, 1),
                "total_cost_of_war_usd": round(pak_total_spent, 1),
                "exchange_ratio": round(
                    self.pakistan.assets_killed_usd / max(0.1, pak_total_spent), 2
                ),
                "destroyed_by_category": {
                    k: round(v, 1) for k, v in self.pakistan.destroyed_by_category.items()
                },
                "killed_by_category": {
                    k: round(v, 1) for k, v in self.pakistan.killed_by_category.items()
                },
                "munitions_by_type": {
                    k: round(v, 1) for k, v in self.pakistan.expended_by_type.items()
                },
                "weapon_roi": self.pakistan.weapon_roi,
            },
        }

    def get_turn_snapshot(self) -> dict:
        """Get cumulative cost data for current turn snapshot."""
        return {
            "india_cost_destroyed": round(self.india.assets_destroyed_usd, 1),
            "india_cost_killed": round(self.india.assets_killed_usd, 1),
            "india_munitions_usd": round(self.india.munitions_expended_usd, 1),
            "pakistan_cost_destroyed": round(self.pakistan.assets_destroyed_usd, 1),
            "pakistan_cost_killed": round(self.pakistan.assets_killed_usd, 1),
            "pakistan_munitions_usd": round(self.pakistan.munitions_expended_usd, 1),
            "india_exchange_ratio": round(
                self.india.assets_killed_usd / max(0.1,
                    self.india.assets_destroyed_usd + self.india.munitions_expended_usd), 2
            ),
            "pakistan_exchange_ratio": round(
                self.pakistan.assets_killed_usd / max(0.1,
                    self.pakistan.assets_destroyed_usd + self.pakistan.munitions_expended_usd), 2
            ),
        }
