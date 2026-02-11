"""
Wargame simulation engine for India-Pakistan conventional conflict.

Core modules:
- map: Hex grid terrain system
- units: Unit state management
- combat/: Domain-specific combat resolution
- turn: Turn sequencing and phase management
- logistics: Supply and attrition
- fog_of_war: Visibility and information
"""

from .map import HexMap, HexCell, TerrainType, Weather
from .units import (
    UnitManager, Unit, AircraftSquadron, Airbase, MissileBattery,
    Faction, UnitCategory, UnitStatus, Posture
)
from .logistics import LogisticsSystem, SupplyNode, SupplyRoute
from .fog_of_war import FogOfWar, IntelQuality, IntelReport, SensorCoverage
from .turn import TurnManager, GameState, Orders, Phase, TimeOfDay

__all__ = [
    # Map
    "HexMap", "HexCell", "TerrainType", "Weather",
    # Units
    "UnitManager", "Unit", "AircraftSquadron", "Airbase", "MissileBattery",
    "Faction", "UnitCategory", "UnitStatus", "Posture",
    # Logistics
    "LogisticsSystem", "SupplyNode", "SupplyRoute",
    # Fog of War
    "FogOfWar", "IntelQuality", "IntelReport", "SensorCoverage",
    # Turn Management
    "TurnManager", "GameState", "Orders", "Phase", "TimeOfDay",
]
