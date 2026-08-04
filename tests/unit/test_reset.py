"""Reset removes what teardown keeps, and nothing else.

The risk in a command like this is not that it fails, it is that it succeeds too widely.
These pin what it is allowed to touch: the image this checkout builds, the artifacts it
generated, and the configuration it wrote. The directory tree that a fresh clone ships with
has to survive, or the next run cannot write anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from terractl import reset as reset_module
from terractl.reset import project_image, removable_artifacts, reset_plan, reset_project

pytestmark = pytest.mark.unit

ARTIFACT_DIRECTORIES = ("diagnostics", "evidence", "junit", "reports", "state")


def _fake_tree(root: Path) -> Path:
    artifacts = root / "artifacts"
    (artifacts).mkdir()
    (artifacts / ".gitkeep").write_text("", encoding="utf-8")
    for name in ARTIFACT_DIRECTORIES:
        directory = artifacts / name
        directory.mkdir()
        (directory / ".gitkeep").write_text("", encoding="utf-8")
    (artifacts / "evidence" / "20260101T000000Z").mkdir()
    (artifacts / "evidence" / "20260101T000000Z" / "manifest.json").write_text("{}", "utf-8")
    (artifacts / "junit" / "unit.xml").write_text("<testsuite/>", encoding="utf-8")
    (artifacts / "state" / "active-fault.json").write_text("{}", encoding="utf-8")
    return artifacts


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    artifacts = _fake_tree(tmp_path)
    monkeypatch.setattr(reset_module, "project_root", lambda: tmp_path)
    monkeypatch.setattr(reset_module, "artifacts_root", lambda: artifacts)
    monkeypatch.setattr(reset_module, "ensure_artifact_directories", lambda: None)
    monkeypatch.setattr(reset_module, "image_id", lambda reference: None)
    return tmp_path


def test_the_image_tag_defaults_when_no_configuration_exists(project: Path) -> None:
    assert project_image() == "terrawatch-lab:local"


def test_the_image_tag_comes_from_the_generated_configuration(project: Path) -> None:
    (project / ".env.local").write_text("IMAGE_TAG=ci-1234\nOTHER=x\n", encoding="utf-8")
    assert project_image() == "terrawatch-lab:ci-1234"


def test_placeholders_are_never_counted_as_removable(project: Path) -> None:
    names = {path.name for path in removable_artifacts()}
    assert names == {"manifest.json", "unit.xml", "active-fault.json"}
    assert ".gitkeep" not in names


def test_reset_removes_generated_state_and_keeps_the_tree(project: Path) -> None:
    (project / ".env.local").write_text("IMAGE_TAG=local\n", encoding="utf-8")
    removed = reset_project()

    assert removed["artifact_files"] == 3
    assert removed["generated_config"] == ".env.local"
    assert not (project / ".env.local").exists()
    assert removable_artifacts() == []

    artifacts = project / "artifacts"
    assert (artifacts / ".gitkeep").is_file(), "the artifact root placeholder must survive"
    for name in ARTIFACT_DIRECTORIES:
        assert (artifacts / name).is_dir(), f"{name} directory must survive a reset"
        assert (artifacts / name / ".gitkeep").is_file(), f"{name} placeholder must survive"


def test_reset_is_safe_to_run_twice(project: Path) -> None:
    reset_project()
    second = reset_project()
    assert second == {"image": None, "artifact_files": 0, "generated_config": None}


def test_the_plan_reports_without_removing_anything(project: Path) -> None:
    (project / ".env.local").write_text("IMAGE_TAG=local\n", encoding="utf-8")
    plan = reset_plan()
    assert plan == {
        "image": None,
        "artifact_files": 3,
        "generated_config": ".env.local",
    }
    assert (project / ".env.local").is_file()
    assert len(removable_artifacts()) == 3


def test_a_present_image_is_reported_and_removed_by_id(project: Path, monkeypatch) -> None:
    """The id is what gets removed, because a reference the image list agrees exists is not
    always one that `docker image rm` can resolve."""
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **_):
        calls.append(command)
        return Result()

    monkeypatch.setattr(reset_module, "image_id", lambda reference: "deadbeef1234")
    monkeypatch.setattr(reset_module.subprocess, "run", fake_run)

    removed = reset_project()
    assert removed["image"] == "terrawatch-lab:local"
    assert calls == [["docker", "image", "rm", "deadbeef1234"]]


def test_a_failed_image_removal_is_reported_rather_than_ignored(project: Path, monkeypatch) -> None:
    class Result:
        returncode = 1
        stdout = ""
        stderr = "image is being used by a running container"

    monkeypatch.setattr(reset_module, "image_id", lambda reference: "deadbeef1234")
    monkeypatch.setattr(reset_module.subprocess, "run", lambda command, **_: Result())

    with pytest.raises(RuntimeError, match="running container"):
        reset_project()
