"""
Data generation package for synthetic revenue recovery events.
"""

from data_generation.archetypes import ARCHETYPES, ArchetypeConfig
from data_generation.generator import generate_event
from data_generation.generate_batch import generate_batch

__all__ = ["ARCHETYPES", "ArchetypeConfig", "generate_event", "generate_batch"]
