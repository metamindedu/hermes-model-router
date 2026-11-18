"""Match Hermes's native YAML policy, retaining legacy standalone support."""
import copy
import hashlib
from collections import OrderedDict
from importlib import import_module
from threading import Lock

try:
    _module = import_module("hermes_yaml")
except ModuleNotFoundError as exc:
    # Only an absent host adapter permits the legacy dependency. A broken
    # adapter/dependency must remain an error, not silently change parsing.
    if exc.name != "hermes_yaml":
        raise
    _module = import_module("yaml")


class ContentMemo:
    """Results keyed by the exact input content (SHA-256), so a hit is what a fresh computation on
    the same content returns. A settings status reads each profile's config.yaml dozens of times;
    this makes that one parse per distinct content. Callers get a deep copy and may mutate it.
    Bounded; exceptions are never cached."""

    def __init__(self, limit=64):
        self._limit = limit
        self._items = OrderedDict()
        self._lock = Lock()

    def get(self, key, compute):
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return copy.deepcopy(self._items[key])
        value = compute()
        with self._lock:
            self._items[key] = copy.deepcopy(value)
            self._items.move_to_end(key)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
        return value

    def clear(self):
        with self._lock:
            self._items.clear()


_PARSED = ContentMemo()


def content_key(stream):
    if isinstance(stream, str):
        return ("str", hashlib.sha256(stream.encode("utf-8", "surrogatepass")).hexdigest())
    if isinstance(stream, (bytes, bytearray)):
        return ("bytes", hashlib.sha256(bytes(stream)).hexdigest())
    return None


class _Yaml:
    """The selected YAML module with a content-memoized ``safe_load``; every other attribute
    (YAMLError, safe_dump, ...) is the module's own."""

    def __getattr__(self, name):
        return getattr(_module, name)

    def safe_load(self, stream):
        key = content_key(stream)
        if key is None:
            return _module.safe_load(stream)
        return _PARSED.get(key, lambda: _module.safe_load(stream))


yaml = _Yaml()
