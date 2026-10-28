"""Hook for transaction logging.

SFWE12-16 (transaction logging) is owned by another team member. Every
service in this package calls :func:`emit` after a change so that module can
subscribe without touching this code::

    from clms import events
    events.subscribe(lambda name, user, details: my_log.write(...))
"""

from __future__ import annotations

from typing import Callable

Listener = Callable[[str, object, dict], None]
_listeners: list[Listener] = []


def subscribe(listener: Listener) -> None:
    _listeners.append(listener)


def unsubscribe(listener: Listener) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def emit(event: str, user, /, **details) -> None:
    for listener in list(_listeners):
        listener(event, user, details)
