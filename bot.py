import logging
import logging.config


from .abc import AsyncCallable
from .state import GameContext, Team
from .command_patch import GameCommand, GameCommandGroup
from .referee_view import RefereeView, event_embed

from typing import Concatenate, Any, cast

from discord import ApplicationCommand, ApplicationContext, AutocompleteContext, File, Member, OptionChoice, Role, TextChannel, Thread, default_permissions, option # pyright: ignore[reportUnknownVariableType]

import traceback
import discord
import pathlib
import asyncio
import atexit
import os

class JLOXBot[ContextType: GameContext](discord.Bot):
    def __init__(self, ctx_cls: type[ContextType], save_dir: pathlib.Path, joinable: bool=True, member_hostable: bool=True, logging_enabled: bool=True, backup_channel_id: int | None = None, *args: Any, **options: Any):
        super().__init__(*args, **options) # pyright: ignore[reportUnknownMemberType]
        
        self._ctx_cls = ctx_cls
        self.save_dir = save_dir
        self.games: dict[int, ContextType] = {}
        self.team_thread_map: dict[int, int] = {}

        if logging_enabled:
            logging.config.fileConfig(pathlib.Path(__file__).parent / "logging.conf")
            
        self.logger = logging.getLogger("jloxgame")
        self.logger.setLevel(logging.DEBUG)

        self.game_management_group = self.create_group("game", "Commands involving managing games.")
        discord.guild_only()(self.game_management_group.command()(self.create)) # pyright: ignore[reportUnknownMemberType]
        self.game_management_group.game_command()(self.configure)
        self.game_management_group.game_command()(self.clean)
        self.game_management_group.game_command()(self.reload)
        
        if joinable:
            self.game_command()(self.join)
            self.game_command()(self.leave)
        self.game_command()(self.assign)
        
        self.referee_group = self.create_group("referee", "Commands involving modifying game state in unrestricted ways.")
        self.referee_group.game_command()(self.view)

        if not member_hostable:
            discord.default_permissions(manage_roles=True)(self.game_management_group) # pyright: ignore[reportUnknownMemberType]
            discord.default_permissions(manage_roles=True)(self.referee_group) # pyright: ignore[reportUnknownMemberType]
        
        if not self.save_dir.exists():
            os.mkdir(self.save_dir)
        if not (self.save_dir / "archive").exists():
            os.mkdir(self.save_dir / "archive")
            
        
        self.scheduler_task = asyncio.get_event_loop().create_task(self.scheduler())
        
        # passthrough functions required instead of methods because pycord tries to set func._once which is disallowed on methods
        @self.listen("on_ready", once=True)
        async def _(): await self._load_games()

        if backup_channel_id:
            @self.listen("on_ready", once=True)
            async def _(): await asyncio.create_task(self.backup_poster(backup_channel_id))
    
    async def _load_games(self):
        for file in self.save_dir.iterdir():
            if file.suffix == ".json":
                gctx = await self.load_game(file)
                if gctx is None: continue
                
                self.games[gctx.thread_id] = gctx
                self.team_thread_map.update({team.thread_id: gctx.thread_id for team in gctx.teams if team.thread})
                self.logger.info(f"loaded game {gctx.thread_id}")
                
    async def load_game(self, file: pathlib.Path) -> ContextType | None:
        try:
            gctx = self._ctx_cls.load(file)
        except Exception:
            self.logger.warning(f"invalid file in save folder (game not loaded): {file}")
            traceback.print_exc()
            return

        game_thread = await self.get_or_fetch(Thread, gctx.thread_id)

        if game_thread is None:
            self.logger.warning(f"could not find thread for game (game not loaded): {gctx.thread_id}")
            return

        gctx.thread = game_thread
        
        for team in gctx.teams:
            team.role = await game_thread.guild.get_or_fetch(Role, team.role_id)
            if team.role is None:
                self.logger.warning(f"could not find all team roles (game not loaded): {gctx.thread_id}")
                return
            
            team.thread = await game_thread.guild.get_or_fetch(Thread, team.thread_id)
            if team.thread is None:
                self.logger.warning(f"could not find all team threads (game not loaded): {gctx.thread_id}")
                return
        
        gctx.file = file
        
        return gctx
        

    def command[**Ts](self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[ApplicationContext, Ts], None]): # pyright: ignore[reportUnknownParameterType]
            return cast(ApplicationCommand[Any, Ts, None], self.application_command(**kwargs)(func))
        return decorator
    
    def game_command[**Ts](self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[ApplicationContext, ContextType, Ts], None]): # pyright: ignore[reportUnknownParameterType]
            return self.application_command(cls=GameCommand[ContextType], getGameCtx=self.get_game_ctx, **kwargs)(func)
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
        self.logger.info("shutting down")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.gather(*(loop.create_task(gctx.save()) for gctx in self.games.values())))
        loop.close()
        self.scheduler_task.cancel()
    
    def run(self, *args: Any, **kwargs: Any):
        atexit.register(self.save_on_exit_handler)
        super().run(*args, **kwargs)
    
    async def scheduler(self) -> None:
        try:
            self.logger.info(f"starting event scheduler")
            
            t = 0
            while True:
                do_save = t >= 60
                for gctx in self.games.values():
                    try:
                        await gctx.schedule_tick()
                    except Exception:
                        traceback.print_exc()
                        channel = await self.get_or_fetch(TextChannel, 1538704776777179176)
                        if channel: await channel.send(traceback.format_exc())
                    
                    if do_save:
                        await gctx.save()
                
                if do_save:
                    t = 0
                else:
                    t += 1
                    
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            self.logger.info(f"shutting down event scheduler")
        
    async def backup_poster(self, backup_channel_id: int) -> None:
        channel = await self.get_or_fetch(TextChannel, backup_channel_id)

        if channel is None:
            self.logger.warning("could not find backups channel")
            return

        while True:
            self.logger.info("posting backup")
            
            for gctx in self.games.values():
                await gctx.save()
            await channel.send("new backups:", files=[File(self.save_dir / fn) for fn in os.listdir(self.save_dir) if os.path.isfile(self.save_dir / fn)])
            await asyncio.sleep(120)

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

            gctx.file = self.save_dir / f"{gctx.thread_id}.json"
            self.games[thread.id] = gctx
            self.team_thread_map.update({team.thread_id: thread.id for team in gctx.teams if team.thread})
            
            asyncio.gather(gctx.save(), thread.send(f"Created a game in this thread!"))
        
            self.logger.info(f"created game {gctx.thread_id}")
        
            if not dctx.response.is_done():
                await dctx.respond("Game successfully created!", ephemeral=True)
        
        else:
            if not dctx.response.is_done():
                await dctx.respond("Game not created!", ephemeral=True)

    async def _create_team_role_thread(self, team: Team, dctx: ApplicationContext):
        assert dctx.guild
        assert isinstance(dctx.channel, TextChannel)

        role = await dctx.guild.create_role(name=team.name, color=team.colour)
        team.role = role
        team.role_id = role.id

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
        return [] if gctx is None else [OptionChoice(team.name, team.team_id) for team in gctx.teams]
    
    @option("team", autocomplete=team_autocomplete, parameter_name="team_id")
    async def join(self, dctx: ApplicationContext, gctx: ContextType, team_id: int):
        """Join a team in this thread's game."""
        
        assert isinstance(dctx.user, discord.Member)

        if gctx.get_user_team(dctx.user) is not None:
            await dctx.respond("You are already in a team!", ephemeral=True)
            return

        team = gctx.get_team(team_id)

        if team is None:
            await dctx.respond("Team not found!", ephemeral=True)
            return

        await team.add_user(dctx.user)
        await dctx.respond("Successfully added you to that team!", ephemeral=True)
    
    @default_permissions(manage_roles=True) # pyright: ignore[reportUntypedFunctionDecorator]
    @option("team", autocomplete=team_autocomplete, parameter_name="team_id")
    async def assign(self, dctx: ApplicationContext, gctx: ContextType, user: Member, team_id: int):
        """Assign a player to a team in this thread's game."""
        
        if gctx.get_user_team(user) is not None:
            await dctx.respond("That player is already in a team!", ephemeral=True)
            return

        team = gctx.get_team(int(team_id))

        if team is None:
            await dctx.respond("Team not found!", ephemeral=True)
            return
        
        await team.add_user(user)
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
        """Reload this thread's game from its save file."""
        
        new_gctx =  await self.load_game(self.save_dir / f"{gctx.thread_id}.json")
        if new_gctx is not None:
            self.games[gctx.thread_id] = new_gctx
            await dctx.respond("Game reloaded successfully!", ephemeral=True)
        else:
            await dctx.respond("Failed to reload game!", ephemeral=True)

    async def clean(self, dctx: ApplicationContext, gctx: ContextType, delete_threads: bool = False):
        """Clean up and stop tracking this thread's game."""
        
        if gctx.scheduler_task is not None: gctx.scheduler_task.cancel()
        
        del self.games[gctx.thread_id]
        if (file := self.save_dir / f"{dctx.channel_id}.json").exists():
            file.move(self.save_dir / "archive" / file.name)
        
        asyncio.gather(*[team.role.delete() for team in gctx.teams if team.role])
        if delete_threads:
            asyncio.gather(*[obj.thread.delete() for obj in gctx.teams + [gctx] if obj.thread])
        else:
            await dctx.respond("Game thread successfully cleaned and unlinked!", ephemeral=True)
    
    async def view(self, dctx: ApplicationContext, gctx: ContextType):
        """Open the referee's Event Log view."""
        
        i = len(gctx.event_log) - 1
        while gctx.event_log[i].__type__ == "__reload__":
            i -= 1
        await dctx.respond(view=RefereeView(gctx, self, i), embed=event_embed(gctx, i), ephemeral=True)

