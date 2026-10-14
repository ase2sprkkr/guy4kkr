"""Atomic filesystem writes shared by small persistence stores."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _fsync_directory(directory: Path) -> None:
    """Persist directory-entry changes where the platform exposes that operation."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically and durably replace *path* with completely flushed contents.

    The temporary file lives next to the destination so :func:`os.replace` is
    an atomic same-filesystem operation. The file itself is fsynced before the
    replacement and, on POSIX, the containing directory is fsynced afterwards
    so the rename is durable across a crash. This helper protects file
    integrity only; callers remain responsible for concurrent-writer locking.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
        _fsync_directory(destination.parent)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    indent: int | None = 2,
) -> None:
    """Serialize JSON and atomically replace *path*."""
    atomic_write_text(path, json.dumps(data, indent=indent))
