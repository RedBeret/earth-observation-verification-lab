"""Structural checks that keep the three CI definitions honest.

They never start a runner. They prove the definitions call the same repository
entrypoints, in the same order, with unconditional diagnostics, artifact collection,
and teardown, and that no gate is allowed to fail quietly.
"""

from __future__ import annotations

import pytest

from terractl.pipelines import (
    ALWAYS_RUN_COMMANDS,
    PIPELINE_FILES,
    REQUIRED_GATES,
    RUNNING_CONTRACT_GATE,
    STATIC_CONTRACT_GATE,
    gate_sequence,
    gates_out_of_order,
    lenient_failure_settings,
    missing_gates,
    pipeline_commands,
    pipeline_path,
    pipeline_text,
    unsafe_secret_references,
)

pytestmark = [pytest.mark.pipeline, pytest.mark.static]

PIPELINES = sorted(PIPELINE_FILES)


@pytest.mark.parametrize("name", PIPELINES)
def test_every_pipeline_definition_exists(name: str) -> None:
    assert pipeline_path(name).is_file()


@pytest.mark.parametrize("name", PIPELINES)
def test_every_required_gate_is_present(name: str) -> None:
    assert missing_gates(pipeline_text(name)) == []


@pytest.mark.parametrize("name", PIPELINES)
def test_gates_run_in_the_documented_order(name: str) -> None:
    assert gates_out_of_order(pipeline_text(name)) == []


@pytest.mark.parametrize("name", PIPELINES)
def test_diagnostics_and_teardown_always_run(name: str) -> None:
    commands = pipeline_commands(pipeline_text(name))
    for command in ALWAYS_RUN_COMMANDS:
        assert command in commands, f"{name} never calls {command}"


@pytest.mark.parametrize("name", PIPELINES)
def test_no_gate_is_allowed_to_fail_quietly(name: str) -> None:
    assert lenient_failure_settings(pipeline_text(name)) == []


@pytest.mark.parametrize("name", PIPELINES)
def test_no_pipeline_needs_a_secret(name: str) -> None:
    assert unsafe_secret_references(pipeline_text(name)) == []


@pytest.mark.parametrize("name", PIPELINES)
def test_the_two_contract_phases_are_documented(name: str) -> None:
    text = pipeline_text(name)
    assert "before the environment exists" in text
    assert "against the started system" in text
    commands = pipeline_commands(text)
    assert commands.index(STATIC_CONTRACT_GATE) < commands.index(RUNNING_CONTRACT_GATE)


@pytest.mark.parametrize("name", PIPELINES)
def test_pipelines_only_call_repository_entrypoints(name: str) -> None:
    for command in pipeline_commands(pipeline_text(name)):
        assert command.startswith("./scripts/terra.sh ") or command == "./scripts/bootstrap.sh"


def test_all_three_definitions_agree_on_the_gate_sequence() -> None:
    sequences = {name: gate_sequence(pipeline_text(name)) for name in PIPELINES}
    reference = sequences[PIPELINES[0]]
    assert reference == list(REQUIRED_GATES)
    for name, sequence in sequences.items():
        assert sequence == reference, f"{name} runs a different gate sequence"


def test_artifact_collection_fails_on_an_empty_result() -> None:
    assert "if-no-files-found: error" in pipeline_text("github")
    assert "allowEmptyArchive: false" in pipeline_text("jenkins")
    assert "when: always" in pipeline_text("gitlab")


def test_the_checkers_detect_a_broken_definition() -> None:
    broken = "run: ./scripts/terra.sh evidence\nrun: ./scripts/terra.sh test unit\n"
    assert "./scripts/terra.sh doctor" in missing_gates(broken)
    assert gates_out_of_order(broken) != []
    assert unsafe_secret_references("run: echo ${{ secrets.DEPLOY_KEY }}") == ["secrets.DEPLOY_KEY"]
    assert lenient_failure_settings("continue-on-error: true") == ["continue-on-error: true"]
