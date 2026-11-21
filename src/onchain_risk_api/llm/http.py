import ssl
from typing import TypedDict

from onchain_risk_api.llm.config import LlmSettings


class ModelClientOptions(TypedDict):
    trust_env: bool
    verify: bool | ssl.SSLContext


def model_client_options(settings: LlmSettings) -> ModelClientOptions:
    if settings.tls_trust_store == "system":
        context = ssl.create_default_context()
        context.keylog_filename = None
        return {"trust_env": True, "verify": context}
    return {"trust_env": True, "verify": True}
