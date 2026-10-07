# JLOXGame
JLOXGame is a framework for developing bots for JLOX games. It aims to fulfil the following objectives:
- Provide a simple mechanism for saving/loading of game state in a robust, recoverable way.
- Handle creation and configuration of games, including team management through roles and threads.
- Manage game timers that persist through game pauses and restarts
- Provide a simple interface to define game commands.

## The Event System
JLOXGame is based on an event system for managing game state. 
To define a JLOXGame bot, a class is designated as the *context class* for the bot, whose instances represent individual games and their state. 

Certain methods of the context class can be designated as *events* with an `@event()` decorator. These methods must have their signature fully typed, their parameters must be fully serializable (which is to say they must be made up of basic python types as listed in [this table](https://docs.python.org/3/library/json.html#py-to-json-table)), and they may not interact with the Discord API. 

Importantly, properties of the context class should only be modified within events, for the following reason:

A game save file consists exclusively of:
- The game's initialisation time and *game time* (unpaused time elapsed)
- The game's teams
- The game's events

When a game is loaded, JLOXGame will create a new instance of the context class and replay each of the events in turn to rebuild the game state at the time of saving. This allows the game to very easily be rewinded, or the state to be entirely rebuilt after a fix, circumventing a screwed up game state after an error.

As part of this, timers are managed through *scheduled events*. Every second, the bot will check if a new scheduled event should be processed, in which case it will be executed as usual. Events should only be scheduled from inside other events - scheduled events are not saved to the event log.

During game loading, the saved events are loaded into the scheduled events list, and the bot then steps through chronologically, processing events until it reaches the saved *game time*. It will then resume the game *from that point*, meaning a scheduled timer will ignore any time during which the bot was not running or paused, and timers will persist through reloads.

## Developing a bot
See below for how to setup a working environment - this section is for how bot code should look.

You should first define your context class, and define methods for every game action. JLOXGame will provide team IDs (internally, the corresponding Discord Role IDs), so these should be used as parameters for identifying teams. It should be possible to run an entire example game, using all mechanics, with the class in a python script.

At this point, JLOXGame can be introduced. Your context class should subclass `GameContext`, and all game actions should be marked with `@event()`. In your main file, create an instance of `JLOXBot` using your context class, and providing a save directory:

```py
bot = jloxgame.JLOXBot(GameState, pathlib.Path() / "save")
```

You may pass the additional flags `member_hostable` and `joinable` to specify what permissions users must have to create or join a game (there is a `/assign` command available to users with the `manage_roles` permission, to add players to teams manually)

You should then override the abstract `configure` method in your context class. This method is called both when a new game is created, and when `/configure` is run. This should prompt the user to set or modify settings in the game (preferably using modals), and then it should propagate these changes to the game state through an event. For now, there is a specific setup that must be used due to events not working properly at creation time, when team IDs don't yet exist.

You can now start to create normal commands with `@bot.command` as usual, or create *game commands* like so:

```py
@bot.game_command()
async def do_something(dctx: ApplicationContext, gctx: ContextClass):
    ...
```

JLOXGame will ensure that game commands are used in an appropriate context, and then pass the corresponding instance of your own context class for you to use.

All interactions with the Discord API should be done within the command's body, and in order to action changes to the game state the command should defer to an event, so that this action will be saved and loaded.

To create a timer, an event can be scheduled (must be from another event!) like so:

```py
self.schedule_event(0, 15, 0, self.unveto)
```

To attach Discord interaction (e.g. an announcement) to timer completion, you should attach a callback to the event. Event callbacks should be used sparingly, and will not be executed during game loading.

```py
async def unveto_callback(self, returned_value: int):
    team = self.get_team(returned_value)
    if team.thread:
        await team.thread.send("Your veto period has expired!")

@event(callback=unveto_callback)
def unveto(self, team_id: int) -> int:
    ...
```

Callbacks will receive as a parameter the returned value from the event, unless the event's return type is `None`.

## Setting up a development environment
To add JLOXGame to your project, ensure you have a git repository in your project directory, and then do the following:

```sh
git submodule add https://github.com/Anshroid/jloxgame/ 
```

Your repository will maintain a fixed version of JLOXGame until you manually update it, with the following command:

```sh
git pull --recurse-submodules
```