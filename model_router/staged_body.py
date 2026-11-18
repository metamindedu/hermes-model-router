"""Request bodies larger than one command line, delivered in pieces.

The Desktop page reaches this plugin through Hermes' ``cli.exec``, which passes the body as one
command-line argument; on Windows a command line is limited to 32,767 characters. A settings save
for many profiles can exceed that, so the page stages the JSON text in numbered pieces (``stage``)
and then sends ``{"staged": {"id", "total", "length"}}`` as the real operation's body. The pieces
carry exactly the text the page would otherwise have sent; nothing here interprets them.

Pieces live under the profile's ``plugin-data/model-router/staged``. Every component of that path
is inspected (no links, junctions or non-directories, inside the profile home) and re-checked
against that first inspection immediately before each write, read or removal there, and pieces are read through a handle checked against the
inspected file. Pieces are deleted when assembled; abandoned pieces and temporary files expire
after ``TTL_SECONDS``. The file cap is a guard against runaway use, not an exact quota.
``length`` counts UTF-16 code units, the unit of the page's JavaScript strings.
"""
from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from pathlib import Path
from typing import Any

STAGE_RELATIVE = Path("plugin-data") / "model-router" / "staged"
CHUNK_LIMIT = 12_000
MAX_CHUNKS = 128
MAX_TOTAL = 512 * 1024
MAX_FILES = 512
TTL_SECONDS = 600
_ID = re.compile(r"[0-9a-f]{32}\Z")
_PART = re.compile(r"([0-9a-f]{32})\.(\d{3})\.part\Z")
_TEMP = re.compile(r"\.[0-9a-f]{32}\.tmp\Z")
STAGED_OPERATIONS = frozenset({"preview", "fallback-preview", "delegation-preview", "initial-setup-preview"})


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


class _Verified:
    """The staging directory and the signature of every path component when it was inspected.
    ``check()`` re-inspects the whole chain and refuses if any component was replaced (a link,
    junction or another directory), immediately before each write, read or removal."""

    def __init__(self, home: Path, path: Path, signature):
        self.home, self.path, self.signature = home, path, signature

    def check(self) -> Path:
        from .installation import _inspect
        info, signature = _inspect(self.path, "dir", base=self.home)
        if info is None or signature != self.signature:
            raise ValueError("stage directory changed")
        return self.path


def _directory(home: Path, create: bool) -> "_Verified | None":
    """The staging directory with every component inspected; None when it does not exist."""
    from .installation import _inspect
    home = Path(home)
    info, _ = _inspect(home, "dir", base=None)
    if info is None:
        raise ValueError("profile home unavailable")
    current = home
    for part in STAGE_RELATIVE.parts:
        current = current / part
        info, _ = _inspect(current, "dir", base=home)
        if info is None:
            if not create:
                return None
            os.mkdir(current)
            info, _ = _inspect(current, "dir", base=home)
            if info is None:
                raise ValueError("stage directory unavailable")
    _, signature = _inspect(current, "dir", base=home)
    return _Verified(home, current, signature)


def _piece(directory: Path, stage_id: str, index: int) -> Path:
    return directory / f"{stage_id}.{index:03d}.part"


def _prune(verified: "_Verified") -> int:
    """Remove expired pieces and temporary files; count what remains."""
    now = time.time()
    count = 0
    for entry in os.scandir(verified.check()):
        if not (_PART.fullmatch(entry.name) or _TEMP.fullmatch(entry.name)):
            continue
        try:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and now - info.st_mtime > TTL_SECONDS:
                verified.check()
                os.unlink(entry.path)
                continue
        except OSError:
            pass
        count += 1
    return count


def stage(home: Path, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or set(body) != {"id", "index", "total", "chunk"}:
        raise ValueError("stage accepts id, index, total and chunk")
    stage_id, index, total, chunk = body["id"], body["index"], body["total"], body["chunk"]
    if not isinstance(stage_id, str) or not _ID.fullmatch(stage_id):
        raise ValueError("invalid stage id")
    if type(total) is not int or not 2 <= total <= MAX_CHUNKS or type(index) is not int or not 0 <= index < total:
        raise ValueError("invalid stage position")
    if not isinstance(chunk, str) or not chunk or len(chunk) > CHUNK_LIMIT:
        raise ValueError("invalid stage chunk")
    verified = _directory(home, create=True)
    if _prune(verified) >= MAX_FILES:
        raise ValueError("too many staged pieces")
    directory = verified.check()
    target = _piece(directory, stage_id, index)
    temporary = directory / f".{uuid.uuid4().hex}.tmp"
    created = False
    try:
        with open(temporary, "x", encoding="utf-8", newline="") as handle:
            created = True
            handle.write(chunk)
        verified.check()
        os.replace(temporary, target)
        created = False
    finally:
        if created:
            try:
                verified.check()
                temporary.unlink()
            except (OSError, ValueError):
                pass
    return {"staged": True, "index": index}


def is_reference(body: Any) -> bool:
    return isinstance(body, dict) and set(body) == {"staged"}


def _read_piece(path: Path, home: Path) -> str:
    from .installation import _inspect
    info, _ = _inspect(path, "file", base=home)
    if info is None:
        raise ValueError("staged body is incomplete")
    if info.st_nlink != 1 or info.st_size > CHUNK_LIMIT * 4:
        raise ValueError("invalid staged piece")
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino, opened.st_size) != (info.st_dev, info.st_ino, info.st_size)):
            raise ValueError("invalid staged piece")
        data = os.read(fd, CHUNK_LIMIT * 4 + 1)
    finally:
        os.close(fd)
    if len(data) != info.st_size:
        raise ValueError("invalid staged piece")
    text = data.decode("utf-8")
    if not text or len(text) > CHUNK_LIMIT:
        raise ValueError("invalid staged piece")
    return text


def assemble(home: Path, body: Any) -> dict[str, Any]:
    """The body the pieces spell, after checking every piece and the total length. The pieces are
    deleted whether or not assembly succeeds, and only inside the verified directory."""
    reference = body.get("staged") if isinstance(body, dict) else None
    if not isinstance(reference, dict) or set(reference) != {"id", "total", "length"}:
        raise ValueError("invalid staged body reference")
    stage_id, total, length = reference["id"], reference["total"], reference["length"]
    if (not isinstance(stage_id, str) or not _ID.fullmatch(stage_id) or type(total) is not int
            or not 2 <= total <= MAX_CHUNKS or type(length) is not int or not 0 < length <= MAX_TOTAL):
        raise ValueError("invalid staged body reference")
    verified = _directory(home, create=False)
    if verified is None:
        raise ValueError("staged body is incomplete")
    _prune(verified)
    directory = verified.check()
    paths = [_piece(directory, stage_id, index) for index in range(total)]
    extra: list[Path] = []
    contained = True
    try:
        pieces = []
        for path in paths:
            verified.check()
            pieces.append(_read_piece(path, Path(home)))
        extra = [directory / entry.name for entry in os.scandir(verified.check())
                 if (match := _PART.fullmatch(entry.name)) and match.group(1) == stage_id and int(match.group(2)) >= total]
        if extra:
            raise ValueError("staged body has extra pieces")
    finally:
        # Removal re-checks the directory chain first; a component swapped after inspection stops
        # the cleanup at once, and the assembly fails.
        for path in (*paths, *extra):
            try:
                verified.check()
            except (OSError, ValueError):
                contained = False
                break
            try:
                path.unlink()
            except OSError:
                pass
    if not contained:
        raise ValueError("stage directory changed")
    text = "".join(pieces)
    if utf16_length(text) != length:
        raise ValueError("staged body length mismatch")
    value = json.loads(text)
    if not isinstance(value, dict) or is_reference(value):
        raise ValueError("body must be an object")
    return value
