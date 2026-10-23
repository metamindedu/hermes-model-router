"""Match Hermes's native YAML policy, retaining legacy standalone support."""
from importlib import import_module

try:
    yaml = import_module("hermes_yaml")
except ModuleNotFoundError as exc:
    # Only an absent host adapter permits the legacy dependency. A broken
    # adapter/dependency must remain an error, not silently change parsing.
    if exc.name != "hermes_yaml":
        raise
    yaml = import_module("yaml")
