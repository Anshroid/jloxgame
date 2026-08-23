from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from discord import ApplicationContext, Member, Role, Thread
from enum import Enum
from typing import Any, Self, cast
import pathlib, json, time, asyncio, random

from jloxgame.events import GameEvent, register_event, registered_events

Status = Enum("Status", "INIT SETUP RUNNING PAUSED END")

@dataclass
class Team:
    name: str
    colour: int
    
    create_thread: bool = True
        
    role_id: int = -1
    thread_id: int = -1

    role: Role | None = None
    thread: Thread | None = None    
    
    async def add_user(self, user: Member) -> bool:
        if self.role: await user.add_roles(self.role)
        if self.thread: await self.thread.add_user(user)
        return self.role is not None

    async def remove_user(self, user: Member) -> bool:
        if self.role: await user.remove_roles(self.role)
        if self.thread: await self.thread.remove_user(user)
        return self.role is not None
    
    def to_dict(self) -> dict[str, Any]: return {"name": self.name, "colour": self.colour, "thread_id": self.thread_id, "role_id": self.role_id}
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        team = cls(data["name"], data["colour"], thread_id=data["thread_id"], role_id=data["role_id"])
        return team
    
    def __hash__(self) -> int:
        assert self.role_id != -1
        return hash(self.role_id)
    
    def __repr__(self) -> str:
        return self.name
        

class GameContext(ABC):
    @abstractmethod
    async def configure(self, dctx: ApplicationContext) -> bool: ...

    @abstractmethod
    async def start(self, dctx: ApplicationContext) -> None: ...

    def __init__(self) -> None:
        self.status = Status.INIT
        
        self.thread_id: int = -1
        self.thread: Thread | None = None
        
        self.init_time = time.time_ns() // 1000
        self.last_update = self.init_time
        self.pause_duration = 0

        self.scheduler_task: asyncio.Task[None] | None = None

        self.errored = False
        
        self.rng = random.Random(self.init_time)
        
        self.event_log: list[GameEvent[Self]] = []
        self.initial_events: list[GameEvent[Self]] = []
        self.scheduled_events: list[GameEvent[Self]] = []
        self.teams: list[Team] = []

        self.threads_roles_created = asyncio.Event()
    
    def get_user_team(self, user: Member):
        _teams = [team for team in self.teams if team.role in user.roles]

        return _teams[0] if len(_teams) == 1 else None
    
    def get_team(self, id: int):
        try:
            return next(team for team in self.teams if team.role_id == id)
        except StopIteration:
            raise ValueError(f"Invalid team id provided: {id}")
        
    def game_time_now(self) -> int:
        return (time.time_ns() // 1000) - self.init_time - self.pause_duration
    
    def unix_ms_to_game_time(self, unix_ms: int) -> int:
        return (unix_ms * 1000) - self.init_time - self.pause_duration
    
    def message_id_to_game_time(self, message_id: int) -> int:
        return (((message_id >> 22) + 1420070400000) * 1000) - self.init_time - self.pause_duration
    
    def game_time_to_unix_ms(self, game_time: int) -> int:
        return (game_time // 1000) + self.init_time + self.pause_duration

    def add_event(self, event: GameEvent[Self]) -> None:
        """Add an event to the event log. 
        Events are added asynchronously. There is no guarantee that changes will be instant, only that the order of events will be correct.

        Args:
            event (GameEvent): The event to add.
        """

        if self.thread_id == -1: # true during and only during initial configuration
            self.initial_events.append(event)
        else:
            print(f"[{self.thread_id} | info] adding event {event.event_type()}")
            event.__time__ = self.game_time_now()
            try:
                event.update(self)
            except Exception as e:
                print(f"[{self.thread_id} | info] exception raised in event {event.to_dict()}, reloading recommended")
                asyncio.create_task(self.save(pathlib.Path() / "save"))
                raise e
            self.event_log.append(event)
    
    def schedule_event(self, event: GameEvent[Self], h: int, m: int, s: int) -> None:
        """Schedule an event to be added to the event log.
        The event will be scheduled to be added at most one second after the selected time.

        Args:
            event (GameEvent): The event to be added.
            h (int): Number of hours in the future to schedule.
            m (int): Number of minutes in the future to schedule.
            s (int): Number of seconds in the future to schedule.
        """
        print(f"[{self.thread_id} | info] scheduling event {event.event_type()}")
        event.__time__ = self.game_time_now() + ((h*60 + m)*60 + s)*1000
        self.scheduled_events.append(event)
        self.scheduled_events.sort(key=lambda e: e.__time__) # O(nlogn) insert :skull:
        # technically a min-heap would be optimal, but who cares, right?
    
    async def schedule_tick(self) -> None:
        if len(self.scheduled_events) > 0:
            # lock not needed here since there is no async during the state modification (this coro cannot be interrupted)
            while len(self.scheduled_events) > 0 and self.game_time_now() > self.scheduled_events[0].__time__:             
                event = self.scheduled_events.pop(0)
                print(f"[{self.thread_id} | info] processing scheduled event {event.event_type()}")
                try:
                    event.update(self)
                except Exception as e:
                    print(f"[{self.thread_id} | info] exception raised in event {event.to_dict()}, reloading recommended")
                    asyncio.create_task(self.save(pathlib.Path() / "save"))
                    raise e
                self.event_log.append(event)
                    
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
        if self.errored: return
        print(f"[{self.thread_id} | info] saving game")
        with open(dir / f"{self.thread_id}.json", "w") as f:
            data: dict[str, Any] = {
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
            
            gctx = cls()
            gctx.teams = [Team.from_dict(team_dict) for team_dict in data["teams"]]
            
            gctx.init_time = data["init_time"]
            gctx.last_update = data["last_update"]
            
            gctx.thread_id = thread_id

            gctx.rng = random.Random(gctx.init_time)
            
            gctx.event_log = []
            for event_dict in data["event_log"]:
                event = registered_events[event_dict["__type__"]].from_dict(event_dict)
                event.__time__ = event_dict["__time__"]
                gctx.event_log.append(event)
                event.update(gctx)
            
            reload_event = Reload(gctx.game_time_now() - gctx.last_update)
            reload_event.__time__ = gctx.game_time_now()
            gctx.event_log.append(reload_event)
            reload_event.update(gctx)
            
            return gctx

@register_event
class Reload(GameEvent[GameContext]):
    def __init__(self, pause_duration: int) -> None:
        self.pause_duration = pause_duration

    @staticmethod
    def event_type() -> str: return "__reload__"

    def to_dict(self) -> dict[str, Any]: return {"pause_duration": self.pause_duration}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reload: return Reload(data["pause_duration"])

    def update(self, gctx: GameContext):
        gctx.pause_duration += self.pause_duration