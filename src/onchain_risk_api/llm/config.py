from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_key: SecretStr = Field(repr=False)
    model: str = Field(min_length=1, max_length=120)
    base_url: AnyHttpUrl = "https://api.openai.com/v1"
    tls_trust_store: Literal["certifi", "system"] = "certifi"
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    run_timeout_seconds: float = Field(default=60, gt=0, le=300)
    max_model_calls: int = Field(default=4, ge=1, le=10)
    max_tool_calls: int = Field(default=4, ge=1, le=10)
    max_output_tokens: int = Field(default=800, ge=64, le=4096)
    output_token_budget: int = Field(default=2400, ge=64, le=16384)

    @model_validator(mode="after")
    def validate_credentials_and_endpoint(self) -> Self:
        if not self.api_key.get_secret_value().strip() or not self.model.strip():
            raise ValueError("Configure a non-empty LLM key and model.")
        if self.base_url.username or self.base_url.password:
            raise ValueError("Do not put credentials in the model endpoint.")
        if self.base_url.query or self.base_url.fragment:
            raise ValueError("The model endpoint must not contain a query or fragment.")
        if self.base_url.scheme != "https" and self.base_url.host not in {
            "localhost", "127.0.0.1", "[::1]"
        }:
            raise ValueError("Use HTTPS for a remote model endpoint.")
        return self
