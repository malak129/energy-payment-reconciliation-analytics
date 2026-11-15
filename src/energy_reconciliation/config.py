"""Validated local TOML settings; loading never creates directories or databases."""

import tomllib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    rules_version: Literal["1"] = "1"
    currency: Literal["EUR"] = "EUR"
    timezone: Literal["Europe/Berlin"] = "Europe/Berlin"
    data_dir: Path = Path("data")
    output_dir: Path = Path("outputs")
    database_path: Path = Path("data/reconciliation.sqlite3")
    seed: int = Field(default=42, strict=True, ge=0)
    start_date: date = date(2026, 1, 1)
    end_date: date = date(2026, 3, 31)
    record_count: int = Field(default=100, strict=True, ge=1, le=1_000_000)
    discrepancy_rate: Decimal = Field(default=Decimal("0.15"), ge=0, le=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("discrepancy_rate", mode="before")
    @classmethod
    def reject_float(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("Use a decimal string for discrepancy_rate")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "Settings":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Timezone data unavailable; install tzdata") from exc
        return self


def load_settings(path: Path | None = None) -> Settings:
    """Resolve paths against the config directory, or cwd when using defaults."""
    base = Path.cwd() if path is None else path.resolve().parent
    if path is None:
        settings = Settings()
    else:
        with path.open("rb") as stream:
            settings = Settings.model_validate(tomllib.load(stream))
    return settings.model_copy(
        update={
            name: (base / getattr(settings, name)).resolve()
            for name in ("data_dir", "output_dir", "database_path")
        }
    )
