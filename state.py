from abc import ABC, abstractmethod
from discord import ApplicationContext, User
from enum import Enum
from typing import List, Tuple
from asyncio import Lock

Status = Enum("Status", "SETUP RUNNING PAUSED END")

class GameConfig(ABC):
    """
    Represents the initial configuration of a game. You should subclass this and override the :func:`configure` method.

    This is created before the GameContext is instantiated, and is modified in :func:`configure` (preferably by a modal), which may be called at any time by the `/setup` command.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def configure(self, dctx: ApplicationContext, initial: bool) -> bool: ...

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

class GameTeam(ABC):
    """
    Represents a team in the game. You should subclass this and call `__init__()`
    """

    def __init__(self, name: str) -> None:
        """
        @param name: the name of the team
        """
        self.name = name
        self.players: List[Tuple[int, User | None]]
    
    def add_user(self, user: User) -> None:
        self.players.append((user.id, user))

class GameContext(ABC):
    """
    Represents the running state of a game. You should subclass this and override the `update` method.

    Warning: Objects of this class are *VOLATILE!* Only the event log, config and player identities are saved.
    """

    def __init__(self, config: GameConfig) -> None:
        """
        @param name: The name of the game instance.
        """
        self.config = config

        self.status = Status.SETUP

        self.lock = Lock()
        self.event_log: List[GameEvent] = []
        self.teams: List[GameTeam] = []

    @abstractmethod
    async def update(self, event: GameEvent):
        pass

    async def add_event(self, event: GameEvent):
        async with self.lock:
            await self.update(event)
            self.event_log.append(event)
    
    async def save(self):
        async with self.lock:
            # TODO
            pass
    
    @classmethod
    def load(cls):
        pass