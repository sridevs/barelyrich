"""A namespaced view over session state, shared by the statement sessions."""

from collections.abc import Callable, MutableMapping


class SessionScope:
    """Reads and writes session values under this scope's key namespace."""

    def __init__(self, state: MutableMapping[str, object], key: Callable[[str], str] = str):
        self._state = state
        self._key = key

    def _get(self, name: str, default: object = None) -> object:
        return self._state.get(self._key(name), default)

    def _set(self, name: str, value: object) -> None:
        self._state[self._key(name)] = value

    def _drop(self, *names: str) -> None:
        for name in names:
            self._state.pop(self._key(name), None)

    def _drop_prefixed(self, *prefixes: str) -> None:
        scoped = tuple(self._key(prefix) for prefix in prefixes)
        for state_key in [key for key in self._state if key.startswith(scoped)]:
            del self._state[state_key]
