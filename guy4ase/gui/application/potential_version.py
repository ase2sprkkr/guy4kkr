from __future__ import annotations

import stat as stat_module
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PotentialFileVersion:
    """Cheap identity of one concrete version of a potential file."""

    path: Path
    is_file: bool
    mtime_ns: int | None
    ctime_ns: int | None
    size: int | None
    device: int | None
    inode: int | None

    @classmethod
    def capture(cls, path: str | Path) -> "PotentialFileVersion":
        resolved = Path(path).expanduser().absolute()
        try:
            info = resolved.stat()
        except OSError:
            return cls(resolved, False, None, None, None, None, None)
        return cls(
            resolved,
            stat_module.S_ISREG(info.st_mode),
            info.st_mtime_ns,
            info.st_ctime_ns,
            info.st_size,
            info.st_dev,
            info.st_ino,
        )

    @property
    def available(self) -> bool:
        return self.is_file and self.mtime_ns is not None

    def current(self) -> "PotentialFileVersion":
        return type(self).capture(self.path)

    def is_current(self) -> bool:
        current = self.current()
        return current.available and current == self
