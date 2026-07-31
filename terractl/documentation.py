"""Keep the documentation honest about commands and paths that actually exist."""

from __future__ import annotations

import re
from pathlib import Path

import typer.main

from terractl.cli import app
from terractl.environment import project_root

COMMAND_PATTERN = re.compile(r"\./scripts/(?:bootstrap\.sh|terra\.sh(?:[ ]+[a-z][a-z0-9-]*){1,3})")
BACKTICK_PATTERN = re.compile(r"`([^`\n]+)`")
LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
PATH_SUFFIXES = (
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".js",
    ".sh",
    ".ini",
    ".toml",
    ".txt",
    ".tif",
)
PLACEHOLDER_CHARACTERS = ("<", ">", "*", "{", "}", "$")
# Generated output is described by the documentation but is never checked in, so its
# absence says nothing about whether the documentation is correct.
GENERATED_PREFIXES = ("artifacts/", "data/generated/")


# Written text stays in plain ASCII punctuation so diffs, terminals, and legacy consoles
# render it identically everywhere.
# Written as escapes so this module does not trip its own check.
TYPOGRAPHIC_CHARACTERS = (
    "\u2014",  # em dash
    "\u2013",  # en dash
    "\u2018",  # left single quotation mark
    "\u2019",  # right single quotation mark
    "\u201c",  # left double quotation mark
    "\u201d",  # right double quotation mark
)


def typographic_characters(text: str) -> list[str]:
    return sorted({character for character in TYPOGRAPHIC_CHARACTERS if character in text})


def known_commands() -> set[str]:
    """Every command the operator CLI actually exposes, including subgroups."""
    group = typer.main.get_command(app)
    names: set[str] = {"./scripts/bootstrap.sh"}
    commands = getattr(group, "commands", {})
    for name, command in commands.items():
        names.add(f"./scripts/terra.sh {name}")
        for child in getattr(command, "commands", {}):
            names.add(f"./scripts/terra.sh {name} {child}")
    return names


def documentation_files(root: Path | None = None) -> list[Path]:
    repo = root or project_root()
    files = sorted(repo.glob("*.md")) + sorted((repo / "docs").glob("*.md"))
    return [path for path in files if path.is_file()]


def referenced_commands(text: str) -> set[str]:
    found: set[str] = set()
    for match in COMMAND_PATTERN.findall(text):
        parts = match.split()
        if parts[0].endswith("bootstrap.sh"):
            found.add("./scripts/bootstrap.sh")
            continue
        # Keep the command and at most one subcommand; drop arguments such as TP ids.
        trimmed = [part for part in parts[1:] if part.islower()]
        found.add(" ".join(["./scripts/terra.sh", *trimmed[:2]]))
    return found


def referenced_paths(text: str) -> set[str]:
    """Repository-relative paths only.

    A leading slash is an HTTP route or an absolute path, and a bare filename is a
    reference to a concept rather than to a checked-in file. Neither is verifiable here.
    """
    found: set[str] = set()
    for token in BACKTICK_PATTERN.findall(text):
        candidate = token.strip()
        if any(character in candidate for character in PLACEHOLDER_CHARACTERS):
            continue
        if " " in candidate or candidate.startswith("/") or "/" not in candidate:
            continue
        if candidate.endswith("/") or candidate.endswith(PATH_SUFFIXES):
            found.add(candidate.rstrip("/"))
    return found


def unknown_commands(text: str) -> list[str]:
    valid = known_commands()
    return sorted(command for command in referenced_commands(text) if command not in valid)


def missing_paths(text: str, root: Path | None = None) -> list[str]:
    repo = root or project_root()
    return sorted(
        candidate
        for candidate in referenced_paths(text)
        if not candidate.startswith(GENERATED_PREFIXES) and not (repo / candidate).exists()
    )


def broken_links(path: Path, root: Path | None = None) -> list[str]:
    repo = root or project_root()
    text = path.read_text(encoding="utf-8")
    broken: list[str] = []
    for target in LINK_PATTERN.findall(text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists() or repo.resolve() not in resolved.parents:
            broken.append(target)
    return broken
