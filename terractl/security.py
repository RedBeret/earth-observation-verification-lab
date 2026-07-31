"""Repository security and public-boundary enforcement.

Findings never contain the offending value. They name the file, the line number,
and the rule so that a failure can be investigated without copying a secret into
logs, evidence, or a pull request.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from terractl.environment import artifacts_root, project_root

BINARY_SUFFIXES = frozenset({".tif", ".tiff", ".png", ".jpg", ".jpeg", ".pyc", ".gz", ".zip"})
REQUIRED_DISCLAIMER = (
    "This is an independently developed personal project using only synthetic and "
    "publicly available information."
)
PRIVATE_TERMS_FILE = "private-prohibited-terms.txt"
ALLOWED_EMAIL_DOMAINS = ("users.noreply.github.com", "example.invalid")
ALLOWED_ADDRESS_LITERALS = frozenset({"127.0.0.1", "0.0.0.0", "255.255.255.255"})

SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[opurs]_[A-Za-z0-9_]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "credential-in-url",
        re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^:\s/@]+:(?!\$\{|\$\()([^@\s/]{6,})@"),
    ),
    (
        "assigned-credential",
        re.compile(
            r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\b\s*[:=]\s*"
            r"(?!\$\{|\$\(|\"\$|'\$|<|\[REDACTED\]|\"\"|''|None\b|null\b)"
            r"[\"']?([A-Za-z0-9+/=_-]{12,})"
        ),
    ),
)

# Documented non-secret local defaults. They are always overridden by .env.local and by
# the Compose environment, and they are listed here so the scanner stays strict about
# every other value it sees. See SECURITY.md.
PLACEHOLDER_SECRETS = frozenset({"terrawatch", "local-placeholder", "CHANGE_ME"})

# Files that exist to prove redaction works must declare this pragma, and only files
# under tests/ may declare it.
FIXTURE_PRAGMA = "secret-scan: synthetic-fixture"

CONTROLLED_MARKINGS: tuple[str, ...] = (
    "NOFORN",
    "ORCON",
    "TS//SCI",
    "SECRET//REL",
    "//SI//",
    "CUI//",
    "FOUO",
)

HOST_PATH_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows-user-path", re.compile(r"[A-Za-z]:\\+Users\\+")),
    ("posix-home-path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/")),
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int

    def __str__(self) -> str:
        return f"{self.rule} at {self.path}:{self.line}"


def tracked_files(root: Path | None = None) -> list[Path]:
    repo = root or project_root()
    process = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if process.returncode:
        raise RuntimeError("unable to list tracked files")
    names = [name for name in process.stdout.split("\0") if name]
    return [repo / name for name in names]


def generated_artifacts(root: Path | None = None) -> list[Path]:
    base = (root or project_root()) / "artifacts"
    if not base.is_dir():
        return []
    return [path for path in base.rglob("*") if path.is_file()]


def _readable_lines(path: Path) -> list[str]:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []


def _local_secret_values(root: Path | None = None) -> list[str]:
    """Return generated local credentials so their leakage can be detected."""
    path = (root or project_root()) / ".env.local"
    if not path.is_file():
        return []
    interesting = {
        "POSTGRES_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "NATS_TOKEN",
    }
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in interesting and len(value) >= 8:
            values.append(value)
    return values


def declares_fixture_pragma(lines: list[str], relative: str) -> bool:
    """Honour the synthetic-fixture pragma only for files under tests/."""
    if not relative.startswith("tests/"):
        return False
    return any(FIXTURE_PRAGMA in line for line in lines[:12])


def scan_for_secrets(paths: list[Path], root: Path | None = None) -> list[Finding]:
    repo = root or project_root()
    leaked = _local_secret_values(repo)
    findings: list[Finding] = []
    for path in paths:
        relative = path.relative_to(repo).as_posix()
        if relative == ".env.local" or relative.endswith(PRIVATE_TERMS_FILE):
            continue
        lines = _readable_lines(path)
        exempt = declares_fixture_pragma(lines, relative)
        for number, line in enumerate(lines, start=1):
            if not exempt:
                for rule, pattern in SECRET_RULES:
                    match = pattern.search(line)
                    if match is None:
                        continue
                    captured = match.groups()[0] if match.groups() else None
                    if captured is not None and captured in PLACEHOLDER_SECRETS:
                        continue
                    findings.append(Finding(rule, relative, number))
            if any(value in line for value in leaked):
                findings.append(Finding("generated-local-credential", relative, number))
    return findings


def private_prohibited_terms(root: Path | None = None) -> list[str]:
    """Load the optional ignored term list. Its contents are never published."""
    path = (root or project_root()) / PRIVATE_TERMS_FILE
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def scan_public_boundary(root: Path | None = None) -> list[Finding]:
    repo = root or project_root()
    findings: list[Finding] = []
    private_terms = [term.lower() for term in private_prohibited_terms(repo)]

    readme = (repo / "README.md").read_text(encoding="utf-8")
    if REQUIRED_DISCLAIMER not in " ".join(readme.split()):
        findings.append(Finding("missing-public-disclaimer", "README.md", 1))

    for path in tracked_files(repo):
        relative = path.relative_to(repo).as_posix()
        for number, line in enumerate(_readable_lines(path), start=1):
            for rule, pattern in HOST_PATH_RULES:
                if pattern.search(line):
                    findings.append(Finding(rule, relative, number))
            for marking in CONTROLLED_MARKINGS:
                if marking in line:
                    findings.append(Finding("controlled-marking", relative, number))
            for address in IPV4_PATTERN.findall(line):
                if address not in ALLOWED_ADDRESS_LITERALS:
                    findings.append(Finding("non-loopback-address-literal", relative, number))
            for email in EMAIL_PATTERN.findall(line):
                if not email.lower().endswith(ALLOWED_EMAIL_DOMAINS):
                    findings.append(Finding("external-email-address", relative, number))
            lowered = line.lower()
            if any(term in lowered for term in private_terms):
                findings.append(Finding("private-prohibited-term", relative, number))
    return findings


def inspect_container_security(config: dict[str, object]) -> list[str]:
    """Check the rendered Compose configuration rather than the template text."""
    services = config.get("services", {})
    if not isinstance(services, dict) or not services:
        raise ValueError("rendered Compose configuration declares no services")
    problems: list[str] = []
    for name, service in services.items():
        if not isinstance(service, dict):
            problems.append(f"{name} is not an object")
            continue
        options = service.get("security_opt") or []
        if "no-new-privileges:true" not in options:
            problems.append(f"{name} does not set no-new-privileges")
        for port in service.get("ports") or []:
            if isinstance(port, dict) and port.get("host_ip") != "127.0.0.1":
                problems.append(f"{name} publishes a non-loopback port")
        if service.get("image") == "terrawatch-lab:local" and not service.get("read_only"):
            problems.append(f"{name} runs a writable application root filesystem")
    return problems


def dockerfile_runs_unprivileged(root: Path | None = None) -> bool:
    text = ((root or project_root()) / "Dockerfile").read_text(encoding="utf-8")
    users = re.findall(r"^USER\s+(\S+)", text, flags=re.MULTILINE)
    return bool(users) and users[-1] not in {"root", "0", "0:0"}


def _run(command: list[str], label: str) -> int:
    print(f"--- {label} ---")
    process = subprocess.run(command, cwd=project_root(), check=False)
    if process.returncode:
        print(f"{label} failed with exit code {process.returncode}.")
    return process.returncode


def run_security_gate() -> int:
    """Static analysis, dependency audit, then the repository security tests."""
    steps = [
        (
            [sys.executable, "-m", "bandit", "-q", "-c", "pyproject.toml", "-r", "terractl"],
            "bandit (terractl)",
        ),
        (
            [sys.executable, "-m", "bandit", "-q", "-c", "pyproject.toml", "-r", "terrawatch"],
            "bandit (terrawatch)",
        ),
        (
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--requirement",
                "requirements/runtime.txt",
                "--strict",
                "--progress-spinner",
                "off",
            ],
            "dependency audit",
        ),
    ]
    for command, label in steps:
        code = _run(command, label)
        if code:
            return code
    artifacts_root().mkdir(parents=True, exist_ok=True)
    return _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "security",
            f"--junitxml={artifacts_root() / 'junit' / 'security.xml'}",
        ],
        "repository security tests",
    )
