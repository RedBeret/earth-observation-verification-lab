import hashlib
import io

import pytest

from terrawatch.hashing import sha256_file, sha256_stream

pytestmark = pytest.mark.unit


def test_sha256_stream() -> None:
    content = b"synthetic-earth-observation"
    assert sha256_stream(io.BytesIO(content)) == hashlib.sha256(content).hexdigest()


def test_sha256_file(tmp_path) -> None:
    path = tmp_path / "fixture.bin"
    path.write_bytes(b"fixed")
    assert sha256_file(path) == hashlib.sha256(b"fixed").hexdigest()
