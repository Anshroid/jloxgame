from .abc import AsyncCallable
from .state import GameContext, GameConfig
from .command import GameCommand, GameCommandGroup

from typing import Concatenate, Any

from discord import ApplicationContext

import discord

class JLOXBot[ConfigType: GameConfig, ContextType: GameContext](discord.Bot):
    def __init__(self, ctx_cls: type[ContextType], cnf_cls: type[ConfigType], *args: Any, **options: Any):
        super().__init__(*args, **options) # pyright: ignore[reportUnknownMemberType]
        
        self.ctx_cls = ctx_cls
        self.cnf_cls = cnf_cls
        self.games: dict[int, ContextType] = {}

        self.command()(self.setup) # type: ignore
        self.game_command()(self.configure)
        self.game_command()(self.end)
    
    def game_command[**Ts](self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[ApplicationContext, ContextType, Ts], None]): # pyright: ignore[reportUnknownParameterType]
            return self.application_command(cls=GameCommand, getGameCtx=self.getGameCtx, **kwargs)(func) # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType] 
        return decorator

    def create_group(self, name: str, description: str | None = None, guild_ids: list[int] | None = None, **kwargs: Any) -> GameCommandGroup[ContextType]:
        description = description or "No description provided."
        group = GameCommandGroup[ContextType](self.getGameCtx, name, description, guild_ids, **kwargs)
        self.add_application_command(group) # pyright: ignore[reportUnknownMemberType]
        return group
    
    def getGameCtx(self, channel_id: int) -> ContextType:
        return self.games[channel_id]
    

    # GLOBAL GAME COMMANDS
    
    async def create(self, dctx: ApplicationContext) -> None: # pyright: ignore[reportUnusedFunction]
        """Create and set up a new game!"""
        if isinstance(dctx.channel, discord.Thread):
            await dctx.respond("Cannot create a game from a thread!", ephemeral=True)
            return
        
        config = self.cnf_cls(f"Game {len(self.games) + 1}")
        if await config.configure(dctx, True):
            gctx = self.ctx_cls(config)
            assert dctx.channel is not None
            assert isinstance(dctx.channel, discord.TextChannel)
            channel = dctx.channel
            thread = await channel.create_thread(name=gctx.config.name, type=discord.ChannelType.public_thread)
            self.games[thread.id] = gctx

            await dctx.respond(f"Created a new game in {thread.mention}!")
    
    async def configure(self, dctx: ApplicationContext, gctx: ContextType): # pyright: ignore[reportUnusedFunction]
        """Change the configuration of the current game."""
        if await gctx.config.configure(dctx, False):
            await dctx.respond(f"Configuration changed!")

    async def end(self, dctx: ApplicationContext, gctx: ContextType, delete: bool = True):
        """End the current game."""
        assert dctx.channel_id is not None
        del self.games[dctx.channel_id]
        if delete:
            await dctx.channel.delete() # type: ignore