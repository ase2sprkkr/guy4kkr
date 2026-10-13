"""Content-aware versions of files used by calculation provenance."""
from __future__ import annotations

import hashlib
import stat as stat_module
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_DIGEST_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class FileFingerprint:
    """Cheap filesystem metadata used to avoid unnecessary content hashing."""

    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def capture(cls, path: str | Path) -> "FileFingerprint":
        info = Path(path).stat()
        return cls(
            device=info.st_dev,
            inode=info.st_ino,
            mode=info.st_mode,
            size=info.st_size,
            mtime_ns=info.st_mtime_ns,
            ctime_ns=info.st_ctime_ns,
        )

    @property
    def is_file(self) -> bool:
        return stat_module.S_ISREG(self.mode)


class FileState(Enum):
    """Relationship between a captured file version and its path on disk now."""

    CURRENT = "current"
    OVERWRITTEN = "overwritten"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_DIGEST_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, eq=False)
class FileVersion:
    """A path together with cheap metadata and optional content identity.

    Captured provenance normally includes a SHA-256 digest once. Later checks
    first compare the cheap metadata fingerprint and hash the current file only
    if those metadata changed. ``digest=False`` is available for callers that
    explicitly need only a cheap, non-content-identifying snapshot.
    """

    path: Path
    fingerprint: FileFingerprint | None
    digest: str | None = None

    @classmethod
    def capture(
        cls,
        path: str | Path,
        *,
        digest: bool = True,
    ) -> "FileVersion":
        resolved = Path(path).expanduser().resolve()
        try:
            fingerprint = FileFingerprint.capture(resolved)
        except OSError:
            return cls(path=resolved, fingerprint=None)

        if not digest or not fingerprint.is_file:
            return cls(path=resolved, fingerprint=fingerprint)

        try:
            content_digest = _file_digest(resolved)
            after = FileFingerprint.capture(resolved)
        except OSError:
            return cls(path=resolved, fingerprint=fingerprint)

        # Never bind a digest to metadata from a different version when a file
        # happens to change while it is being hashed.
        if after != fingerprint:
            return cls(path=resolved, fingerprint=after)
        return cls(
            path=resolved,
            fingerprint=fingerprint,
            digest=content_digest,
        )

    @property
    def available(self) -> bool:
        return self.fingerprint is not None and self.fingerprint.is_file

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FileVersion):
            return NotImplemented
        if self.path != other.path:
            return False
        if self.digest is not None or other.digest is not None:
            return (
                self.digest is not None
                and other.digest is not None
                and self.digest == other.digest
            )
        return self.fingerprint == other.fingerprint

    def __hash__(self) -> int:
        if self.digest is not None:
            return hash((self.path, self.digest))
        return hash((self.path, self.fingerprint))

    def current(self) -> "FileVersion":
        """Capture the current version, hashing only after metadata changed."""
        current = type(self).capture(self.path, digest=False)
        if current.fingerprint == self.fingerprint:
            return self
        if not current.available or self.digest is None:
            return current

        current = type(self).capture(self.path, digest=True)
        return self if current == self else current

    def is_current(self) -> bool:
        return self.state() is FileState.CURRENT

    def state(self) -> FileState:
        try:
            fingerprint = FileFingerprint.capture(self.path)
        except FileNotFoundError:
            return FileState.MISSING
        except OSError:
            return FileState.UNAVAILABLE

        if self.fingerprint is not None and fingerprint == self.fingerprint:
            return FileState.CURRENT
        if not fingerprint.is_file:
            return FileState.OVERWRITTEN
        if self.digest is None:
            return FileState.OVERWRITTEN

        try:
            digest = _file_digest(self.path)
        except FileNotFoundError:
            return FileState.MISSING
        except OSError:
            return FileState.UNAVAILABLE
        return FileState.CURRENT if digest == self.digest else FileState.OVERWRITTEN
