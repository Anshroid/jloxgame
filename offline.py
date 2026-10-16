import logging
import logging.config

from .state import GameContext

from typing import Any

import traceback
import pathlib
import os

class JLOXBotOffline[ContextType: GameContext]:
    def __init__(self, ctx_cls: type[ContextType], save_dir: pathlib.Path, logging_enabled: bool=True, *args: Any, **options: Any):
        super().__init__(*args, **options) # pyright: ignore[reportUnknownMemberType]
        
        self._ctx_cls = ctx_cls
        self.save_dir = save_dir
        self.games: dict[int, ContextType] = {}

        if logging_enabled:
            logging.config.fileConfig(pathlib.Path(__file__).parent / "logging.conf")
            
        self.logger = logging.getLogger("jloxgame")
        self.logger.setLevel(logging.DEBUG)    
        
        if not self.save_dir.exists():
            os.mkdir(self.save_dir)
        if not (self.save_dir / "archive").exists():
            os.mkdir(self.save_dir / "archive")
        
        self._load_games()
    
    def _load_games(self):
        for file in self.save_dir.iterdir():
            if file.suffix == ".json":
                game_thread_id = int(file.stem)

                try:
                    gctx = self._ctx_cls.load(self.save_dir, game_thread_id)
                except Exception:
                    self.logger.warning(f"invalid file in save folder (game not loaded): {file}")
                    traceback.print_exc()
                    continue
                
                self.games[game_thread_id] = gctx

                self.logger.info(f"loaded game {game_thread_id}")
    
    # UNIVERSAL GAME COMMANDS
    
    def create(self) -> ContextType:
        """Create and set up a new game!"""
        
        gctx = self._ctx_cls()
        gctx.thread_id = len(self.games)

        self.games[gctx.thread_id] = gctx
        
        return gctx