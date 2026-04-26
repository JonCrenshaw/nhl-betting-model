"""Tests for ``puckbunny.storage.local.LocalFilesystemStorage``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from puckbunny.storage.local import LocalFilesystemStorage

if TYPE_CHECKING:
    from pathlib import Path


def test_put_get_round_trip(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    storage.put_object("a/b/c.txt", b"hello")
    assert storage.get_object("a/b/c.txt") == b"hello"


def test_head_object_reports_size(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    storage.put_object("blob", b"payload-data")
    meta = storage.head_object("blob")
    assert meta.key == "blob"
    assert meta.size_bytes == len(b"payload-data")


def test_list_objects_filters_by_prefix(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    storage.put_object("a/1.parquet", b"1")
    storage.put_object("a/b/2.parquet", b"2")
    storage.put_object("c/3.parquet", b"3")

    keys_under_a = sorted(storage.list_objects("a"))
    assert keys_under_a == ["a/1.parquet", "a/b/2.parquet"]


def test_list_objects_empty_prefix_walks_all(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    storage.put_object("x.txt", b"x")
    storage.put_object("y/z.txt", b"z")
    assert sorted(storage.list_objects("")) == ["x.txt", "y/z.txt"]


def test_delete_object(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    storage.put_object("k", b"v")
    storage.delete_object("k")
    # delete is idempotent; deleting again is a no-op.
    storage.delete_object("k")
    assert list(storage.list_objects("")) == []


def test_overwrite_replaces(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    storage.put_object("k", b"first")
    storage.put_object("k", b"second")
    assert storage.get_object("k") == b"second"


def test_path_traversal_rejected(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.put_object("../escape", b"x")


def test_empty_key_rejected(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.put_object("", b"x")
