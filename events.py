from abc import ABC, abstractmethod
from typing import Any, Self, TYPE_CHECKING

if TYPE_CHECKING:
    from jloxgame.state import GameContext

class GameEvent[ContextType: GameContext](ABC):
    """
    Represents a single game event. You should subclass this and implement :func:`event_type`, :func:`to_dict` and :func:`from_dict`.
    """

    def __init__(self):
        self.__time__ = 0

    @staticmethod
    @abstractmethod
    def event_type() -> str:
        """Returns the type of this event."""
        ...

    @abstractmethod
    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> Self: ...

    @abstractmethod
    def update(self, gctx: ContextType, i: int) -> None: ...