from abc import ABC, abstractmethod
from discord import ApplicationContext
from enum import Enum

Status = Enum("Status", "SETUP RUNNING PAUSED END")
    
class GameContext(ABC):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.status = Status.SETUP

        self.teams = []

    @abstractmethod
    async def setup(self, dctx: ApplicationContext, initial: bool) -> bool:
        pass

class GameEvent(ABC):
    @property
    @abstractmethod
    def event_type(self):
        pass

    @abstractmethod
    def serialize(self):
        pass

    @abstractmethod
    def load(self):
        pass