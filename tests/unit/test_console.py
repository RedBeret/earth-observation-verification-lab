"""Console writing has to survive a narrow console code page.

Newman and k6 both decorate their output with box drawing and arrow characters. A Windows
console using cp1252 cannot encode them, and printing them raised `UnicodeEncodeError`
after the underlying gate had already done its work and written its reports. These pin the
substituting writer that every subprocess echo path now uses.
"""

from __future__ import annotations

from io import BytesIO, TextIOWrapper

import pytest

from terractl.console import write_console

pytestmark = pytest.mark.unit

# The exact characters that took down the contract gate: U+274F from the Newman banner and
# U+21B3 from its request tree.
NEWMAN_GLYPHS = "❏ Operational surface\n↳ Ingest API\n"


def _cp1252_stream() -> tuple[BytesIO, TextIOWrapper]:
    buffer = BytesIO()
    return buffer, TextIOWrapper(buffer, encoding="cp1252", newline="")


def test_characters_outside_the_code_page_do_not_raise() -> None:
    buffer, stream = _cp1252_stream()
    write_console(NEWMAN_GLYPHS, stream)
    stream.flush()
    decoded = buffer.getvalue().decode("cp1252")
    assert "Operational surface" in decoded
    assert "Ingest API" in decoded


def test_only_the_unencodable_characters_are_replaced() -> None:
    buffer, stream = _cp1252_stream()
    write_console("built ✓ ok\n", stream)
    stream.flush()
    assert buffer.getvalue().decode("cp1252") == "built ? ok\n"


def test_text_the_code_page_supports_is_untouched() -> None:
    buffer, stream = _cp1252_stream()
    write_console("plain ascii only\n", stream)
    stream.flush()
    assert buffer.getvalue().decode("cp1252") == "plain ascii only\n"


def test_a_stream_without_an_encoding_falls_back_to_utf8() -> None:
    class NoEncoding:
        encoding = None

        def __init__(self) -> None:
            self.written = ""

        def write(self, value: str) -> int:
            self.written += value
            return len(value)

    target = NoEncoding()
    write_console(NEWMAN_GLYPHS, target)  # type: ignore[arg-type]
    assert "❏" in target.written
