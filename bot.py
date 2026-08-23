from asyncio.base_events import traceback
from .abc import AsyncCallable
from .state import GameContext, Team
from .command_patch import GameCommand, GameCommandGroup

from typing import Concatenate, Any, Self, cast

from discord import ApplicationCommand, ApplicationContext, AutocompleteContext, Member, Role, TextChannel, Thread, default_permissions, option # pyright: ignore[reportUnknownVariableType]

import discord
import pathlib
import asyncio
import atexit
import os


class JLOXBot[ContextType: GameContext](discord.Bot):
    def __init__(self, ctx_cls: type[ContextType], save_dir: pathlib.Path, joinable: bool=True, member_creatable: bool=True, *args: Any, **options: Any):
        super().__init__(*args, **options) # pyright: ignore[reportUnknownMemberType]
        
        self._ctx_cls = ctx_cls
        self.save_dir = save_dir
        self.games: dict[int, ContextType] = {}
        self.team_thread_map: dict[int, int] = {}

        game_group = self.create_group("game")
        discord.guild_only()(game_group.command()(self.create)) # pyright: ignore[reportUnknownMemberType]
        game_group.game_command()(self.configure)
        game_group.game_command(name="start")(self._start)
        game_group.game_command()(self.end)
        game_group.game_command()(self.reload)

        if not member_creatable:
            discord.default_permissions(manage_roles=True)(game_group) # pyright: ignore[reportUnknownMemberType]
        
        self.game_command()(self.configure)
        if joinable:
            self.game_command()(self.join)
            self.game_command()(self.leave)
    
        
        if not self.save_dir.exists():
            os.mkdir(self.save_dir)
        if not (self.save_dir / "archive").exists():
            os.mkdir(self.save_dir / "archive")
        
        @self.listen("on_ready", once=True)
        async def _(): await self.load_games()
        # passthrough function required because pycord tries to set func._once which is disallowed on methods
        
        self.scheduler_task = asyncio.get_event_loop().create_task(self.scheduler())
    
    async def load_games(self):
        for file in self.save_dir.iterdir():
            if file.suffix == ".json":
                game_thread_id = int(file.stem)

                try:
                    gctx = self._ctx_cls.load(self.save_dir, game_thread_id)
                except ValueError:
                    print(f"[jloxgame | warn] invalid file in save folder (game not loaded): {file}")
                    traceback.print_exc()
                    return

                game_thread = await self.get_or_fetch(Thread, game_thread_id)

                if game_thread is None:
                    print(f"[jloxgame | warn] could not find thread for game (game not loaded): {game_thread_id}")
                    return

                for team in gctx.teams:
                    team.role = await game_thread.guild.get_or_fetch(Role, team.role_id)
                    if team.role is None:
                        print(f"[jloxgame | warn] could not find all team roles (game not loaded): {game_thread_id}")
                        return
                    
                    if team.create_thread: 
                        team.thread = await game_thread.guild.get_or_fetch(Thread, team.thread_id)
                        if team.thread is None:
                            print(f"[jloxgame | warn] could not find all team threads (game not loaded): {game_thread_id}")
                            return
                
                self.games[game_thread_id] = gctx
                self.team_thread_map.update({team.thread_id: game_thread_id for team in gctx.teams if team.thread})

                for event in gctx.initial_events:
                    gctx.add_event(event)
                gctx.initial_events = []

                print(f"[jloxgame | info] loaded game {game_thread_id}")

    def command[**Ts](self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[ApplicationContext, Ts], None]): # pyright: ignore[reportUnknownParameterType]
            return cast(ApplicationCommand[Any, Ts, None], self.application_command(**kwargs)(func))
        return decorator
    
    def game_command[**Ts](self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[ApplicationContext, ContextType, Ts], None]): # pyright: ignore[reportUnknownParameterType]
            return self.application_command(cls=GameCommand[Self], getGameCtx=self.get_game_ctx, **kwargs)(func)
        return decorator

    def create_group(self, name: str, description: str | None = None, guild_ids: list[int] | None = None, **kwargs: Any) -> GameCommandGroup[ContextType]:
        description = description or "No description provided."
        group = GameCommandGroup[ContextType](self.get_game_ctx, name, description, guild_ids, **kwargs)
        self.add_application_command(group) # pyright: ignore[reportUnknownMemberType]
        return group
    
    def get_game_ctx(self, context: int | ApplicationContext | AutocompleteContext | None) -> ContextType | None:
        channel_id = -1
        match context:
            case int():
                channel_id = context
            case ApplicationContext():
                channel_id = context.channel_id
            case AutocompleteContext():
                channel_id = context.interaction.channel_id
            case None:
                pass
        
        if channel_id == None:
            return None

        channel_id = self.team_thread_map.get(channel_id, channel_id) # if this thread is known to be a team thread, replace channel_id with the game thread
        return self.games.get(channel_id, None)
    
    def save_on_exit_handler(self):
        print("[jloxgame | info] shutting down")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.gather(*(loop.create_task(gctx.save(self.save_dir)) for gctx in self.games.values())))
        loop.close()
        self.scheduler_task.cancel()
    
    def run(self, *args: Any, **kwargs: Any):
        atexit.register(self.save_on_exit_handler)
        super().run(*args, **kwargs)
    
    async def scheduler(self) -> None:
        try:
            print(f"[jloxgame | info] starting event scheduler")
            
            t = 0
            while True:
                do_save = t >= 60
                for gctx in self.games.values():
                    await gctx.schedule_tick()
                    
                    if do_save:
                        await gctx.save(self.save_dir)
                
                if do_save:
                    t = 0
                else:
                    t += 1
                    
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            print(f"[jloxgame | info] shutting down event scheduler")

    # UNIVERSAL GAME COMMANDS
    
    async def create(self, dctx: ApplicationContext) -> None:
        """Create and set up a new game!"""
        if isinstance(dctx.channel, discord.Thread):
            await dctx.respond("Cannot create a game from a thread!", ephemeral=True)
            return
        
        gctx = self._ctx_cls()
        if await gctx.configure(dctx):
            assert isinstance(dctx.channel, discord.TextChannel)

            channel = dctx.channel
            thread = await channel.create_thread(name=f"Game {len(self.games)+1}", type=discord.ChannelType.public_thread)
            gctx.thread = thread
            gctx.thread_id = thread.id

            await asyncio.gather(*[self._create_team_role_thread(team, dctx) for team in gctx.teams])

            self.games[thread.id] = gctx
            self.team_thread_map.update({team.thread_id: thread.id for team in gctx.teams if team.thread})

            for event in gctx.initial_events:
                gctx.add_event(event)
            gctx.initial_events = []
            
            asyncio.gather(gctx.save(self.save_dir), thread.send(f"Created a game in this thread!"))

    async def _create_team_role_thread(self, team: Team, dctx: ApplicationContext):
        assert dctx.guild
        assert isinstance(dctx.channel, TextChannel)

        role = await dctx.guild.create_role(name=team.name, color=team.colour)
        team.role = role
        team.role_id = role.id

        if team.create_thread:
            thread = await dctx.channel.create_thread(name=team.name, type=discord.ChannelType.private_thread)
            team.thread = thread
            team.thread_id = thread.id
    
    async def configure(self, dctx: ApplicationContext, gctx: ContextType):
        """Change the configuration of this thread's game."""
        if await gctx.configure(dctx):
            await dctx.respond(f"Configuration changed!", ephemeral=True)
    
    async def team_autocomplete(self, ctx: AutocompleteContext):
        bot = cast(JLOXBot[ContextType], ctx.bot)
        gctx = bot.get_game_ctx(ctx)
        return [] if gctx is None else [team.name for team in gctx.teams]
    
    @option("team", str, autocomplete=team_autocomplete)
    async def join(self, dctx: ApplicationContext, gctx: ContextType, team: str):
        """Join a team in this thread's game."""
        
        assert isinstance(dctx.user, discord.Member)

        if gctx.get_user_team(dctx.user) is not None:
            await dctx.respond("You are already in a team!", ephemeral=True)
            return

        _team = next((_team for _team in gctx.teams if _team.name == team), None)

        if _team is None:
            await dctx.respond("Team not found!", ephemeral=True)
            return

        await _team.add_user(dctx.user)
        await dctx.respond("Successfully added you to that team!", ephemeral=True)
    
    @default_permissions(manage_roles=True) # pyright: ignore[reportUntypedFunctionDecorator]
    @option("team", str, autocomplete=team_autocomplete)
    async def assign(self, dctx: ApplicationContext, gctx: ContextType, user: Member, team: str):
        """Assign a player to a team in this thread's game."""
        
        if gctx.get_user_team(user) is not None:
            await dctx.respond("That player is already in a team!", ephemeral=True)
            return

        _team = next((_team for _team in gctx.teams if _team.name == team), None)

        if _team is None:
            await dctx.respond("Team not found!", ephemeral=True)
            return
        
        await _team.add_user(user)
        await dctx.respond("Successfully assigned that player to that team!", ephemeral=True)
    
    async def leave(self, dctx: ApplicationContext, gctx: ContextType):
        """Leave your team in this thread's game."""
        
        assert isinstance(dctx.user, discord.Member)

        team = gctx.get_user_team(dctx.user)
        if team is None:
            await dctx.respond("You are not in a team!", ephemeral=True)
            return

        await team.remove_user(dctx.user)
        await dctx.respond("Successfully removed you from your team!", ephemeral=True)
    
    @default_permissions(manage_roles=True) # pyright: ignore[reportUntypedFunctionDecorator]
    async def reload(self, dctx: ApplicationContext, gctx: ContextType):
        self.games[gctx.thread_id] = self._ctx_cls.load(self.save_dir, gctx.thread_id)
        await dctx.respond("Game reloaded successfully!", ephemeral=True)
        
    async def _start(self, dctx: ApplicationContext, gctx: ContextType):
        """Start this thread's game."""
        await gctx.start(dctx)

    async def end(self, dctx: ApplicationContext, gctx: ContextType, delete_threads: bool = True):
        """End this thread's game."""
        if gctx.scheduler_task is not None: gctx.scheduler_task.cancel()
        
        del self.games[gctx.thread_id]
        if (file := self.save_dir / f"{dctx.channel_id}.json").exists():
            file.move(self.save_dir / "archive" / file.name)
        
        asyncio.gather(*[team.role.delete() for team in gctx.teams if team.role])
        if delete_threads:
            asyncio.gather(*[obj.thread.delete() for obj in gctx.teams + [gctx] if obj.thread])
