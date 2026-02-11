"""
Base combat resolution system with common mechanics.
"""

import random
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class CombatResult(Enum):
    DECISIVE_VICTORY = "decisive_victory"
    VICTORY = "victory"
    MARGINAL = "marginal"
    STALEMATE = "stalemate"
    DEFEAT = "defeat"
    DECISIVE_DEFEAT = "decisive_defeat"


@dataclass
class CombatReport:
    """Report of a combat engagement."""
    attacker_id: str
    defender_id: str
    turn: int
    phase: str
    result: CombatResult
    attacker_losses: dict = field(default_factory=dict)
    defender_losses: dict = field(default_factory=dict)
    attacker_damage: float = 0.0
    defender_damage: float = 0.0
    location: Optional[tuple[int, int]] = None
    notes: list[str] = field(default_factory=list)


class CombatResolver:
    """Base class for combat resolution."""

    def __init__(self, rng_seed: Optional[int] = None):
        self.rng = random.Random(rng_seed)

    def roll(self, base: float, variance: float = 0.2) -> float:
        """Roll with variance around base value."""
        return base * (1.0 + self.rng.uniform(-variance, variance))

    def hit_check(self, hit_chance: float) -> bool:
        """Check if an attack hits."""
        return self.rng.random() < hit_chance

    def calculate_hit_chance(
        self,
        attacker_skill: float,
        defender_evasion: float,
        range_modifier: float = 1.0,
        weather_modifier: float = 1.0,
        ecm_modifier: float = 1.0
    ) -> float:
        """Calculate probability of hit."""
        base = attacker_skill / 100.0
        evasion = defender_evasion / 200.0  # Evasion halves effectiveness

        chance = base * (1.0 - evasion) * range_modifier * weather_modifier * ecm_modifier
        return max(0.05, min(0.95, chance))  # Clamp between 5% and 95%

    def calculate_damage(
        self,
        base_damage: float,
        armor: float = 0,
        critical_chance: float = 0.1
    ) -> float:
        """Calculate damage dealt."""
        # Armor reduces damage
        effective_damage = base_damage * (100 / (100 + armor))

        # Critical hit check
        if self.rng.random() < critical_chance:
            effective_damage *= 1.5

        return self.roll(effective_damage)

    def determine_result(self, attacker_score: float, defender_score: float) -> CombatResult:
        """Determine combat result from scores."""
        ratio = attacker_score / max(1, defender_score)

        if ratio >= 3.0:
            return CombatResult.DECISIVE_VICTORY
        elif ratio >= 1.5:
            return CombatResult.VICTORY
        elif ratio >= 1.1:
            return CombatResult.MARGINAL
        elif ratio >= 0.9:
            return CombatResult.STALEMATE
        elif ratio >= 0.67:
            return CombatResult.DEFEAT
        else:
            return CombatResult.DECISIVE_DEFEAT

    def apply_losses(self, unit, casualties: int, organization_loss: float):
        """Apply combat losses to a unit."""
        unit.take_losses(casualties, organization_loss)

    def calculate_suppression(self, firepower: float, target_concealment: float) -> float:
        """Calculate suppression effect."""
        base_suppression = firepower * 0.5
        concealment_reduction = target_concealment / 100.0 * 0.5
        return base_suppression * (1.0 - concealment_reduction)
