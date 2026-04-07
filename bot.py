from .abc import AsyncCallable
from .state import GameContext
from .command import GameCommand, GameCommandGroup

from typing import Concatenate, Any

from discord import ApplicationContext

import discord

class JLOXBot[S: GameContext](discord.Bot):
    def __init__(self, ctx_cls: type[S], description: str | None =None, *args: Any, **options: Any):
        super().__init__(description, *args, **options) # pyright: ignore[reportUnknownMemberType]
        
        self.ctx_cls = ctx_cls
        self.games: dict[int, S] = {}

        self.command()(self.setup) # type: ignore
        self.game_command()(self.settings)
        self.game_command()(self.end)
    
    def game_command(self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[ApplicationContext, S, ...], None]): # pyright: ignore[reportUnknownParameterType]
            return self.application_command(cls=GameCommand, getGameCtx=self.getGameCtx, **kwargs)(func) # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType] 
        return decorator

    def create_group(self, name: str, description: str | None = None, guild_ids: list[int] | None = None, **kwargs: Any) -> GameCommandGroup[S]:
        description = description or "No description provided."
        group = GameCommandGroup[S](self.getGameCtx, name, description, guild_ids, **kwargs)
        self.add_application_command(group) # pyright: ignore[reportUnknownMemberType]
        return group
    
    def getGameCtx(self, channel_id: int) -> S:
        return self.games[channel_id]
    

    # GLOBAL GAME COMMANDS
    
    async def setup(self, dctx: ApplicationContext) -> None: # pyright: ignore[reportUnusedFunction]
        """Create and set up a new game!"""
        if isinstance(dctx.channel, discord.Thread):
            await dctx.respond("Cannot create a game from a thread!", ephemeral=True)
            return
        
        gctx = self.ctx_cls(f"Game {len(self.games) + 1}")
        if await gctx.setup(dctx, True):
            channel: discord.TextChannel = dctx.channel
            thread = await channel.create_thread(name=gctx.name, type=discord.ChannelType.public_thread)
            self.games[thread.id] = gctx

            await dctx.respond(f"Created a new game in {thread.mention}!")
    
    async def settings(self, dctx: ApplicationContext, gctx: S): # pyright: ignore[reportUnusedFunction]
        """Change the settings of the current game."""
        await gctx.setup(dctx, False)

    async def end(self, dctx: ApplicationContext, gctx: S, delete: bool = True):
        """End the current game."""
        if dctx.channel_id in self.games.keys():
            del self.games[dctx.channel_id]
            if delete:
                await dctx.channel.delete()
        else:
            await dctx.respond("No game found in this channel!", ephemeral=True)