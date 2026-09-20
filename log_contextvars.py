from contextvars import ContextVar
from logging import Filter, LogRecord

game_id: ContextVar[int] = ContextVar("gameId")

class GameInjector(Filter):
    def filter(self, record: LogRecord) -> bool | LogRecord:
        record.gameId = game_id.get()
        return True