"""Scoped native-delegation settings using the existing one-shot plan boundary.

This module never launches agents and never writes YAML. Only the four owned
keys are passed to Service's supported Hermes config writer.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from importlib.machinery import BYTECODE_SUFFIXES, EXTENSION_SUFFIXES, SOURCE_SUFFIXES
import json
import os
from pathlib import Path
import re
import time
import uuid
from typing import Any

from . import effective_config, native_settings as ns

AUTO_ROUTING_SUPPORTED = True

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_BACKEND = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


def _safe_path(path: Path) -> bool:
    try:
        return path.is_absolute() and all(
            not item.is_symlink() and not (hasattr(item, "is_junction") and item.is_junction())
            for item in (path, *path.parents)
        )
    except OSError:
        return False


def inventory(service) -> list[str]:
    result = []
    for name in service._discover_profiles():
        home = service._profile_home(name)
        config = home / "config.yaml"
        if _safe_path(home) and _safe_path(config) and home.is_dir() and config.is_file():
            result.append(name)
    return result


def validate_native_targets(service, profiles) -> None:
    """Never authorize one inventory then let core resolve a same-named foreign profile."""
    from .native_delegation import _inventory
    if any(not _inventory(service, row["name"]) for row in profiles["profiles"]):
        raise ValueError("native profile resolution does not match the selected origin inventory")


def _code_signature(service, profile: str) -> str | None:
    """Presence and exact code identity, not current-session registration proof."""
    from . import installation
    try:
        from agent.delegation_provider import DelegationProvider
        if not callable(getattr(DelegationProvider, "route_task", None)):
            return None
        home = service._profile_home(profile)
        if not installation.timeout_python_enabled(home):
            return None
        root = home / "plugins" / "model-router"
        files = [root / "__init__.py", root / "plugin.yaml", root / "model_router/native_delegation.py",
                 root / "model_router/native_watchdog.py", root / "model_router/native_settings.py",
                 root / "model_router/native_service.py", root / "model_router/service.py"]
        payloads = []
        for path in files:
            if not _safe_path(path) or not path.is_file() or path.stat().st_size > 256 * 1024:
                return None
            payloads.append(path.read_bytes())
        if b"register_native_delegation" not in payloads[0]:
            return None
        mode_snapshot = effective_config.read_key_scoped(home, ("plugins.isolation",))
        if mode_snapshot.warnings or not mode_snapshot.effective_available:
            return None
        isolation = mode_snapshot.effective("plugins.isolation")
        if isolation not in (None, "", "in_process", "in-process"):
            return None  # routed watchdog ContextVars cannot cross the plugin host
        return hashlib.sha256(b"\0".join(payloads)).hexdigest()
    except (ImportError, OSError, ValueError, RuntimeError):
        return None


def _auto_code_signature(service, profile: str, code: str | None) -> str | None:
    """Feature-specific installed code declaration, never importing foreign modules.

    General native support also accepts pre-auto packages. Require the coordinated
    literal feature contract in every new component, bind their exact bytes, and
    refuse alternate import-loader candidates rather than inspecting the wrong .py.
    This is on-disk capability, not current-session registration proof.
    """
    if code is None:
        return None
    root = service._profile_home(profile) / 'plugins/model-router/model_router'
    names = ('native_delegation', 'native_watchdog', 'native_settings', 'native_service', 'config_writer')
    suffixes = tuple(set((*BYTECODE_SUFFIXES, *EXTENSION_SUFFIXES, '.pyd')))
    def shadowed(stem):
        return any(item.name == stem or (item.name.startswith(stem + '.') and item.name.endswith(suffixes))
                   for item in root.iterdir())
    try:
        payloads = []
        for name in names:
            path = root / (name + '.py')
            if not _safe_path(path) or not path.is_file() or path.stat().st_size > 256 * 1024 or shadowed(name):
                return None
            data = path.read_bytes()
            tree = ast.parse(data.decode('utf-8-sig'))
            markers = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                       and any(isinstance(target, ast.Name) and target.id == 'AUTO_ROUTING_SUPPORTED'
                               for target in (node.targets if isinstance(node, ast.Assign) else [node.target]))]
            if (len(markers) != 1 or not isinstance(markers[0].value, ast.Constant)
                    or markers[0].value.value is not True):
                return None
            payloads.append(data)
        for name, data in zip(names, payloads):
            path = root / (name + '.py')
            if not _safe_path(path) or path.read_bytes() != data or shadowed(name):
                return None
        if service._native_delegation_code_signature(profile) != code:
            return None
        return hashlib.sha256(code.encode() + b'\0' + b'\0'.join(payloads)).hexdigest()
    except (OSError, ValueError, SyntaxError, UnicodeError, RecursionError):
        return None


def _role_intro_code_signature(service, profile: str, code: str | None) -> str | None:
    """Observe installed provider and resolver as a single feature identity."""
    if code is None:
        return None
    from .role_metadata import read_bounded
    root = service._profile_home(profile) / 'plugins/model-router/model_router'
    try:
        payloads = []
        for name in ('native_delegation', 'role_metadata'):
            suffixes = tuple(set((*BYTECODE_SUFFIXES, *EXTENSION_SUFFIXES, '.pyd')))
            if any(p.name == name or (p.name.startswith(name + '.') and p.name.endswith(suffixes)) for p in root.iterdir()):
                return None
            data, _ = read_bounded(root / (name + '.py'), root, 256 * 1024)
            reference, _ = read_bounded(Path(__file__).parent / (name + '.py'), Path(__file__).parent, 256 * 1024)
            # Recognize only the provider/resolver pair whose implementation this
            # manager actually knows. Unknown future implementations fail closed.
            if data is None or reference is None or data != reference:
                return None
            tree = ast.parse(data.decode('utf-8-sig'))
            markers = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ROLE_INTRO_INHERITANCE_SCHEMA' for t in n.targets)]
            if len(markers) != 1 or not isinstance(markers[0].value, ast.Constant) or type(markers[0].value.value) is not int or markers[0].value.value != 1:
                return None
            if name == 'native_delegation':
                provider = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == 'ModelRouterProfilesProvider')
                method = next(n for n in provider.body if isinstance(n, ast.FunctionDef) and n.name == 'task_parameters')
                if not any(isinstance(n, ast.ImportFrom) and n.module == 'role_metadata' and any(x.name == 'resolve' for x in n.names) for n in ast.walk(method)) or not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'resolve' for n in ast.walk(method)):
                    return None
            payloads.append(data)
        if service._native_delegation_code_signature(profile) != code:
            return None
        for name, data in zip(('native_delegation', 'role_metadata'), payloads):
            if read_bounded(root / (name + '.py'), root, 256 * 1024)[0] != data:
                return None
        return hashlib.sha256(code.encode() + b'\0' + b'\0'.join(payloads)).hexdigest()
    except Exception:
        return None


def _check_role_record(service, record):
    if _role_intro_code_signature(service, record['profile'], record['code']) != record.get('role_code'):
        from .service import RevisionConflict
        raise RevisionConflict('role inheritance implementation changed')


def _check_auto_record(service, record):
    if record['after'][ns.KEY_BACKEND] == 'model-router-auto':
        signature = _auto_code_signature(service, record['profile'], record['code'])
        if signature is None or signature != record.get('auto_code'):
            from .service import RevisionConflict
            raise RevisionConflict('automatic routing implementation is unavailable or changed')


def read_snapshot(service, profile):
    return effective_config.read_native_delegation_settings(service._profile_home(profile))


def _plain(snapshot, profile, names):
    if snapshot.warnings or snapshot.managed_keys or not snapshot.effective_available:
        raise ValueError("native delegation is managed or unavailable")
    if any(snapshot.raw(key) != snapshot.effective(key) for key in ns.KEYS):
        raise ValueError("effective native delegation differs from editable config")
    backend = snapshot.raw(ns.KEY_BACKEND)
    if backend is None or backend == "":
        backend = "default"
    if not isinstance(backend, str) or not _BACKEND.fullmatch(backend):
        raise ValueError("unsupported backend declaration")
    policy = snapshot.raw(ns.KEY_POLICY)
    policy = ns.default_policy() if policy is None else ns.validate_policy_block(profile, policy)
    profiles = snapshot.raw(ns.KEY_PROFILES)
    if profiles is None:
        profiles = {"profiles": [], "default": None}
    else:
        # A deleted target is safe metadata, not an advanced/secret declaration.
        # Keep it editable for revocation; desired saves still require live targets.
        declared = profiles.get("profiles") if isinstance(profiles, dict) else None
        declared_names = [row.get("name") for row in declared if isinstance(row, dict)] if isinstance(declared, list) else []
        profiles = ns.validate_profiles_block(profiles, declared_names)
    auto_policy = snapshot.raw(ns.KEY_AUTO_POLICY)
    auto_policy = ns.default_policy() if auto_policy is None else ns.validate_policy_block(profile, auto_policy, backend="model-router-auto")
    return backend, policy, profiles, auto_policy


def status(service, profile: str) -> dict[str, Any]:
    code = service._native_delegation_code_signature(profile)
    role_code = _role_intro_code_signature(service, profile, code)
    result = {"schema": 1, "supported": code is not None, "editable": False, "backend": "unavailable",
              "role_intro_inheritance": {"schema": 1, "supported": role_code is not None, "code_identity": role_code, "activation": "new_session_or_supported_rebuild"},
              "digest": "", "policy": ns.default_policy(),
              "profile_routes": {"profiles": [], "default": None}, "auto_policy": ns.default_policy(), "auto_supported": False, "warnings": []}
    try:
        names = inventory(service)
        if profile not in names:
            raise ValueError("unsafe profile")
        snapshot = service._read_native_delegation_snapshot(profile)
        backend, policy, profiles, auto_policy = _plain(snapshot, profile, names)
        auto_code = _auto_code_signature(service, profile, code)
        from .service import _digest
        result.update(backend=backend, policy=policy, profile_routes=profiles, auto_policy=auto_policy, auto_supported=auto_code is not None,
                      digest=_digest({"snapshot": snapshot.cas_digest, "code": code, "auto_code": auto_code, "role_code": role_code, "profile": profile}),
                      editable=code is not None)
        if any(row["name"] not in names for row in profiles["profiles"]):
            result["warnings"].append("profile_target_missing_remove_from_allowlist")
        if code is None:
            result["warnings"].append("native_delegation_code_or_activation_unavailable")
    except (ValueError, RuntimeError, OSError, TypeError, KeyError):
        # Never serialize advanced declarations, endpoint/key fields or exception text.
        result["warnings"].append("native_delegation_readonly")
    return result


def preview(service, body: dict[str, Any]) -> dict[str, Any]:
    from .service import _digest, _json_bytes, _atomic_write, _FileLock, _now, RevisionConflict
    if not isinstance(body, dict) or set(body) != {"expected_revision", "updates"}:
        raise ValueError("native delegation preview has unknown or missing fields")
    if type(body["expected_revision"]) is not int or body["expected_revision"] < 0:
        raise ValueError("expected_revision must be a nonnegative integer")
    updates = body["updates"]
    if not isinstance(updates, list) or not 1 <= len(updates) <= 32:
        raise ValueError("native delegation requires one to 32 explicit origin profiles")
    with _FileLock(service._lock_path):
        stored = service._load_store()
        revision = stored["revision"] if stored else 0
        if revision != body["expected_revision"]:
            raise RevisionConflict("settings revision changed")
        names = inventory(service)
        records, changes, seen = [], [], set()
        fields = {"profile", "expected_digest", "backend", "policy", "profile_routes", "allow_additional_cost", "allow_profile_access"}
        for update in updates:
            if not isinstance(update, dict) or set(update) != fields:
                raise ValueError("invalid native delegation update fields")
            profile = service._require_profile(update["profile"], names)
            if profile in seen:
                raise ValueError("duplicate origin profile")
            seen.add(profile)
            dto = status(service, profile)
            if dto["editable"] is not True or not isinstance(update["expected_digest"], str) or not _HEX.fullmatch(update["expected_digest"]):
                raise ValueError("native delegation editing is unavailable")
            if dto["digest"] != update["expected_digest"]:
                raise RevisionConflict("native delegation changed; reload before saving")
            backend = update["backend"]
            if not isinstance(backend, str) or backend not in ns.BACKENDS:
                raise ValueError("unsupported native delegation backend")
            if backend == 'model-router-auto' and dto['auto_supported'] is not True:
                raise ValueError('automatic routing is unsupported by this installed profile; update it first')
            if type(update["allow_profile_access"]) is not bool:
                raise ValueError("profile execution confirmation must be boolean")
            policy_backend = "model-router-auto" if backend == "model-router-auto" else "model-router"
            policy_key = ns.KEY_AUTO_POLICY if backend == "model-router-auto" else ns.KEY_POLICY
            policy = ns.build_policy_block(profile, update["policy"], update["allow_additional_cost"], backend=policy_backend)
            profiles = ns.validate_profiles(update["profile_routes"], names)
            validate_native_targets(service, profiles)
            old_profiles = dto["profile_routes"]
            old_descriptions = {row['name']: row['description'] for row in old_profiles['profiles']}
            if not dto['role_intro_inheritance']['supported'] and any(row['description'] == '' and (row['name'] not in old_descriptions or old_descriptions[row['name']] != '') for row in profiles['profiles']):
                raise ValueError('role inheritance is unsupported by this installed profile')
            added = {row["name"] for row in profiles["profiles"]} - {row["name"] for row in old_profiles["profiles"]}
            default_grant = profiles["default"] is not None and profiles["default"] != old_profiles["default"]
            if (added or default_grant) and update["allow_profile_access"] is not True:
                raise ValueError("adding profile execution authority requires explicit permission")
            if backend in ("model-router", "model-router-auto") and service.routing_config(profile).get("enabled") is not True:
                raise ValueError("purpose routing is disabled; preserve the explicit opt-out")
            snapshot = service._read_native_delegation_snapshot(profile)
            code = service._native_delegation_code_signature(profile)
            auto_code = _auto_code_signature(service, profile, code)
            role_code = _role_intro_code_signature(service, profile, code)
            # Do not pair the DTO with a later, independently changed snapshot.
            if dto["digest"] != _digest({"snapshot": snapshot.cas_digest, "code": code, "auto_code": auto_code, "role_code": role_code, "profile": profile}):
                raise RevisionConflict("native delegation changed during preview")
            if backend == 'model-router-auto' and auto_code is None:
                raise RevisionConflict('automatic routing support changed during preview')
            before = {key: snapshot.raw(key) for key in ns.KEYS}
            desired = {**before, policy_key: policy, ns.KEY_PROFILES: {"schema": 1, **profiles}, ns.KEY_BACKEND: backend}
            for key in (ns.KEY_POLICY, ns.KEY_AUTO_POLICY, ns.KEY_PROFILES, ns.KEY_BACKEND):
                if before[key] != desired[key]:
                    changes.append({"profile": profile, "field": key, "before": copy.deepcopy(before[key]), "after": copy.deepcopy(desired[key])})
            records.append({"profile": profile, "before": before, "after": desired,
                            "cas": snapshot.cas_digest, "provenance": snapshot.provenance_digest, "code": code, "auto_code": auto_code, "role_code": role_code})
        plan_id = uuid.uuid4().hex
        expires = time.time() + 300
        plan = {"kind": "native_delegation", "owner_profile": service.active_profile(), "revision": revision,
                "settings_digest": _digest(stored), "expires_epoch": expires, "records": records, "changes": changes}
        path = service.store_path.parent / "plans" / (plan_id + ".json")
        if not _safe_path(path.parent):
            raise ValueError("unsafe plan directory")
        _atomic_write(path, _json_bytes(plan))
        return {"plan_id": plan_id, "changes": changes, "warnings": ["Saved backend is not proof of current-session activation; no running child is restarted."],
                "expires_at": expires}


def apply_consumed(service, plan, plan_id):
    """Called after Service.apply owns the lock and consumes the plan exactly once."""
    from .service import _digest, _now, RevisionConflict
    stored = service._load_store()
    if _digest(stored) != plan["settings_digest"]:
        raise RevisionConflict("model/routing settings changed since preview")
    names = inventory(service)
    records = plan["records"]
    snapshots = {}
    # Complete preflight before the first write, including NOOP targets.
    for record in records:
        profile = service._require_profile(record["profile"], names)
        if service._native_delegation_code_signature(profile) != record["code"] or record["code"] is None:
            raise RevisionConflict("native delegation implementation changed")
        _check_auto_record(service, record)
        _check_role_record(service, record)
        snapshot = service._read_native_delegation_snapshot(profile)
        _plain(snapshot, profile, names)
        if snapshot.cas_digest != record["cas"]:
            raise RevisionConflict("native delegation configuration changed")
        validate_native_targets(service, ns.validate_profiles_block(record["after"][ns.KEY_PROFILES], names))
        for key, backend in ((ns.KEY_POLICY, "model-router"), (ns.KEY_AUTO_POLICY, "model-router-auto")):
            if record["after"][key] is not None:
                ns.validate_policy_block(profile, record["after"][key], backend=backend)
        if record["after"][ns.KEY_BACKEND] in ("model-router", "model-router-auto") and service.routing_config(profile).get("enabled") is not True:
            raise RevisionConflict("purpose routing was disabled")
        snapshots[profile] = {key: snapshot.raw(key) for key in ns.KEYS}
    writes = [{"profile": r["profile"], "key": key, "after": r["after"][key]} for r in records
              for key in (ns.KEY_POLICY, ns.KEY_AUTO_POLICY, ns.KEY_PROFILES, ns.KEY_BACKEND) if r["before"][key] != r["after"][key]]
    pending, applied = list(writes), []
    try:
        for item in writes:
            profile, key = item["profile"], item["key"]
            record = next(r for r in records if r["profile"] == profile)
            _check_auto_record(service, record)
            _check_role_record(service, record)
            snapshot = service._read_native_delegation_snapshot(profile)
            _plain(snapshot, profile, inventory(service))
            if (snapshot.provenance_digest != record["provenance"] or
                    {k: snapshot.raw(k) for k in ns.KEYS} != snapshots[profile] or
                    service._native_delegation_code_signature(profile) != record["code"]):
                raise RevisionConflict("native delegation changed during apply")
            service._write_key(profile, key, item["after"])
            # A successful writer return alone is not proof of persistence.
            expected = dict(snapshots[profile], **{key: item["after"]})
            observed = service._read_native_delegation_snapshot(profile)
            if ({k: observed.raw(k) for k in ns.KEYS} != expected or
                    any(observed.effective(k) != expected[k] for k in ns.KEYS) or
                    observed.provenance_digest != record["provenance"] or observed.warnings or observed.managed_keys):
                raise RevisionConflict("native delegation exact readback failed")
            snapshots[profile] = expected
            applied.append({"profile": profile, "key": key})
            pending.pop(0)
        # Final capability, target inventory, provenance and NOOP state checks.
        current_names = inventory(service)
        for record in records:
            profile = service._require_profile(record["profile"], current_names)
            _check_auto_record(service, record)
            _check_role_record(service, record)
            observed = service._read_native_delegation_snapshot(profile)
            _plain(observed, profile, current_names)
            validate_native_targets(service, ns.validate_profiles_block(record["after"][ns.KEY_PROFILES], current_names))
            if (service._native_delegation_code_signature(profile) != record["code"] or
                    observed.provenance_digest != record["provenance"] or
                    {key: observed.raw(key) for key in ns.KEYS} != snapshots[profile]):
                raise RevisionConflict("native delegation final state changed")
        if _digest(service._load_store()) != plan["settings_digest"]:
            raise RevisionConflict("model/routing settings changed during apply")
    except Exception:
        receipt = {"status": "partial", "plan_id": plan_id, "revision": plan["revision"], "applied": applied,
                   "remaining": [{"profile": row["profile"], "key": row["key"]} for row in pending], "finished_at": _now()}
        service._store_apply(receipt)
        return receipt
    receipt = {"status": "applied" if writes else "no_change", "plan_id": plan_id, "revision": plan["revision"],
               "applied": applied, "remaining": [], "finished_at": _now()}
    service._store_apply(receipt)
    return receipt


INITIAL_SETUP_SCHEMA = 1
INITIAL_SETUP_BACKEND = 'model-router-auto'
_INITIAL_KEYS = (*ns.KEYS, 'plugins.enabled', 'plugins.disabled', 'skills.disabled', 'plugins.isolation', 'platform_toolsets')


def _initial_raw(service, profile):
    """Read full user data in memory only, bound to the same stable scoped snapshot."""
    from .service import _digest
    home = service._profile_home(profile)
    path = home / 'config.yaml'
    first = path.read_bytes()
    snapshot = effective_config.read_key_scoped(home, _INITIAL_KEYS)
    raw = effective_config._helpers().read_user_config_raw(path)
    if not isinstance(raw, dict) or path.read_bytes() != first:
        raise ValueError('initial setup configuration changed')
    if snapshot.warnings or snapshot.managed_keys or not snapshot.effective_available:
        raise ValueError('initial setup requires editable configuration')
    if any(snapshot.raw(key) != snapshot.effective(key) for key in _INITIAL_KEYS):
        raise ValueError('initial setup effective configuration differs')
    return raw, snapshot, _digest(raw)


def _initial_preservation(raw, delegation_present):
    from .service import _digest
    value = copy.deepcopy(raw)
    section = value.get('delegation')
    if 'delegation' in value and not isinstance(section, dict):
        raise ValueError('invalid delegation container')
    if isinstance(section, dict):
        section.pop('backend', None)
        if not section and not delegation_present:
            value.pop('delegation', None)
    return _digest(value)


def _initial_intent(raw):
    """Only native selection of this package is an allowed install-phase delta."""
    from .service import _digest
    value = copy.deepcopy(raw)
    section = value.get('plugins')
    if section is not None and not isinstance(section, dict):
        raise ValueError('invalid plugin selection')
    if isinstance(section, dict):
        for key in ('enabled', 'disabled'):
            if key in section:
                if not isinstance(section[key], list) or any(not isinstance(x, str) for x in section[key]):
                    raise ValueError('invalid plugin selection')
                # Native enable treats selection lists as sets and canonicalizes
                # their order. Bind every other member, not incidental ordering.
                section[key] = sorted(set(x for x in section[key] if x != 'model-router'))
                if not section[key]:
                    section.pop(key)
        if not section:
            value.pop('plugins', None)
    return _digest(value)


def _initial_package_code(service, profile):
    """Compare the complete bounded executable/declaration surface; never import it."""
    root = service._profile_home(profile) / 'plugins/model-router'
    from . import installation
    excluded = {'.git', '.github', 'tests', 'docs', '__pycache__', '.pytest_cache', '.venv', 'node_modules'}
    executable = {'.py', '.pyi', '.pyw', '.pyc', '.pyo', '.pyd', '.js', '.mjs', '.cjs', '.sh', '.ps1', '.bat', '.cmd', '.vbs', '.lua', '.rb', '.dll', '.dylib', '.so', '.exe', '.wasm'}
    executable.update(Path(suffix).suffix.lower() for suffix in (*SOURCE_SUFFIXES, *BYTECODE_SUFFIXES, *EXTENSION_SUFFIXES))
    declarations = {'.json', '.yaml', '.yml', '.toml', '.md', '.css', '.html', '.txt'}
    owned = {'model_router', 'lib', 'dashboard', 'desktop', 'skills', 'compat', 'scripts'}
    required = {'__init__.py', 'cli.py', 'plugin.yaml', 'pyproject.toml', 'model_router/native_delegation.py', 'model_router/native_service.py'}
    def failed_walk(error):
        raise error
    def names():
        found = []
        inspected = 0
        for folder, dirs, files in os.walk(root, followlinks=False, onerror=failed_walk):
            if not _safe_path(Path(folder)):
                raise ValueError('unsafe package directory')
            dirs[:] = sorted(d for d in dirs if d not in excluded)
            for directory in dirs:
                if not _safe_path(Path(folder) / directory):
                    raise ValueError('unsafe package directory')
            inspected += len(dirs) + len(files)
            if inspected > 4096:
                raise ValueError('package inventory too large')
            for filename in sorted(files):
                path = Path(folder) / filename
                relative = path.relative_to(root)
                if (path.suffix.lower() in executable or relative.as_posix() in required or
                        relative.parts[0] in owned and path.suffix.lower() in declarations):
                    found.append(relative.as_posix())
                    if len(found) > 512:
                        raise ValueError('package code inventory too large')
        return sorted(found)
    try:
        if not _safe_path(root) or not root.is_dir():
            return None
        initial = names()
        if not required.issubset(initial):
            return None
        observations = {}; total = 0
        for name in initial:
            item = installation._file(root / name, base=root, limit=1024 * 1024)
            if not item.present or item.error or item.data is None:
                return None
            total += len(item.data)
            if total > 8 * 1024 * 1024:
                return None
            observations[name] = item
        if names() != initial:
            return None
        for name, before in observations.items():
            after = installation._file(root / name, base=root, limit=1024 * 1024)
            if after.error or after.signature != before.signature:
                return None
        payload = [(name, hashlib.sha256(item.data).hexdigest()) for name, item in observations.items()]
        return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()
    except (OSError, ValueError):
        return None


def _initial_native_enable_preserves_tools(raw):
    """Do not let native enable widen an explicitly restricted platform tool list."""
    from hermes_cli.toolset_validation import parse_platform_toolsets_value
    table = raw.get('platform_toolsets')
    if table is None:
        return True
    if not isinstance(table, dict):
        return False
    return all((parsed := parse_platform_toolsets_value(value)) is None or 'model_router' in parsed for value in table.values())


def _initial_install_revision(service, profile):
    from . import installation
    path = service._profile_home(profile) / 'plugins/.install-metadata.json'
    try:
        if not _safe_path(path) or not path.is_file() or path.stat().st_size > 256 * 1024:
            return None
        record = installation._trusted_metadata(path.read_bytes())
        return record['revision'] if record else None
    except OSError:
        return None


def _initial_observation(service, profile, readiness=None):
    from . import installation
    from .native_delegation import _inventory
    from .service import _digest, ROUTING_SKILL_IDS, _route
    names = inventory(service)
    service._require_profile(profile, names)
    if not _inventory(service, profile):
        raise ValueError('initial setup profile authority changed')
    stored = service._load_store()
    ready = readiness if readiness is not None else installation.profile_readiness(service, profile, stored)
    if not isinstance(ready, dict) or type(ready.get('explicit_opt_out')) is not bool or type(ready.get('managed_selection')) is not bool:
        raise ValueError('initial setup opt-out state unavailable')
    if not isinstance(ready.get('identity'), str) or not _HEX.fullmatch(ready['identity']):
        raise ValueError('initial setup readiness identity unavailable')
    raw, snapshot, config_digest = _initial_raw(service, profile)
    source_ready = installation.profile_readiness(service, service.active_profile(), stored)
    source_code = service._native_delegation_code_signature(service.active_profile())
    code = service._native_delegation_code_signature(profile)
    source_auto_code = _auto_code_signature(service, service.active_profile(), source_code)
    auto_code = _auto_code_signature(service, profile, code)
    source_revision = _initial_install_revision(service, service.active_profile())
    installed_revision = _initial_install_revision(service, profile)
    base = installation._root_identity(service.root)
    plugins = raw.get('plugins', {})
    skills = raw.get('skills', {})
    if not isinstance(plugins, dict) or not isinstance(skills, dict):
        raise ValueError('initial setup selection unavailable')
    disabled = plugins.get('disabled', [])
    skill_disabled = skills.get('disabled', [])
    if not isinstance(disabled, list) or not isinstance(skill_disabled, list):
        raise ValueError('initial setup opt-out state unavailable')
    action, reason = 'manual', 'configuration_unavailable'
    source_package_code = _initial_package_code(service, service.active_profile())
    package_code = source_package_code if profile == service.active_profile() else _initial_package_code(service, profile)
    present = snapshot.raw_present(ns.KEY_BACKEND)
    backend = snapshot.raw(ns.KEY_BACKEND)
    entry = stored.get('profiles', {}).get(profile) if stored else None
    opted_out = ready['explicit_opt_out'] or 'model-router' in disabled or bool(ROUTING_SKILL_IDS.intersection(skill_disabled)) or (entry is not None and entry['routing']['enabled'] is False)
    if opted_out:
        action, reason = 'preserved', 'explicit_off'
    elif ready['managed_selection']:
        action, reason = 'manual', 'managed_selection'
    elif present and backend not in ('model-router', INITIAL_SETUP_BACKEND):
        action, reason = 'preserved', 'saved_backend' if isinstance(backend, str) and backend else 'explicit_backend_requires_review'
    elif ready.get('state') == 'ready' and backend in ('model-router', INITIAL_SETUP_BACKEND) and code is not None:
        if backend == INITIAL_SETUP_BACKEND and auto_code is None:
            raise ValueError('selected automatic routing is unavailable')
        routes = service.native_route_config(profile)
        if routes.get('enabled') is not True:
            raise ValueError('initial setup routing unavailable')
        _route(routes['heavy']); _route(routes['light'])
        action, reason = 'complete', 'already_selected'
    else:
        # Keep the normal settings DTO readable after setup; an opaque owned
        # model-only block needs manual review, not a successful but unreadable setup.
        if snapshot.raw_present(ns.KEY_POLICY):
            ns.validate_policy_block(profile, snapshot.raw(ns.KEY_POLICY))
        policy = snapshot.raw(ns.KEY_AUTO_POLICY)
        if snapshot.raw_present(ns.KEY_AUTO_POLICY):
            parsed = ns.validate_policy_block(profile, policy, backend=INITIAL_SETUP_BACKEND)
            if any(parsed[role]['mode'] != 'off' for role in ns.ROLES):
                raise ValueError('initial setup does not activate existing continuation')
        if snapshot.raw_present(ns.KEY_PROFILES):
            profiles = ns.validate_profiles_block(snapshot.raw(ns.KEY_PROFILES), names)
            if profiles['profiles'] or profiles['default'] is not None:
                raise ValueError('initial setup does not activate dormant profile authority')
        if source_package_code is None or source_code is None:
            action, reason = 'manual', 'source_package_unavailable'
        elif source_auto_code is None:
            action, reason = 'manual', 'source_automatic_routing_unavailable'
        elif ready.get('state') == 'missing':
            action, reason = ('install', 'package_missing') if source_revision else ('manual', 'installed_source_unverified')
        elif ready.get('version') != source_ready.get('version') or not source_ready.get('version'):
            action, reason = 'manual', 'different_package_version'
        elif not source_revision or installed_revision != source_revision:
            action, reason = 'manual', 'different_package_source'
        elif package_code is None or source_package_code is None or package_code != source_package_code:
            action, reason = 'manual', 'different_package_code'
        elif ready.get('state') == 'disabled' and ready.get('files') == 'complete' and ready.get('base_supported') is True and ready.get('split_supported') is True:
            action, reason = 'enable', 'package_not_enabled'
        elif ready.get('state') == 'ready' and auto_code is None:
            action, reason = 'manual', 'automatic_routing_unavailable'
        elif ready.get('state') == 'ready' and code is not None and code == source_code:
            routes = service.native_route_config(profile)
            if routes.get('enabled') is not True:
                raise ValueError('initial setup routing unavailable')
            _route(routes['heavy']); _route(routes['light'])
            action, reason = 'select_backend', 'backend_unset'
    if action in ('install', 'enable') and not _initial_native_enable_preserves_tools(raw):
        action, reason = 'manual', 'native_enable_changes_tool_selection'
    intent = _digest({'profile': profile, 'base': base, 'intent': _initial_intent(raw), 'store': _digest(stored), 'provenance': snapshot.provenance_digest})
    digest = _digest({'intent': intent, 'config': config_digest, 'cas': snapshot.cas_digest, 'readiness': ready, 'code': code, 'source_code': source_code, 'auto_code': auto_code, 'source_auto_code': source_auto_code, 'default_backend': INITIAL_SETUP_BACKEND, 'package_code': package_code, 'source_package_code': source_package_code, 'source_revision': source_revision, 'installed_revision': installed_revision, 'action': action})
    dto = {'schema': INITIAL_SETUP_SCHEMA, 'action': action, 'eligible': action in ('install', 'enable', 'select_backend'),
           'default_backend': INITIAL_SETUP_BACKEND, 'backend_unset': not present, 'digest': digest, 'intent_digest': intent, 'reason_codes': [reason]}
    return {'dto': dto, 'snapshot': snapshot, 'raw': raw, 'config_digest': config_digest, 'base': base,
            'store_digest': _digest(stored), 'code': code, 'source_code': source_code, 'auto_code': auto_code, 'source_auto_code': source_auto_code, 'package_code': package_code, 'source_package_code': source_package_code, 'source_revision': source_revision, 'installed_revision': installed_revision, 'delegation_present': 'delegation' in raw,
            'preserve': _initial_preservation(raw, 'delegation' in raw)}


def initial_setup_status(service, profile, readiness=None):
    try:
        return _initial_observation(service, profile, readiness)['dto']
    except Exception:
        return {'schema': INITIAL_SETUP_SCHEMA, 'action': 'manual', 'eligible': False, 'backend_unset': False,
                'default_backend': INITIAL_SETUP_BACKEND, 'digest': '', 'intent_digest': '', 'reason_codes': ['configuration_unavailable']}


def initial_setup_preview(service, body):
    from .service import _digest, _json_bytes, _atomic_write, _FileLock, RevisionConflict
    from . import installation
    if not isinstance(body, dict) or set(body) != {'expected_revision', 'expected_root_identity', 'updates'}:
        raise ValueError('invalid initial setup request')
    if type(body['expected_revision']) is not int or body['expected_revision'] < 0 or not isinstance(body['expected_root_identity'], str) or not _HEX.fullmatch(body['expected_root_identity']):
        raise ValueError('invalid initial setup baseline')
    updates = body['updates']
    if not isinstance(updates, list) or not 1 <= len(updates) <= 32:
        raise ValueError('initial setup requires one to 32 profiles')
    with _FileLock(service._lock_path):
        stored = service._load_store(); revision = stored['revision'] if stored else 0
        if revision != body['expected_revision'] or installation._root_identity(service.root) != body['expected_root_identity']:
            raise RevisionConflict('initial setup baseline changed')
        seen, records = set(), []
        for update in updates:
            if not isinstance(update, dict) or set(update) != {'profile', 'expected_digest'}:
                raise ValueError('invalid initial setup target')
            name = service._require_profile(update['profile'], inventory(service))
            if name in seen:
                raise ValueError('duplicate initial setup target')
            seen.add(name)
            observed = _initial_observation(service, name)
            if observed['dto']['action'] != 'select_backend' or observed['dto']['backend_unset'] is not True:
                raise ValueError('initial setup preserves existing choices')
            if not isinstance(update['expected_digest'], str) or not _HEX.fullmatch(update['expected_digest']) or observed['dto']['digest'] != update['expected_digest']:
                raise RevisionConflict('initial setup target changed')
            records.append({'profile': name, 'digest': observed['dto']['digest'], 'preserve': observed['preserve'],
                            'auto_code': observed['auto_code'], 'source_auto_code': observed['source_auto_code'],
                            'provenance': observed['snapshot'].provenance_digest, 'code': observed['code'], 'source_code': observed['source_code'], 'package_code': observed['package_code'], 'source_package_code': observed['source_package_code'], 'source_revision': observed['source_revision'], 'installed_revision': observed['installed_revision'],
                            'delegation_present': observed['delegation_present']})
        plan_id = uuid.uuid4().hex
        changes = [{'profile': row['profile'], 'field': ns.KEY_BACKEND, 'before': None, 'after': INITIAL_SETUP_BACKEND} for row in records]
        plan = {'kind': 'initial_setup', 'default_backend': INITIAL_SETUP_BACKEND, 'owner_profile': service.active_profile(), 'revision': revision,
                'settings_digest': _digest(stored), 'base': body['expected_root_identity'], 'records': records,
                'changes': changes, 'expires_epoch': time.time() + 300}
        folder = service.store_path.parent / 'plans'
        if not _safe_path(folder):
            raise ValueError('unsafe initial setup plan directory')
        _atomic_write(folder / (plan_id + '.json'), _json_bytes(plan))
        return {'plan_id': plan_id, 'default_backend': INITIAL_SETUP_BACKEND, 'changes': changes, 'warnings': ['New conversations let the agent choose model or allowed profile routes; existing sessions are unchanged.'], 'expires_at': plan['expires_epoch']}


def initial_setup_apply_consumed(service, plan, plan_id):
    from .service import _digest, _now, RevisionConflict
    from . import installation
    if plan.get('default_backend') != INITIAL_SETUP_BACKEND:
        raise RevisionConflict('initial setup default changed; create a new plan')
    if installation._root_identity(service.root) != plan['base'] or _digest(service._load_store()) != plan['settings_digest']:
        raise RevisionConflict('initial setup baseline changed')
    for record in plan['records']:
        observed = _initial_observation(service, record['profile'])
        if observed['dto']['action'] != 'select_backend' or observed['dto']['digest'] != record['digest']:
            raise RevisionConflict('initial setup target changed')
    applied = []
    pending = [{'profile': row['profile'], 'key': ns.KEY_BACKEND} for row in plan['records']]
    def verified(record):
        current = _initial_observation(service, record['profile'])
        if (current['dto']['action'] != 'complete' or current['snapshot'].raw(ns.KEY_BACKEND) != INITIAL_SETUP_BACKEND or
                current['snapshot'].effective(ns.KEY_BACKEND) != INITIAL_SETUP_BACKEND or current['code'] != record['code'] or current['source_code'] != record['source_code'] or
                current['auto_code'] != record['auto_code'] or current['source_auto_code'] != record['source_auto_code'] or
                current['source_revision'] != record['source_revision'] or current['installed_revision'] != record['installed_revision'] or
                current['package_code'] != record['package_code'] or current['source_package_code'] != record['source_package_code'] or
                current['snapshot'].provenance_digest != record['provenance'] or
                _initial_preservation(current['raw'], record['delegation_present']) != record['preserve']):
            raise RevisionConflict('initial setup exact readback failed')
    try:
        for record in plan['records']:
            if installation._root_identity(service.root) != plan['base'] or _digest(service._load_store()) != plan['settings_digest']:
                raise RevisionConflict('initial setup baseline changed')
            current = _initial_observation(service, record['profile'])
            if current['dto']['action'] != 'select_backend' or current['dto']['digest'] != record['digest']:
                raise RevisionConflict('initial setup changed during apply')
            service._write_key(record['profile'], ns.KEY_BACKEND, INITIAL_SETUP_BACKEND)
            verified(record)
            applied.append(pending.pop(0))
        for record in plan['records']:
            verified(record)
        if installation._root_identity(service.root) != plan['base'] or _digest(service._load_store()) != plan['settings_digest']:
            raise RevisionConflict('initial setup final baseline changed')
    except Exception:
        receipt = {'status': 'partial', 'plan_id': plan_id, 'revision': plan['revision'], 'applied': applied, 'remaining': pending, 'finished_at': _now()}
        service._store_apply(receipt)
        return receipt
    receipt = {'status': 'applied', 'plan_id': plan_id, 'revision': plan['revision'], 'applied': applied, 'remaining': [], 'finished_at': _now()}
    service._store_apply(receipt)
    return receipt
