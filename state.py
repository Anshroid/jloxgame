from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import GenericAlias
from discord import ApplicationContext, Member, Role, Thread
from enum import Enum
from typing import Any, Callable, Concatenate, Coroutine, Self, cast, get_args, get_origin, get_type_hints
import pathlib, json, time, asyncio, random

Status = Enum("Status", "INIT SETUP RUNNING PAUSED END")

######################################## EVENTS ########################################

type Serializable = str | int | float | bool | list[Serializable] | tuple[Serializable] | dict[str, Serializable]

def _serializable(_type: type) -> bool:
    if _type in [str, int, float, bool]:
        return True

    if isinstance(_type, GenericAlias):
        typeargs = get_args(_type)
        if get_origin(_type) in [list, tuple]:
            return _serializable(typeargs[0])
        elif _type.__origin__ == dict:
            return typeargs[0] == str and _serializable(typeargs[1])

    return False

@dataclass
class EventInstance:
    __type__: str
    __time__: int
    args: list[Serializable]
    kwargs: dict[str, Serializable]

    def to_dict(self): return {"__type__": self.__type__, "__time__": self.__time__, "args": self.args, "kwargs": self.kwargs}

class Event[ContextType: GameContext, **Params, ReturnType]:
    def __init__(self, func: Callable[Concatenate[ContextType, Params], ReturnType], callback: Callable[[ContextType, ReturnType], Coroutine[None, None, None]] | None = None) -> None:
        self.func = func
        self.callback = callback
    
    def __get__(self, gctx: ContextType, _=None) -> BoundEvent[ContextType, Params, ReturnType]:
        return BoundEvent(self, gctx)

    def event_type(self): return self.func.__name__

    def __repr__(self) -> str: return f"<jloxgame.state.Event object of type {self.event_type()}>"

class BoundEvent[ContextType: GameContext, **Params, ReturnType]:
    def __init__(self, event: Event[ContextType, Params, ReturnType], gctx: ContextType) -> None:
        self.event = event
        self.gctx = gctx
    
    def event_type(self): return self.event.event_type()

    def get_instance(self, time: int, *args: Params.args, **kwargs: Params.kwargs) -> EventInstance:
        return EventInstance(self.event_type(), time, cast(list[Serializable], args), cast(dict[str, Serializable], kwargs))
    
    def __call__(self, *args: Params.args, **kwargs: Params.kwargs) -> ReturnType:
        gctx = self.gctx
        if gctx.thread_id == -1:
            raise ValueError("Event added before initialisation!")
        
        print(f"[{gctx.thread_id} | info] adding event {self.event_type()}")

        inst = self.get_instance(gctx.game_time_now(), *args, **kwargs)
        
        try:
            ret = self.event.func(gctx, *args, **kwargs)
        except Exception as e:
            print(f"[{gctx.thread_id} | info] exception raised in event {inst.to_dict()}, reloading recommended")
            asyncio.create_task(gctx.save(pathlib.Path() / "save")) # TODO: hardcoded
            raise e

        gctx.event_log.append(inst)

        if self.event.callback: asyncio.create_task(self.event.callback(gctx, ret))
        return ret
    
    def __repr__(self) -> str: return f"<jloxgame.state.BoundEvent object on context {self.gctx} of type {self.event_type()}>"

# TODO: callback
# def event[ContextType: GameContext, **Params, ReturnType](callback: Callable[[ContextType, ReturnType], Coroutine[None, None, None]] | None = None):
def event[ContextType: GameContext, **Params, ReturnType](func: Callable[Concatenate[ContextType, Params], ReturnType]) -> Event[ContextType, Params, ReturnType]:
    if asyncio.iscoroutinefunction(func):
        raise ValueError(f"Invalid function {func} marked as event: function may not be async!")

    types = get_type_hints(func)
    for label, _type in types.items():
        if label in ["self", "return"]: continue

        if not _serializable(_type):
            raise ValueError(f"Invalid function {func} marked as event: parameter {label} ({_type}) is not serializable!")

    print(f"[jloxgame | info] registered event {func.__name__}")

    return Event(func)
    # return inner


######################################## MODELS ########################################

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
        
        self.event_log: list[EventInstance] = []
        self.initial_events: list[EventInstance] = []
        self.scheduled_events: list[EventInstance] = []
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
        
    def game_time_now(self) -> int: # TODO: during loading, spoof this
        return (time.time_ns() // 1000) - self.init_time - self.pause_duration
    
    def unix_ms_to_game_time(self, unix_ms: int) -> int: # TODO: Maybe remove these?
        return (unix_ms * 1000) - self.init_time - self.pause_duration
    
    def message_id_to_game_time(self, message_id: int) -> int:
        return self.unix_ms_to_game_time((message_id >> 22) + 1420070400000)
    
    def game_time_to_unix_ms(self, game_time: int) -> int:
        return (game_time // 1000) + self.init_time + self.pause_duration

    def actualise_instance(self, inst: EventInstance):
        bound_event: BoundEvent[Self, Any, Any] = getattr(self, inst.__type__)

        try:
            bound_event(*inst.args, **inst.kwargs)
        except Exception as e:
            asyncio.create_task(self.save(pathlib.Path() / "save"))
            raise ValueError(f"[{self.thread_id} | info] exception raised in event {inst.to_dict()}, reloading recommended") from e

        self.event_log.append(inst)

    def schedule_event[**Params, ReturnType](self, h: int, m: int, s: int, event: BoundEvent[Self, Params, ReturnType], *args: Params.args, **kwargs: Params.kwargs) -> None:
        """Schedule an event to be added to the event log.
        The event will be scheduled to be added at most one second after the selected time.

        Args:
            event (Event): The event to be added.
            h (int): Number of hours in the future to schedule.
            m (int): Number of minutes in the future to schedule.
            s (int): Number of seconds in the future to schedule.
        """
        print(f"[{self.thread_id} | info] scheduling event {event.event_type()}")
        inst = event.get_instance(self.game_time_now() + ((h*60 + m)*60 + s)*1000, *args, **kwargs)
        self.scheduled_events.append(inst)
        self.scheduled_events.sort(key=lambda e: e.__time__) # O(nlogn) insert :skull:
        # technically a min-heap would be optimal, but who cares, right?
    
    async def schedule_tick(self) -> None:
        if len(self.scheduled_events) > 0:
            # lock not needed here since there is no async during the state modification (this coro cannot be interrupted)
            while len(self.scheduled_events) > 0 and self.game_time_now() > self.scheduled_events[0].__time__:             
                inst = self.scheduled_events.pop(0)
                print(f"[{self.thread_id} | info] processing scheduled event {inst.__type__}")
                self.actualise_instance(inst)
                    
        self.last_update = self.game_time_now()
    
    def json_encoder(self, obj: object) -> Any:
        match obj:
            case Status():
                return obj.value
    
            case EventInstance():
                return obj.to_dict()
    
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
                "event_log": self.event_log + self.scheduled_events
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
                inst = EventInstance(event_dict["__type__"], event_dict["__time__"], event_dict["args"], event_dict["kwargs"])
                gctx.actualise_instance(inst)

            gctx.__reload__(gctx.game_time_now() - gctx.last_update)
            
            return gctx
    
    @event
    def __reload__(self, pause_duration: int) -> None:
        self.pause_duration += pause_duration