from datetime import UTC, datetime

import pytest

from terrawatch.analysis import (
    QueryContractError,
    parse_filters,
    parse_pagination,
)

pytestmark = pytest.mark.unit


def test_combined_filters_parse_as_inclusive_values() -> None:
    bbox, time_range = parse_filters(
        "-120.1,37.1,-119.9,37.3",
        "2026-07-29T18:15:00Z",
        "2026-07-29T18:45:00Z",
    )
    assert bbox == (-120.1, 37.1, -119.9, 37.3)
    assert time_range == (
        datetime(2026, 7, 29, 18, 15, tzinfo=UTC),
        datetime(2026, 7, 29, 18, 45, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("bbox", "start", "end", "code"),
    [
        ("-119,37,-120,38", None, None, "invalid-bbox"),
        ("-120,37,-119", None, None, "invalid-bbox"),
        (None, "2026-07-29T18:30:00Z", None, "invalid-time-range"),
        (
            None,
            "2026-07-29T18:31:00Z",
            "2026-07-29T18:30:00Z",
            "invalid-time-range",
        ),
    ],
)
def test_invalid_filters_have_specific_codes(
    bbox: str | None,
    start: str | None,
    end: str | None,
    code: str,
) -> None:
    with pytest.raises(QueryContractError) as caught:
        parse_filters(bbox, start, end)
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("page", "page_size"),
    [("0", "50"), ("1", "0"), ("1", "101"), ("x", "50")],
)
def test_invalid_pagination_fails(page: str, page_size: str) -> None:
    with pytest.raises(QueryContractError, match="Page"):
        parse_pagination(page, page_size)


def test_valid_pagination() -> None:
    assert parse_pagination("2", "25") == (2, 25)
