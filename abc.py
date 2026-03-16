from collections.abc import Callable, Coroutine
from typing import Any, TypeAlias, ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")

AsyncCallable: TypeAlias = Callable[_P, Coroutine[Any, Any, _R]]