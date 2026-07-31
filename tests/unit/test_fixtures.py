from hashlib import sha256
from pathlib import Path

import pytest

from data.generators.generate_expected_results import generate

pytestmark = pytest.mark.unit


def _manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_fixture_generation_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate(first)
    generate(second)
    assert _manifest(first) == _manifest(second)


def test_fixture_set_contains_required_negative_cases(tmp_path: Path) -> None:
    generate(tmp_path)
    assert (tmp_path / "valid" / "scene-wgs84.tif").is_file()
    assert (tmp_path / "valid" / "scene-projected.tif").is_file()
    assert (tmp_path / "invalid" / "no-crs.tif").is_file()
    assert (tmp_path / "invalid" / "truncated-raster.tif").is_file()
    assert (tmp_path / "invalid" / "invalid-metadata.json").is_file()
    assert (tmp_path / "expected" / "stac-scene-syn-0001.json").is_file()
    assert (tmp_path / "expected" / "correlations.json").is_file()
