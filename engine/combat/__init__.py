"""
Combat resolution modules for each warfare domain.

Phase order: missiles → EW/cyber → air → drones → artillery → helicopters → ground → SF
"""

from .missiles import MissileCombat
from .ew import ElectronicWarfare
from .air import AirCombat
from .drones import DroneCombat
from .artillery import ArtilleryCombat
from .helicopters import HelicopterCombat
from .ground import GroundCombat
from .special_forces import SpecialForcesCombat

__all__ = [
    "MissileCombat",
    "ElectronicWarfare",
    "AirCombat",
    "DroneCombat",
    "ArtilleryCombat",
    "HelicopterCombat",
    "GroundCombat",
    "SpecialForcesCombat",
]
