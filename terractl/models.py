"""Models for verification, procedures, and evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationRecord(StrictModel):
    requirement_id: str
    procedure_id: str
    check_id: str
    expected: Any
    observed: Any | None = None
    observation_status: Literal["observed", "not observed"] = "observed"
    passed: bool
    duration_ms: int = Field(ge=0)
    evidence_path: str

    @model_validator(mode="after")
    def missing_observation_fails(self) -> VerificationRecord:
        if self.observation_status == "not observed":
            self.observed = None
            self.passed = False
        return self


class VerificationSummary(StrictModel):
    run_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    records: list[VerificationRecord]

    @model_validator(mode="after")
    def at_least_one_check(self) -> VerificationSummary:
        if not self.records:
            raise ValueError("zero executed checks cannot produce a verification summary")
        return self

    @property
    def passed(self) -> int:
        return sum(record.passed for record in self.records)

    @property
    def failed(self) -> int:
        return len(self.records) - self.passed

    @property
    def total(self) -> int:
        return len(self.records)
