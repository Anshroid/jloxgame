from abc import ABC, abstractmethod
from typing import Any
from discord import ApplicationContext, Interaction
from discord.ui import Modal, InputText
from enum import Enum

Status = Enum("Status", "SETUP RUNNING PAUSED END")
    
class GameContext(ABC):
    @abstractmethod
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.status = Status.SETUP

        self.teams = []

    @abstractmethod
    async def setup(self, dctx: ApplicationContext, initial: bool) -> bool:
        pass

    @abstractmethod
    def serialize(self) -> str:
        pass

    @classmethod
    @abstractmethod
    def load(cls, name: str, data: str) -> GameContext:
        pass

class SetupModal[S: GameContext](Modal):
    @abstractmethod
    def __init__(self, gctx: S, initial: bool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.gctx = gctx

        self.initial = initial
        if initial:
            self.name = InputText(label="Game name", value=gctx.name)
            self.add_item(self.name)

    @abstractmethod
    async def callback(self, interaction: Interaction):
        if self.initial:
            self.gctx.name = self.children[0].value or ""
            
        await interaction.response.defer()