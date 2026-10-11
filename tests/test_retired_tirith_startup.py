"""Exercise the actual startup statements without agent/model/profile side effects."""
from __future__ import annotations

import ast
import builtins
from pathlib import Path
import types

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "model_router" / "scoped_agent.py"
LEGACY_MODULE = "tools.tirith_security"


def _startup_code():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_default_prepare_runtime")
    start = next(i for i, node in enumerate(fn.body)
                 if any(isinstance(n, ast.ImportFrom) and n.module == LEGACY_MODULE
                        for n in ast.walk(node)))
    end = next(i for i in range(start + 1, len(fn.body))
               if isinstance(fn.body[i], ast.ImportFrom)
               and fn.body[i].module == "hermes_cli.plugins")
    # Include discovery's actual caller to prove successful bootstrap advances,
    # while any unrelated import/initializer error stops before discovery.
    discovery = fn.body[end + 1]
    assert isinstance(discovery, ast.Expr)
    assert isinstance(discovery.value, ast.Call)
    assert isinstance(discovery.value.func, ast.Name)
    assert discovery.value.func.id == "discover_plugins"
    return compile(ast.Module(body=fn.body[start:end + 2], type_ignores=[]),
                   str(SOURCE), "exec")


def _run(monkeypatch, mode):
    calls = []
    legacy = types.ModuleType(LEGACY_MODULE)
    plugins = types.ModuleType("hermes_cli.plugins")

    def ensure_installed(**kwargs):
        calls.append(("legacy", kwargs))
        if mode == "initializer_failure":
            raise RuntimeError("synthetic initialization failure")

    if mode != "missing_symbol":
        legacy.ensure_installed = ensure_installed
    plugins.discover_plugins = lambda: calls.append(("plugins", {}))
    original = builtins.__import__

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        if name == LEGACY_MODULE:
            if mode == "retired":
                raise ModuleNotFoundError("synthetic retired module", name=LEGACY_MODULE)
            if mode == "missing_parent":
                raise ModuleNotFoundError("synthetic missing tools package", name="tools")
            if mode == "broken_dependency":
                raise ModuleNotFoundError("synthetic missing dependency", name="legacy_dependency")
            if mode == "other_import_error":
                raise ImportError("synthetic broken import", name=LEGACY_MODULE)
            if mode == "other_loader_error":
                raise ValueError("synthetic broken loader")
            return legacy
        if name == "hermes_cli.plugins":
            return plugins
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", importer)
    return calls, lambda: exec(_startup_code(), {"__builtins__": builtins})


def test_retired_module_does_not_block_actual_plugin_discovery(monkeypatch):
    calls, run = _run(monkeypatch, "retired")
    run()
    assert calls == [("plugins", {})]


def test_legacy_host_keeps_exact_initializer_before_discovery(monkeypatch):
    calls, run = _run(monkeypatch, "available")
    run()
    assert calls == [("legacy", {"log_failures": False}), ("plugins", {})]


@pytest.mark.parametrize("mode,error,missing_name", [
    ("missing_parent", ModuleNotFoundError, "tools"),
    ("broken_dependency", ModuleNotFoundError, "legacy_dependency"),
    ("missing_symbol", ImportError, None),
    ("other_import_error", ImportError, None),
    ("other_loader_error", ValueError, None),
    ("initializer_failure", RuntimeError, None),
])
def test_unrelated_failures_are_not_swallowed(monkeypatch, mode, error, missing_name):
    calls, run = _run(monkeypatch, mode)
    with pytest.raises(error) as caught:
        run()
    if missing_name is not None:
        assert caught.value.name == missing_name
    assert not any(name == "plugins" for name, _kwargs in calls)
    assert calls == ([("legacy", {"log_failures": False})]
                     if mode == "initializer_failure" else [])
