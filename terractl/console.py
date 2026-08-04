"""Console output that survives a narrow console encoding.

A Windows console defaults to a code page that cannot represent the box drawing and arrow
characters that Compose, Newman, and k6 all emit. Printing captured output directly raises
`UnicodeEncodeError` and takes down a gate that had already finished its actual work, so
every path that echoes subprocess output goes through here instead of `print`.

The substitution is deliberate. Losing a decorative glyph from a transcript is acceptable;
losing the run is not.
"""

from __future__ import annotations

import sys
from typing import TextIO


def write_console(value: str, stream: TextIO | None = None) -> None:
    """Write text to a stream, replacing anything the stream cannot encode."""
    target = stream or sys.stdout
    encoding = target.encoding or "utf-8"
    safe_value = value.encode(encoding, errors="replace").decode(encoding)
    target.write(safe_value)
