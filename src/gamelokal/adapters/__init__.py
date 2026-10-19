"""Adapter per game."""
from .base import Adapter
from .wuwa import WUTHERING_WAVES

ADAPTERS = {WUTHERING_WAVES.name: WUTHERING_WAVES}

__all__ = ["Adapter", "ADAPTERS", "WUTHERING_WAVES"]
