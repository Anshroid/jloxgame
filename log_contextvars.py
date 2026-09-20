from contextvars import ContextVar

event_name: ContextVar[str] = ContextVar("eventType")
game_id: ContextVar[int] = ContextVar("gameId")