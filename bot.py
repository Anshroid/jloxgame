from .abc import AsyncCallable
from .state import GameContext, Status
from .command_patch import GameCommand, GameCommandGroup

from typing import Concatenate, Any, cast

from discord import ApplicationContext, AutocompleteContext, option # pyright: ignore[reportUnknownVariableType]

import discord
import pathlib
import asyncio
import os


class JLOXBot[ContextType: GameContext](discord.Bot):
    def __init__(self, ctx_cls: type[ContextType], save_dir: pathlib.Path, *args: Any, **options: Any):
        super().__init__(*args, **options) # pyright: ignore[reportUnknownMemberType]
        
        self.ctx_cls = ctx_cls
        self.save_dir = save_dir
        self.games: dict[int, ContextType] = {}

        self.command()(self.create)
        self.game_command()(self.configure)
        self.game_command()(self.join)
        self.game_command()(self.end)
        
        if not self.save_dir.exists():
            os.mkdir(self.save_dir)
        if not (self.save_dir / "archive").exists():
            os.mkdir(self.save_dir / "archive")
            
        for file in self.save_dir.iterdir():
            if file.suffix == ".json":
                try:
                    thread_id = int(file.stem)
                    self.games[thread_id] = ctx_cls.load(self.save_dir, thread_id)
                except ValueError as e:
                    print(f"Invalid file in save folder: {file}")
                    raise e
        
        self.scheduler_task = asyncio.get_event_loop().create_task(self.scheduler())

    def command[**Ts](self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[ApplicationContext, Ts], None]): # pyright: ignore[reportUnknownParameterType]
            return self.application_command(**kwargs)(func) # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType] 
        return decorator
    
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
    
    def run(self, *args: Any, **kwargs: Any):
        try:
            super().run(*args, **kwargs)
        except KeyboardInterrupt:
            print("Shutting down!")
            self.scheduler_task.cancel()
            for gctx in self.games.values():
                asyncio.create_task(gctx.save(self.save_dir))
    
    async def scheduler(self) -> None:
        try:
            print(f"Starting event scheduler...")
            
            t = 0
            while True:
                do_save = t >= 60
                for gctx in self.games.values():
                    assert gctx.real
                    await gctx.schedule_tick()
                    
                    if do_save:
                        await gctx.save(self.save_dir)
                
                if do_save:
                    t = 0
                else:
                    t += 1
                    
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            print(f"Shutting down event scheduler!")

    # UNIVERSAL GAME COMMANDS
    
    async def create(self, dctx: ApplicationContext) -> None:
        """Create and set up a new game!"""
        if isinstance(dctx.channel, discord.Thread):
            await dctx.respond("Cannot create a game from a thread!", ephemeral=True)
            return
        
        gctx = self.ctx_cls(len(self.games))
        if await gctx.configure(dctx, Status.INIT):
            assert dctx.channel is not None
            assert isinstance(dctx.channel, discord.TextChannel)
            channel = dctx.channel
            thread = await channel.create_thread(name=gctx.name, type=discord.ChannelType.public_thread)
            
            gctx.realise(thread.id)
            self.games[thread.id] = gctx
            
            await gctx.save(self.save_dir)

            await thread.send(f"Created a game in this thread!")
    
    async def configure(self, dctx: ApplicationContext, gctx: ContextType):
        """Change the configuration of the current game."""
        if await gctx.configure(dctx, gctx.status):
            await dctx.respond(f"Configuration changed!")
    
    async def join_autocomplete(self, ctx: AutocompleteContext, gctx: ContextType): return [team.name for team in gctx.teams]
    
    @option("team", str, autocomplete=join_autocomplete)
    async def join(self, dctx: ApplicationContext, gctx: ContextType, team: str):
        """Join a team in the current game."""
        
        user = cast(discord.User, dctx.user)
        
        gctx.teams[[team.name for team in gctx.teams].index(team)].add_user(user)
        
    
    # start

    async def end(self, dctx: ApplicationContext, gctx: ContextType, delete: bool = True):
        """End the current game."""
        if gctx.scheduler_task is not None: gctx.scheduler_task.cancel()
        
        assert dctx.channel_id is not None
        del self.games[dctx.channel_id]
        if (file := self.save_dir / f"{dctx.channel_id}.json").exists():
            file.move(self.save_dir / "archive" / file.name)
        if delete:
            await dctx.channel.delete() # type: ignore