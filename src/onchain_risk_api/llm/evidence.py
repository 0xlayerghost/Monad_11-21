import json
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlsplit

from pydantic import Field, field_validator

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.models import ApiModel
from onchain_risk_api.llm.config import LlmSettings
from onchain_risk_api.llm.models import AgentResult


class EvidenceReview(ApiModel):
    fact_check: Literal["pending", "pass", "fail", "not_applicable"] = "pending"
    provider_billing_checked: bool = False
    unsupported_claims: list[str] = Field(default_factory=list)
    notes: str = ""


class InvestigationEvidence(ApiModel):
    schema_version: Literal[1] = 1
    scenario_id: str = Field(pattern=r"^S(?:0[1-9]|1[0-9]|20)$")
    started_at: datetime
    finished_at: datetime
    model_id: str | None
    network: str | None
    expected_chain_id: int | None
    rpc_provider: str | None
    prompt: str
    result: AgentResult
    review: EvidenceReview = Field(default_factory=EvidenceReview)

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Evidence schema version must be an integer.")
        return value


class EvidenceRecorder:
    def __init__(self, *, scenario_id: str, prompt: str) -> None:
        self._scenario_id = scenario_id
        self._prompt = prompt
        self._started_at = datetime.now(UTC)
        self._model_id: str | None = None
        self._network: str | None = None
        self._expected_chain_id: int | None = None
        self._rpc_provider: str | None = None
        self._secrets: set[str] = set()

    def configure_model(self, settings: LlmSettings) -> None:
        self._model_id = settings.model
        self._secrets.add(settings.api_key.get_secret_value())
        self._remember_endpoint(str(settings.base_url))

    def configure_network(self, settings: Settings) -> None:
        self._network = settings.network_name
        self._expected_chain_id = settings.expected_chain_id
        self._rpc_provider = settings.rpc_provider_name
        self._remember_endpoint(str(settings.rpc_url))

    def _remember_endpoint(self, endpoint: str) -> None:
        self._secrets.add(endpoint)
        self._secrets.add(endpoint.rstrip("/"))
        parsed = urlsplit(endpoint)
        for credential in (parsed.username, parsed.password):
            if credential:
                self._secrets.update((credential, unquote(credential)))
        for segment in parsed.path.split("/"):
            if len(segment) >= 8:
                self._secrets.update((segment, unquote(segment)))
        for _, value in parse_qsl(parsed.query):
            if value:
                self._secrets.add(value)

    def redact(self, value: object) -> object:
        if isinstance(value, str):
            for secret in sorted(self._secrets, key=len, reverse=True):
                if secret:
                    value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        return value

    def serialize(self, result: AgentResult) -> str:
        record = InvestigationEvidence(
            scenario_id=self._scenario_id, started_at=self._started_at,
            finished_at=datetime.now(UTC), model_id=self._model_id,
            network=self._network, expected_chain_id=self._expected_chain_id,
            rpc_provider=self._rpc_provider, prompt=self._prompt, result=result,
        )
        return json.dumps(
            self.redact(record.model_dump(mode="json", by_alias=True)),
            ensure_ascii=False, indent=2,
        ) + "\n"
