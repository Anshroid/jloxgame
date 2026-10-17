from datetime import timedelta
from inspect import Signature, signature
import json
from typing import TYPE_CHECKING, Any

from discord import ButtonStyle, Embed, InputTextStyle, Interaction, SelectOption
from discord.ui import Button, DesignerModal, View, Select, InputText, Label

from jloxgame.state import BoundEvent, EventInstance, GameContext
if TYPE_CHECKING:
    from jloxgame.bot import JLOXBot

def event_embed(gctx: GameContext, i: int) -> Embed:
    inst = gctx.event_log[i]
    embed = Embed()
    embed.title = f"Event {i}: `{inst.__type__}`"
    bound_event: BoundEvent[GameContext, Any, Any] = getattr(gctx, inst.__type__)
    
    sig = signature(bound_event.event.func, eval_str=True)
    params = {k: v for k, v in sig.parameters.items() if k != "self"}
    if len(params) > 25:
        embed.description = json.dumps(inst.to_dict(), indent=4)
    else:
        for value, key in zip(inst.args, params.keys()):
            embed.add_field(name=key, value=json.dumps(value))
        
        for key, value in inst.kwargs.items():
            embed.add_field(name=key, value=json.dumps(value))
    
    embed.set_footer(text=f"Game time: {timedelta(seconds=inst.__time__ // 1000)}" + ("\nThis event was scheduled and cannot be modified." if inst.was_scheduled else ""))
    
    return embed

class RefereeView[ContextType: GameContext](View):
    def __init__(self, gctx: ContextType, bot: JLOXBot[ContextType], i: int):
        super().__init__(timeout=None)
        
        self.i = i
        self.gctx = gctx
        self.bot = bot
        
        self.left_btn = Button[Any](label="<", style=ButtonStyle.blurple)
        self.left_btn.callback = self.left
        
        self.edit_btn = Button[Any](label="Edit", emoji="✍️", style=ButtonStyle.gray)
        self.edit_btn.callback = self.edit
        
        self.toggle_btn = Button[Any](label="Disable", emoji="❎", style=ButtonStyle.red)
        self.toggle_btn.callback = self.toggle
        
        # self.add_btn = Button[Any](label="Add New After", emoji="➕", style=ButtonStyle.green)
        # self.add_btn.callback = self.add
        
        self.right_btn = Button[Any](label=">", style=ButtonStyle.blurple)
        self.right_btn.callback = self.right
        
        low = max(self.i-12, 0)
        self.jump_dropdown = Select(options=[
            SelectOption(label=f"{timedelta(seconds=inst.__time__ // 1000)} - {inst.__type__}", value=str(j), default=j == self.i) 
            for inst, j in zip(self.gctx.event_log[low:self.i+13], range(low, self.i+13))
        ], placeholder="Jump to an event...")
        self.jump_dropdown.callback = self.jump
        
        self.add_item(self.left_btn)
        self.add_item(self.edit_btn)
        self.add_item(self.toggle_btn)
        # self.add_item(self.add_btn)
        self.add_item(self.right_btn)
        
        self.add_item(self.jump_dropdown)
        
    async def update(self):
        embed = event_embed(self.gctx, self.i)
        inst = self.gctx.event_log[self.i]
        
        self.left_btn.disabled = self.i == 0
        self.right_btn.disabled = self.i == len(self.gctx.event_log) - 1
        
        self.edit_btn.disabled = self.toggle_btn.disabled = inst.was_scheduled
        
        self.toggle_btn.label = "Enable" if inst.__disabled__ else "Disable"
        self.toggle_btn.emoji = "☑️" if inst.__disabled__ else "❎"
        self.toggle_btn.style = ButtonStyle.green if inst.__disabled__ else ButtonStyle.red
        
        low = max(self.i-12, 0)
        self.jump_dropdown.options=[
            SelectOption(label=f"{timedelta(seconds=inst.__time__ // 1000)} - {inst.__type__}", value=str(j), default=j == self.i) 
            for inst, j in zip(self.gctx.event_log[low:self.i+13], range(low, self.i+13))
        ]
        
        if self.parent: await self.parent.edit_original_response(embed=embed, view=self)
        
    async def left(self, interaction: Interaction):
        self.i -= 1
        while self.gctx.event_log[self.i].__type__ == "__reload__" and self.i > 0:
            self.i -= 1
        await self.update()
        await interaction.response.defer()
    
    async def edit(self, interaction: Interaction):
        bound_event: BoundEvent[ContextType, Any, Any] = getattr(self.gctx, self.gctx.event_log[self.i].__type__)
        sig = signature(bound_event.event.func, eval_str=True)
        modal = EditEventModal(self.gctx.event_log[self.i], sig)
        await interaction.response.send_modal(modal)
        
        if await modal.wait():
            if modal.overall_input is not None:
                try:
                    assert modal.overall_input.value is not None
                    event_dict = json.loads(modal.overall_input.value)
                    inst = EventInstance(
                        event_dict["__type__"], 
                        event_dict["__time__"], 
                        event_dict["args"], 
                        event_dict["kwargs"], 
                        False,
                        event_dict.get("__disabled__", False)
                    )
                    
                    self.gctx.event_log[self.i] = inst
                
                except Exception:
                    await interaction.respond("Something went wrong - could not edit event!", ephemeral=True)
                    return
            
            else:
                try:
                    assert modal.kwargs is not None
                    assert modal.kwargs.value is not None
                    
                    args = [json.loads(input.value) for input in modal.param_inputs if input.value is not None]
                    kwargs = json.loads(modal.kwargs.value)
                    inst = EventInstance(
                        self.gctx.event_log[self.i].__type__, 
                        self.gctx.event_log[self.i].__time__, 
                        args, 
                        kwargs, 
                        False,
                        self.gctx.event_log[self.i].__disabled__, 
                    )
                    
                    self.gctx.event_log[self.i] = inst
                    
                except Exception:
                    await interaction.respond("Something went wrong - could not edit event!", ephemeral=True)
                    return
        
        await self.gctx.save()
        assert self.gctx.file
        new_gctx = await self.bot.load_game(self.gctx.file)
        if new_gctx is not None:
            self.bot.games[self.gctx.thread_id] = new_gctx
            self.gctx = new_gctx
        
        await self.update()
    
    async def toggle(self, interaction: Interaction):
        await interaction.response.defer()
        self.gctx.event_log[self.i].__disabled__ = not self.gctx.event_log[self.i].__disabled__
        
        await self.gctx.save()
        assert self.gctx.file
        new_gctx = await self.bot.load_game(self.gctx.file)
        if new_gctx is not None:
            self.bot.games[self.gctx.thread_id] = new_gctx
            self.gctx = new_gctx

        await self.update()
        
    async def add(self, interaction: Interaction):
        await interaction.response.defer()
        await self.update()        
    
    async def right(self, interaction: Interaction):
        self.i += 1
        while self.gctx.event_log[self.i].__type__ == "__reload__" and self.i < len(self.gctx.event_log) - 1:
            self.i += 1
        await self.update()
        await interaction.response.defer()
    
    async def jump(self, interaction: Interaction):
        assert self.jump_dropdown.values is not None
        self.i = int(self.jump_dropdown.values[0])
        
        await self.update()
        await interaction.response.defer()
        
class EditEventModal(DesignerModal):
    def __init__(self, inst: EventInstance, sig: Signature) -> None:
        super().__init__(title=f"Edit event {inst.__type__} ({timedelta(seconds=inst.__time__ // 1000)})", timeout=None) # pyright: ignore[reportUnknownMemberType]
        
        self.overall_input: InputText | None = None
        self.param_inputs: list[InputText] = []
        self.kwargs: InputText | None = None
        
        params = {k: v for k, v in sig.parameters.items() if k != "self"}
        if len(params) > 4:
            self.overall_input = InputText(value=json.dumps(inst.to_dict(), indent=4), style=InputTextStyle.long)
            self.add_item(Label("Event JSON:", self.overall_input)) # pyright: ignore[reportUnknownMemberType]
        else:
            for value, key in zip(inst.args, params.keys()):
                self.param_inputs.append(InputText(value=json.dumps(value)))
                self.add_item(Label(key, self.param_inputs[-1])) # pyright: ignore[reportUnknownMemberType]
        
            self.kwargs = InputText(value=json.dumps(inst.kwargs, indent=4), style=InputTextStyle.long)
            self.add_item(Label("Keyword Arguments (as JSON dict):", self.kwargs)) # pyright: ignore[reportUnknownMemberType]
            
    async def callback(self, interaction: Interaction):
        await interaction.response.defer()