"""Plug-in registry: maps a slot and a name to the code that builds it.

A teammate makes their module available with one decorator::

    from orbit.core.registry import register

    @register("baseline", "ewma")
    class EwmaBaseline:
        def __init__(self, alpha: float = 0.2): ...
        def compute(self, ctx): ...

and switches to it in ``orbit.toml`` without touching the pipeline::

    [modules.baseline]
    use = "ewma"
    alpha = 0.3

Every registered implementation is automatically run through the contract
tests in ``tests/test_contracts.py``.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, TypeVar

from .interfaces import SLOTS

T = TypeVar("T")

_REGISTRY: dict[str, dict[str, Callable[..., Any]]] = {slot: {} for slot in SLOTS}
_BUILTINS_LOADED = False


class RegistryError(LookupError):
    pass


def register(slot: str, name: str) -> Callable[[T], T]:
    """Class or factory decorator that adds an implementation to a slot."""
    if slot not in _REGISTRY:
        raise RegistryError(f"unknown slot '{slot}'; slots are: {', '.join(SLOTS)}")

    def decorator(factory: T) -> T:
        existing = _REGISTRY[slot].get(name)
        if existing is not None and existing is not factory:
            raise RegistryError(f"'{name}' is already registered for slot '{slot}'")
        _REGISTRY[slot][name] = factory  # type: ignore[assignment]
        return factory

    return decorator


def _load_builtins() -> None:
    """Import the bundled modules so their @register decorators run."""
    global _BUILTINS_LOADED
    if not _BUILTINS_LOADED:
        _BUILTINS_LOADED = True
        importlib.import_module("orbit.modules")


def available(slot: str) -> list[str]:
    """Names registered for a slot."""
    _load_builtins()
    if slot not in _REGISTRY:
        raise RegistryError(f"unknown slot '{slot}'")
    return sorted(_REGISTRY[slot])


def create(slot: str, name: str, **options: Any) -> Any:
    """Build the implementation ``name`` for ``slot`` with the given options.

    Raises a clear error if the name is unknown, the options are wrong, or the
    built object does not have the methods its slot requires.
    """
    _load_builtins()
    factories = _REGISTRY.get(slot)
    if factories is None:
        raise RegistryError(f"unknown slot '{slot}'; slots are: {', '.join(SLOTS)}")
    factory = factories.get(name)
    if factory is None:
        known = ", ".join(sorted(factories)) or "none"
        raise RegistryError(f"no '{slot}' module called '{name}'; available: {known}")
    try:
        instance = factory(**options)
    except TypeError as exc:
        raise RegistryError(f"bad options for {slot} '{name}': {exc}") from exc
    interface = SLOTS[slot]
    if not isinstance(instance, interface):
        raise RegistryError(
            f"{slot} '{name}' does not implement {interface.__name__}; "
            f"check the method names in orbit/core/interfaces.py"
        )
    return instance
