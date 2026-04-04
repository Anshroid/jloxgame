from discord import (
    SlashCommand, ClientException, ApplicationContext,
    SlashCommandGroup
)
from typing import OrderedDict, Callable, Any, Concatenate, cast
from inspect import Parameter

from discord.ext.commands.cooldowns import CooldownMapping, MaxConcurrency # pyright: ignore[reportMissingTypeStubs]
from .abc import AsyncCallable

class GameCommand[S](SlashCommand):
    def __new__(cls, *args: Any, **kwargs: Any) -> GameCommand[S]:
        return cast(GameCommand[S], super().__new__(cls, *args, **kwargs)) # pyright: ignore[reportUnknownMemberType]
    
    def __init__(self, func: Callable[..., Any], *args: Any, getGameCtx: Callable[[int], S], **kwargs: Any) -> None:
        super().__init__(func, *args, **kwargs) # pyright: ignore[reportUnknownMemberType]

        async def applied(dctx: ApplicationContext, *args: Any, **kwargs: Any):
                gctx = getGameCtx(dctx.channel_id)
                await func(dctx, gctx, *args, **kwargs)

        self.callback = applied
        
    def _check_required_params(self: SlashCommand, params: OrderedDict[str, Parameter]):
            params_iter = iter(params.items())
            required_params = (
                ["self", "discord-context", "game-context"] if self.attached_to_group or self.cog else ["discord-context", "game-context"]
            )
            for p in required_params:
                try:
                    next(params_iter)
                except StopIteration:
                    raise ClientException(
                        f'Callback for {self.name} command is missing "{p}" parameter.'
                    )

            return params_iter

class GameCommandGroup[S](SlashCommandGroup):
    def __new__(cls, *args: Any, **kwargs: Any) -> GameCommandGroup[S]:
        return cast(GameCommandGroup[S], super().__new__(cls, *args, **kwargs)) # pyright: ignore[reportUnknownMemberType]

    def __init__(self, getGameCtx: Callable[[int], S], name: str, description: str | None = None, guild_ids: list[int] | None = None, parent: GameCommandGroup[S] | None = None, cooldown: CooldownMapping | None = None, max_concurrency: MaxConcurrency | None = None, **kwargs: Any) -> None:
        super().__init__(name, description, guild_ids, parent, cooldown, max_concurrency, **kwargs) # pyright: ignore[reportUnknownMemberType]
        self.getGameCtx = getGameCtx

    def game_command(self, **kwargs: Any):
        def decorator(func: AsyncCallable[Concatenate[ApplicationContext, S, ...], None]): # pyright: ignore[reportUnknownParameterType]
            return self.command(cls=GameCommand, getGameCtx=self.getGameCtx, **kwargs)(func) # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType] 
        
        return decorator
    
    def create_subgroup(self, name: str, description: str | None = None, guild_ids: list[int] | None = None, **kwargs: Any) -> GameCommandGroup[S]:
        if self.parent is not None:
            raise Exception("A subcommand group cannot be added to a subcommand group")

        sub_command_group = GameCommandGroup[S](
            self.getGameCtx, name, description, guild_ids, parent=self, **kwargs
        )
        self.subcommands.append(sub_command_group)
        return sub_command_group