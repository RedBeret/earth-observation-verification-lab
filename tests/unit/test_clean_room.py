import json
from pathlib import Path

import pytest

from terractl.clean_room import (
    ContainerSnapshot,
    clean_room_proof,
)

pytestmark = pytest.mark.unit


def _project_container() -> ContainerSnapshot:
    return ContainerSnapshot(
        identifier="project-id",
        name="project-container",
        status="running",
        labels={
            "org.northstar.project": "earth-observation-verification-lab",
            "com.docker.compose.project": "project-one",
        },
    )


def _sentinel() -> ContainerSnapshot:
    return ContainerSnapshot(
        identifier="sentinel-id",
        name="verification-sentinel",
        status="running",
        labels={
            "org.northstar.project": "earth-observation-verification-sentinel",
            "org.northstar.verification-sentinel": "sentinel-token",
        },
    )


def test_clean_room_refuses_without_unrelated_neighbor(monkeypatch) -> None:
    monkeypatch.setattr("terractl.clean_room.assert_environment_green", lambda: None)
    monkeypatch.setattr("terractl.clean_room.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.clean_room.survey_containers", lambda: [_project_container()])
    monkeypatch.setattr("terractl.clean_room.collect_failure_diagnostics", lambda context: None)
    monkeypatch.setattr(
        "terractl.clean_room.compose_down",
        lambda: pytest.fail("teardown must not run"),
    )

    with pytest.raises(RuntimeError, match="refuses teardown"):
        clean_room_proof()


def test_sentinel_survives_project_teardown_and_is_removed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = _project_container()
    sentinel = _sentinel()
    surveys = iter(
        [
            [project],
            [project, sentinel],
            [sentinel],
        ]
    )
    removed: list[str] = []
    monkeypatch.setattr("terractl.clean_room.assert_environment_green", lambda: None)
    monkeypatch.setattr("terractl.clean_room.compose_project", lambda: "project-one")
    monkeypatch.setattr("terractl.clean_room.survey_containers", lambda: next(surveys))
    monkeypatch.setattr("terractl.clean_room.create_sentinel", lambda: sentinel)
    monkeypatch.setattr("terractl.clean_room.compose_down", lambda: 0)
    monkeypatch.setattr(
        "terractl.clean_room.remove_sentinel",
        lambda snapshot: removed.append(snapshot.identifier),
    )
    monkeypatch.setattr("terractl.clean_room.artifacts_root", lambda: tmp_path)

    evidence_path = clean_room_proof(create_verification_sentinel=True)

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["result"] == "passed"
    assert evidence["project_containers_after"] == 0
    assert evidence["neighbor_fingerprints_unchanged"] is True
    assert evidence["sentinel_removed"] is True
    assert removed == ["sentinel-id"]
