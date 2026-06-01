from __future__ import annotations
from abc import ABC, abstractmethod
from discord import ApplicationContext, User
from enum import Enum
from typing import Any, Self, cast
from asyncio import Lock
import pathlib, json, time, asyncio, random

from jloxgame.events import GameEvent

Status = Enum("Status", "INIT SETUP RUNNING PAUSED END")

class Team:
    """
    Represents a team in the game. You may subclass this if you would like.
    Remember to call `super().__init__()`.

    Warning: Objects of this class are *VOLATILE!*.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.players: dict[int, User | None]
    
    def add_user(self, user: User) -> None:
        self.players[user.id] = user
    
    def to_dict(self) -> dict[str, Any]: return {"name": self.name, "players": self.players.keys()}
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        team = cls(data["name"])
        team.players = {k: None for k in data["players"]}
        return team

class GameContext(ABC):
    """
    Represents the running state of a game. You should subclass this.
    Remember to call `super().__init__()`.

    Warning: Objects of this class are *VOLATILE!* Only the event log, config and player identities are saved.
    """
    
    registered_events: dict[str, type[GameEvent[Self]]] = {}
    @classmethod
    def event[EventType: GameEvent[Any]](cls, event: type[EventType]) -> type[EventType]:
        """Registers this class as a serializable and deserializable event."""
        
        event_ = cast(type[GameEvent[Self]], event)

        assert event_.event_type() is not None
        assert event_.event_type() not in cls.registered_events.keys()
        cls.registered_events[event_.event_type()] = event_
        print(f"Registered event {event_.event_type()}")
        return event
    
    @abstractmethod
    async def configure(self, dctx: ApplicationContext, status: Status) -> bool: ...

    def __init__(self, game_index: int) -> None:
        self.name = f"Game {game_index+1}"
        
        self.status = Status.SETUP
        self.thread_id = -1
        
        self.init_time = time.time_ns() // 1000
        self.last_update = self.init_time
        self.pause_duration = 0

        self.lock = Lock()
        self.scheduler_task: asyncio.Task[None] | None = None
        
        self.random = random.Random(self.init_time)
        
        self.event_log: list[GameEvent[Self]] = []
        self.scheduled_events: list[GameEvent[Self]] = []
        self.teams: list[Team] = []
        
        self.real = False
    
    def realise(self, thread_id: int):
        self.real = True
        self.thread_id = thread_id
        
    def game_time_now(self) -> int:
        return (time.time_ns() // 1000) - self.init_time - self.pause_duration
    
    def unix_ms_to_game_time(self, unix_ms: int) -> int:
        return unix_ms - self.init_time - self.pause_duration
    
    def message_id_to_game_time(self, message_id: int) -> int:
        return ((message_id >> 22) + 1420070400000) - self.init_time - self.pause_duration
    
    def game_time_to_unix_ms(self, game_time: int) -> int:
        return game_time + self.init_time + self.pause_duration

    async def add_event(self, event: GameEvent[Self]) -> None:
        """Add an event to the event log. 
        Note that events are added asynchronously. There is no guarantee that changes will be instant, only that the order will be correct.

        Args:
            event (GameEvent): The event to add.
        """
        async with self.lock:
            event.__time__ = self.game_time_now()
            self.event_log.append(event)
            event.update(self, len(self.event_log)-1)
    
    async def schedule_event(self, event: GameEvent[Self], h: int, m: int, s: int) -> None:
        """Schedule an event to be added to the event log.
        The event will be scheduled to be added at most one second after the selected time.

        Args:
            event (GameEvent): The event to be added.
            h (int): Number of hours in the future to schedule.
            m (int): Number of minutes in the future to schedule.
            s (int): Number of seconds in the future to schedule.
        """
        async with self.lock:
            event.__time__ = self.game_time_now() + ((h*60 + m)*60 + s)*1000
            self.scheduled_events.append(event)
            self.scheduled_events.sort(key=lambda e: e.__time__) # technically a min-heap would be better, but who cares, right?
    
    async def schedule_tick(self) -> None:
        if len(self.scheduled_events) > 0:
            async with self.lock:
                while len(self.scheduled_events) > 0 and self.game_time_now() > self.scheduled_events[0].__time__:             
                    event = self.scheduled_events.pop(0)
                    self.event_log.append(event)
                    event.update(self, len(self.event_log)-1)
                    
        self.last_update = self.game_time_now()
    
    def json_encoder(self, obj: object) -> Any:
        match obj:
            case Status():
                return obj.value
    
            case GameEvent():
                obj = cast(GameEvent[Self], obj) # cannot use the generic in the case statement
                d = obj.to_dict()
                if "__type__" in d.keys(): raise ValueError(f"{type(obj)} to_dict result must not contain key '__type__'")
                d["__type__"] = obj.event_type()
                if "__time__" in d.keys(): raise ValueError(f"{type(obj)} to_dict result must not contain key '__time__'")
                d["__time__"] = obj.__time__
                return d
    
            case Team():
                return obj.to_dict()

            case _:
                raise TypeError(f"Could not encode {obj} into JSON!")

    async def save(self, dir: pathlib.Path) -> None:
        assert self.real
        
        async with self.lock:
            with open(dir / f"{self.thread_id}.json", "w") as f:
                data: dict[str, Any] = {
                    "name": self.name,
                    "init_time": self.init_time,
                    "last_update": self.last_update,
                    "teams": self.teams,
                    "event_log": self.event_log
                }
                json.dump(data, f, default=self.json_encoder)

    @classmethod
    def load(cls, dir: pathlib.Path, thread_id: int) -> Self:
        with open(dir / f"{thread_id}.json", "r") as f:
            data = json.load(f)
            
            gctx = cls(-1)
            gctx.name = data["name"]
            gctx.teams = data["teams"] # TODO
            
            gctx.init_time = data["init_time"]
            gctx.last_update = data["last_update"]
            
            gctx.random = random.Random(gctx.init_time)
            
            gctx.event_log = []
            for event_dict in data["event_log"]:
                event = GameContext.registered_events[event_dict["__type__"]].from_dict(event_dict)
                event.__time__ = event_dict["__time__"]
                gctx.event_log.append(event)
            
            for i, e in enumerate(gctx.event_log):
                e.update(gctx, i)
                
            reload_event = Reload(gctx.game_time_now() - gctx.last_update)
            reload_event.__time__ = gctx.game_time_now()
            gctx.event_log.append(reload_event)
            reload_event.update(gctx, len(gctx.event_log)-1)
            
            gctx.realise(thread_id)

            return gctx

@GameContext.event
class Reload(GameEvent[GameContext]):
    def __init__(self, pause_duration: int) -> None:
        self.pause_duration = pause_duration

    @staticmethod
    def event_type() -> str: return "___reload__"

    def to_dict(self) -> dict[str, Any]: return {"pause_duration": self.pause_duration}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reload: return Reload(data["pause_duration"])

    def update(self, gctx: GameContext, i: int):
        gctx.pause_duration += self.pause_duration