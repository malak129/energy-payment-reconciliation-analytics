"""Generation configuration, independent of Phase 1's local environment settings."""

import calendar
from datetime import date, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def month_start(start: date, offset: int) -> date:
    year, month = divmod(start.year * 12 + start.month - 1 + offset, 12)
    return date(year, month + 1, 1)


def month_end(start: date) -> date:
    return start.replace(day=calendar.monthrange(start.year, start.month)[1])


class GenerationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int = Field(default=42, strict=True, ge=0)
    customer_count: int = Field(default=500, strict=True, ge=1, le=10000)
    billing_periods: int = Field(default=12, strict=True, ge=1, le=120)
    start_date: date = date(2025, 1, 1)
    end_date: date | None = None
    evaluation_date: date | None = None
    discrepancy_rate: Decimal = Field(default=Decimal("0.15"), ge=0, le=1)
    output_dir: Path = Path("data/synthetic")

    @field_validator("discrepancy_rate", mode="before")
    @classmethod
    def decimal_rate(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("discrepancy_rate must be a decimal string")
        return value

    @model_validator(mode="after")
    def dates(self) -> "GenerationSettings":
        if not 1900 <= self.start_date.year <= 2100:
            raise ValueError("start_date year must be between 1900 and 2100")
        final_month = month_start(self.start_date, self.billing_periods - 1)
        end = self.end_date or month_end(final_month)
        if end < self.start_date or end.replace(day=1) != final_month:
            raise ValueError("end_date must fall in the final requested billing month")
        evaluation = self.evaluation_date or end + timedelta(days=60)
        if evaluation < self.start_date:
            raise ValueError("evaluation_date must be on or after start_date")
        object.__setattr__(self, "end_date", end)
        object.__setattr__(self, "evaluation_date", evaluation)
        return self

    def semantic_config(self) -> dict:
        result = self.model_dump(mode="json", exclude={"output_dir"})
        with localcontext() as context:
            context.prec = max(32, len(self.discrepancy_rate.as_tuple().digits))
            result["discrepancy_rate"] = format(self.discrepancy_rate.normalize(), "f")
        return {"schema_version": "1", "generator_version": "1", **result}
