from __future__ import annotations

import json
import os

import pytest

from guy4ase.gui.application import atomic_io


def test_atomic_write_json_replaces_complete_document(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"old": true}', encoding="utf-8")

    atomic_io.atomic_write_json(path, {"new": [1, 2, 3]})

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": [1, 2, 3]}
    assert not tuple(tmp_path.glob(".state.json.*.tmp"))


def test_atomic_write_keeps_previous_file_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    original = '{"old": true}'
    path.write_text(original, encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(atomic_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_io.atomic_write_json(path, {"new": True})

    assert path.read_text(encoding="utf-8") == original
    assert not tuple(tmp_path.glob(".state.json.*.tmp"))


def test_atomic_write_keeps_previous_file_when_flush_fails(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    original = '{"old": true}'
    path.write_text(original, encoding="utf-8")

    def fail_fsync(_fd):
        raise OSError("flush failed")

    monkeypatch.setattr(atomic_io.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="flush failed"):
        atomic_io.atomic_write_json(path, {"new": True})

    assert path.read_text(encoding="utf-8") == original
    assert not tuple(tmp_path.glob(".state.json.*.tmp"))


def test_atomic_write_fsyncs_file_and_parent_directory(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(atomic_io.os, "fsync", lambda fd: calls.append(fd))

    target = tmp_path / "state.json"
    atomic_io.atomic_write_text(target, "value")

    assert target.read_text(encoding="utf-8") == "value"
    expected = 1 if os.name == "nt" else 2
    assert len(calls) == expected
