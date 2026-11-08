"""Central environment configuration. Loading settings performs no network or file writes."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings can be loaded without credentials for contract tests and replay work."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    gemini_api_key: SecretStr | None = None
    gemini_model: str = ""
    data_dir: Path = Field(default=Path(".trialfair"), alias="TRIALFAIR_DATA_DIR")
    mode: Literal["live", "replay"] = Field(default="live", alias="TRIALFAIR_MODE")
    max_interpretation_texts: int = Field(
        default=20, ge=1, le=100, alias="TRIALFAIR_MAX_INTERPRETATION_TEXTS"
    )
    interpreter_thinking_level: Literal["minimal", "low", "medium", "high"] | None = Field(
        default=None, alias="TRIALFAIR_INTERPRETER_THINKING_LEVEL"
    )

    @field_validator("interpreter_thinking_level", mode="before")
    @classmethod
    def blank_thinking_level_is_unset(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    max_model_turns: int = Field(default=12, gt=0, alias="TRIALFAIR_MAX_MODEL_TURNS")
    max_external_requests: int = Field(default=16, gt=0, alias="TRIALFAIR_MAX_EXTERNAL_REQUESTS")
    max_evidence_requests: int = Field(default=2, gt=0, alias="TRIALFAIR_MAX_EVIDENCE_REQUESTS")
    max_additional_analyses: int = Field(default=3, gt=0, alias="TRIALFAIR_MAX_ADDITIONAL_ANALYSES")
    run_timeout_seconds: float = Field(
        default=150, gt=0, le=900, alias="TRIALFAIR_RUN_TIMEOUT_SECONDS"
    )
    demo_timeout_seconds: float = Field(
        default=600, gt=0, le=900, alias="TRIALFAIR_DEMO_TIMEOUT_SECONDS"
    )

    def require_live_credentials(self) -> None:
        """Fail explicitly at live execution time, never during import."""
        if self.mode == "live" and (
            not self.gemini_api_key
            or not self.gemini_api_key.get_secret_value().strip()
            or not self.gemini_model.strip()
        ):
            raise ValueError("Live execution requires GEMINI_API_KEY and GEMINI_MODEL")
