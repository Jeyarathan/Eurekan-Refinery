"""Abstract base class for all unit models."""

from abc import ABC, abstractmethod
from typing import Any


class BaseUnitModel(ABC):
    """Abstract base for all unit models."""

    @abstractmethod
    def calculate(self, **kwargs: Any) -> Any:
        """Run the unit model calculation."""
        ...
