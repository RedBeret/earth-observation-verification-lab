import pytest

from terractl.documentation import (
    broken_links,
    documentation_files,
    known_commands,
    missing_paths,
    referenced_commands,
    unknown_commands,
)
from terractl.environment import project_root

pytestmark = pytest.mark.unit

DOCUMENTS = documentation_files()
IDENTIFIERS = [path.relative_to(project_root()).as_posix() for path in DOCUMENTS]


def test_the_expected_documents_exist() -> None:
    assert {"README.md", "SECURITY.md", "PROJECT_BOUNDARY.md"} <= set(IDENTIFIERS)
    assert {
        "docs/ARCHITECTURE.md",
        "docs/OPERATIONS.md",
        "docs/TEST_PLAN.md",
        "docs/TROUBLESHOOTING.md",
        "docs/INTERFACE_CONTROL.md",
    } <= set(IDENTIFIERS)


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDENTIFIERS)
def test_documented_commands_exist(path) -> None:
    assert unknown_commands(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDENTIFIERS)
def test_documented_paths_exist(path) -> None:
    assert missing_paths(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDENTIFIERS)
def test_relative_links_resolve(path) -> None:
    assert broken_links(path) == []


def test_the_command_checker_catches_an_invented_command() -> None:
    assert unknown_commands("Run `./scripts/terra.sh deploy` to ship.") == [
        "./scripts/terra.sh deploy"
    ]


def test_the_path_checker_catches_an_invented_path() -> None:
    assert missing_paths("See `docs/NOT_A_FILE.md` for details.") == ["docs/NOT_A_FILE.md"]


def test_subcommands_are_recognized() -> None:
    commands = known_commands()
    assert "./scripts/terra.sh test unit" in commands
    assert "./scripts/terra.sh procedure run" in commands
    assert "./scripts/terra.sh fault inject" in commands


def test_placeholders_are_not_treated_as_commands() -> None:
    assert referenced_commands("`./scripts/terra.sh <command>`") == set()


def test_routes_and_bare_filenames_are_not_treated_as_repository_paths() -> None:
    assert missing_paths("Fetch `/openapi.json` and create `private-terms.txt`.") == []
