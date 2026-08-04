"""Return the checkout to the state a fresh clone would be in.

`down` removes the containers, volumes, and networks the project created and deliberately
leaves everything else alone, so a second run reuses the built image and the evidence from
the last run is still there to read. Reset is the other half. It removes what `down` keeps,
so the next run starts from nothing and proves it can.

Nothing here reaches outside the project. The image is matched by the exact repository name
the compose file builds and the tag the generated configuration names, the artifacts are
the ones under the project artifact root, and the generated configuration is the single
file the tooling writes. Anything the operator did not generate by running this project is
not this command's business.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from terractl.environment import artifacts_root, ensure_artifact_directories, project_root

GENERATED_CONFIG = ".env.local"
IMAGE_REPOSITORY = "terrawatch-lab"
KEEP_FILENAME = ".gitkeep"


def project_image() -> str:
    """The exact image reference this checkout builds."""
    tag = "local"
    config = project_root() / GENERATED_CONFIG
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            if line.startswith("IMAGE_TAG="):
                tag = line.split("=", 1)[1].strip() or tag
    return f"{IMAGE_REPOSITORY}:{tag}"


def image_id(reference: str) -> str | None:
    """Resolve an image reference to its id, or None when it is not present.

    This asks the image list to filter rather than asking `docker image inspect` to resolve
    the name. On Docker 29 a locally built image can be listed as `terrawatch-lab:local`
    and carry exactly that string in its `RepoTags`, while `docker image inspect` on the
    same string answers "No such image" and only the fully qualified
    `docker.io/library/terrawatch-lab:local` resolves. The filter agrees with what the
    operator sees in `docker images`, so it is the one to trust.
    """
    process = subprocess.run(
        ["docker", "images", "--quiet", "--filter", f"reference={reference}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    if process.returncode:
        return None
    identifier = process.stdout.strip().splitlines()
    return identifier[0].strip() if identifier else None


def removable_artifacts() -> list[Path]:
    """Every generated artifact, never the placeholders that define the directory tree."""
    root = artifacts_root()
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.name != KEEP_FILENAME)


def reset_plan() -> dict[str, Any]:
    config = project_root() / GENERATED_CONFIG
    image = project_image()
    return {
        "image": image if image_id(image) else None,
        "artifact_files": len(removable_artifacts()),
        "generated_config": config.name if config.is_file() else None,
    }


def reset_project() -> dict[str, Any]:
    """Remove what a teardown leaves behind. Assumes the caller already tore down."""
    removed: dict[str, Any] = {"image": None, "artifact_files": 0, "generated_config": None}

    image = project_image()
    identifier = image_id(image)
    if identifier:
        # Remove by id. The reference that the image list agrees exists is not always a
        # reference that `docker image rm` can resolve, for the same reason as above.
        process = subprocess.run(
            ["docker", "image", "rm", identifier],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or f"unable to remove image {image}")
        removed["image"] = image

    root = artifacts_root()
    if root.is_dir():
        removed["artifact_files"] = len(removable_artifacts())
        for entry in sorted(root.iterdir()):
            if entry.is_dir():
                # Keep the directory and its placeholder so the tree survives a reset.
                for child in sorted(entry.iterdir()):
                    if child.name == KEEP_FILENAME:
                        continue
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
            elif entry.name != KEEP_FILENAME:
                entry.unlink()
    ensure_artifact_directories()

    config = project_root() / GENERATED_CONFIG
    if config.is_file():
        config.unlink()
        removed["generated_config"] = config.name

    return removed
