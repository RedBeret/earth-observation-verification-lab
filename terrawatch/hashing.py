"""Stable content hashing utilities."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO


def sha256_stream(stream: BinaryIO, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return sha256_stream(handle)
