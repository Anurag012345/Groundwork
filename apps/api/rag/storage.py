import os
from pathlib import Path, PurePosixPath
from uuid import uuid4


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        relative = PurePosixPath(key)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Invalid storage key")
        candidate = self.root.joinpath(*relative.parts).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Invalid storage key")
        return candidate

    def put(self, key: str, content: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
