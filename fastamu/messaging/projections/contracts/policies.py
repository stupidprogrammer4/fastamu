from pydantic import BaseModel, ConfigDict, Field


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    max_attempts: int = Field(default=3, ge=1)
    delay: float = Field(default=5.0, ge=0, allow_inf_nan=False)
