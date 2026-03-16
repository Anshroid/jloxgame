from .abc import AsyncCallable
from .state import GameContext
from .command import GameCommand, GameCommandGroup

from typing import Concatenate, Any
import discord

class JLOXBot[S: GameContext](discord.Bot):
    def __init__(self, ctx_cls: type[S], description: str | None =None, *args: Any, **options: Any):
        super().__init__(description, *args, **options) # pyright: ignore[reportUnknownMemberType]
        
        self.ctx_cls = ctx_cls
        self.games: dict[int, S] = {}

        self.create_setup_command()
    
    def game_command(self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[discord.ApplicationContext, S, ...], None]): # pyright: ignore[reportUnknownParameterType]
            return self.application_command(cls=GameCommand, getGameCtx=self.getGameCtx, **kwargs)(func) # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType] 
        return decorator

    def create_group(self, name: str, description: str | None = None, guild_ids: list[int] | None = None, **kwargs: Any) -> GameCommandGroup[S]:
        description = description or "No description provided."
        group = GameCommandGroup[S](self.getGameCtx, name, description, guild_ids, **kwargs)
        self.add_application_command(group) # pyright: ignore[reportUnknownMemberType]
        return group
    
    def getGameCtx(self, channel_id: int) -> S:
        return self.games[channel_id]
    
    def create_setup_command(self): # pyright: ignore[reportUnknownParameterType]
        @self.command() # pyright: ignore[reportUnknownMemberType]
        async def setup(dctx: discord.ApplicationContext) -> None: # pyright: ignore[reportUnusedFunction]
            """Create and set up a new game!"""
            if isinstance(dctx.channel, discord.Thread):
                await dctx.respond("Cannot create a game from a thread!", ephemeral=True)
                return
                
            gctx = self.ctx_cls(f"Game {len(self.games) + 1}")
            if await gctx.setup(dctx):
                channel: discord.TextChannel = dctx.channel
                thread = await channel.create_thread(name=gctx.name, type=discord.ChannelType.public_thread)
                self.games[thread.id] = gctx

                await dctx.respond(f"Created a new game in {thread.mention}!")