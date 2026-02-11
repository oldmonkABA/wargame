"""
Strategic agents for wargame simulation.

Uses OpenAI (gpt-4o) for decision making.
"""

from .base import StrategicAgent
from .india import IndiaAgent
from .pakistan import PakistanAgent

__all__ = ["StrategicAgent", "IndiaAgent", "PakistanAgent"]
