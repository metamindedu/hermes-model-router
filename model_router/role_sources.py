"""Bounded local enabled-skill identifiers; never opens skill Markdown bodies."""
from __future__ import annotations
import os
import re
from .role_metadata import digest, read_bounded

_IDENTIFIER = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z')
_SKIP = {'references', 'templates', 'scripts', 'assets', 'archive', 'archives', 'node_modules', '__pycache__'}


def local_skill_names(service, target):
    """Return local names, omission reasons and opaque inventory binding.

    External dirs are intentionally not traversed: they can contain arbitrary
    private material outside the profile's bounded source authority.
    """
    from .installation import _inspect
    from .effective_config import read_key_scoped
    home = service._profile_home(target)
    omitted = []
    try:
        config, config_sig = read_bounded(home / 'config.yaml', service.root, 256 * 1024)
        if config is None:
            raise ValueError('missing_config')
        snapshot = read_key_scoped(home, ('skills.disabled', 'skills.external_dirs'))
        if snapshot.warnings or snapshot.managed_keys or not snapshot.effective_available:
            raise ValueError('unknown_skill_policy')
        disabled = snapshot.effective('skills.disabled') or []
        external = snapshot.effective('skills.external_dirs') or []
        if not isinstance(disabled, list) or any(not isinstance(v, str) for v in disabled):
            raise ValueError('unknown_skill_policy')
        if external:
            omitted.append('external_skills_omitted')
        disabled = {v.casefold() for v in disabled}
        signatures = []
        names = []
        count = 0
        def visit(directory, depth):
            nonlocal count
            info, before = _inspect(directory, 'dir', base=service.root)
            signatures.append(before)
            if info is None:
                return
            # Do not materialize an unbounded directory before checking the budget.
            entries = []
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    count += 1
                    if count > 512:
                        raise ValueError('skill_inventory_budget')
                    entries.append(entry)
            for entry in sorted(entries, key=lambda e: e.name.casefold()):
                path = directory / entry.name
                if entry.name == 'SKILL.md':
                    file_info, sig = _inspect(path, 'file', base=service.root)
                    if file_info is None or file_info.st_nlink != 1:
                        raise ValueError('unsafe_skill_entry')
                    relative = directory.relative_to(home / 'skills')
                    identifier = relative.as_posix()
                    if identifier != '.' and len(identifier) <= 128 and not ({identifier.casefold(), directory.name.casefold()} & disabled):
                        names.append(identifier)
                        signatures.append(sig)
                elif _IDENTIFIER.fullmatch(entry.name) and entry.name.casefold() not in _SKIP:
                    if entry.is_symlink():
                        raise ValueError('unsafe_skill_entry')
                    if entry.is_dir(follow_symlinks=False):
                        if depth >= 3:
                            omitted.append('deep_skills_omitted')
                        else:
                            visit(path, depth + 1)
            _, after = _inspect(directory, 'dir', base=service.root)
            if before != after:
                raise ValueError('skill_inventory_changed')
        visit(home / 'skills', 0)
        after, after_sig = read_bounded(home / 'config.yaml', service.root, 256 * 1024)
        if config != after or config_sig != after_sig:
            raise ValueError('skill_policy_changed')
        names = sorted(set(names), key=str.casefold)
        truncated = len(names) > 32
        selected = names[:32]
        return selected, sorted(set(omitted)), truncated, digest({'inventory': signatures, 'names': names, 'config': snapshot.cas_digest, 'signature': config_sig})
    except Exception:
        return [], ['skills_unavailable'], False, digest({'state': 'unavailable'})
