from abc import ABC, abstractmethod
from typing import Any, Self, TYPE_CHECKING

if TYPE_CHECKING:
    from jloxgame.state import GameContext

registered_events: dict[str, type[GameEvent[Any]]] = {}
def register_event[EventType: GameEvent[Any]](event: type[EventType]) -> type[EventType]: 
    """Decorator that registers this class as a serializable and deserializable event."""

    # this is not type-theoretically sound (GameEvent is contravariant so GameEvent[Any] has no subtypes), but who cares, right?
    # in fact this function is type-theoretically inconsistent, it would have to be a static method of the game state to be solvable
    # but I tried that earlier and this is syntactically neater so we are going with this
    
    assert event.event_type() is not None
    assert event.event_type() not in registered_events.keys()
    registered_events[event.event_type()] = event
    print(f"[jloxgame | info] registered event {event.event_type()}")
    return event

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
    def update(self, gctx: ContextType) -> None: ...