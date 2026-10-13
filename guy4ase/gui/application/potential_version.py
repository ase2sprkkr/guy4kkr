from __future__ import annotations

import stat as stat_module
from dataclasses import dataclass
from pathlib import Path

from ase2sprkkr.common.file_fingerprints import file_fingerprint


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
            fingerprint = file_fingerprint(resolved)
        except OSError:
            return cls(resolved, False, None, None, None, None, None)
        return cls(
            resolved,
            stat_module.S_ISREG(fingerprint.mode),
            fingerprint.mtime_ns,
            fingerprint.ctime_ns,
            fingerprint.size,
            fingerprint.device,
            fingerprint.inode,
        )

    @property
    def available(self) -> bool:
        return self.is_file and self.mtime_ns is not None

    def current(self) -> "PotentialFileVersion":
        return type(self).capture(self.path)

    def is_current(self) -> bool:
        current = self.current()
        return current.available and current == self
