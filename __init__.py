__title__="jloxgame"
__name__="jloxgame"

from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Define the __all__ variable
__all__ = []

# Import the submodules
from .bot import *
from .state import *