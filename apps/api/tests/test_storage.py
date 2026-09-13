from pathlib import Path

import pytest

from rag.storage import LocalStorage


def test_local_storage_round_trip(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    storage.put("tenant/document/version/file.txt", b"knowledge")
    assert storage.read("tenant/document/version/file.txt") == b"knowledge"
    storage.delete("tenant/document/version/file.txt")
    assert not (tmp_path / "tenant/document/version/file.txt").exists()


@pytest.mark.parametrize("key", ["../secret", "/absolute", "tenant/../../secret"])
def test_local_storage_rejects_path_escape(tmp_path: Path, key: str):
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError, match="Invalid storage key"):
        storage.put(key, b"bad")
