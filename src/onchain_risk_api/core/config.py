from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from onchain_risk_api import __version__
from onchain_risk_api.domain.validation import EvmAddress


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "onchain-risk-api"
    service_version: str = __version__
    network_name: str = Field(default="base-sepolia", pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    expected_chain_id: int = Field(default=84532, gt=0)
    native_symbol: str = Field(default="ETH", min_length=1, max_length=16)
    native_decimals: int = Field(default=18, ge=0, le=255)
    rpc_provider_name: str = Field(default="custom", min_length=1, max_length=64)
    rpc_url: AnyHttpUrl
    rpc_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    erc20_allowed_tokens: list[EvmAddress] = Field(default_factory=list, max_length=50)
    erc20_allowed_spenders: list[EvmAddress] = Field(default_factory=list, max_length=50)
