import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path

import httpx
from pydantic import ValidationError

from onchain_risk_api.app import create_app
from onchain_risk_api.domain.models import ApiError
from onchain_risk_api.llm.config import LlmSettings
from onchain_risk_api.llm.evidence import EvidenceRecorder
from onchain_risk_api.llm.http import model_client_options
from onchain_risk_api.llm.models import AgentResult
from onchain_risk_api.llm.provider import OpenAIResponsesProvider
from onchain_risk_api.llm.runner import InvestigationRunner


async def _investigate(prompt: str, *, evidence: EvidenceRecorder | None = None) -> AgentResult:
    settings = LlmSettings()
    if evidence is not None:
        evidence.configure_model(settings)
    app = create_app()
    if evidence is not None:
        evidence.configure_network(app.state.settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(**model_client_options(settings)) as client,
    ):
        runner = InvestigationRunner(
            settings=settings, provider=OpenAIResponsesProvider(settings=settings, client=client),
            tools=app.state.tool_registry, network_name=app.state.settings.network_name,
            chain_id=app.state.settings.expected_chain_id,
        )
        return await runner.run(prompt)


def _run_cli(prompt: str, evidence: EvidenceRecorder | None = None) -> AgentResult:
    try:
        if evidence is not None:
            return asyncio.run(_investigate(prompt, evidence=evidence))
        return asyncio.run(_investigate(prompt))
    except ValidationError:
        return AgentResult(
            status="error", stop_reason="CONFIGURATION_ERROR",
            error=ApiError(code="CONFIGURATION_ERROR", message="Check local RPC and LLM settings."),
        )
    except Exception:
        return AgentResult(
            status="error", stop_reason="AGENT_EXECUTION_FAILED",
            error=ApiError(code="AGENT_EXECUTION_FAILED", message="Investigation startup failed."),
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded, read-only LLM investigation.")
    parser.add_argument("prompt", help="A question, or - to read up to 8000 characters from stdin.")
    parser.add_argument("--scenario-id", choices=[f"S{number:02}" for number in range(1, 21)])
    parser.add_argument("--save-evidence", type=Path, help="Create a new UTF-8 evidence JSON file.")
    args = parser.parse_args(argv)
    if bool(args.scenario_id) != bool(args.save_evidence):
        parser.error("Use --scenario-id and --save-evidence together.")
    prompt = sys.stdin.read(8001) if args.prompt == "-" else args.prompt
    evidence = (
        EvidenceRecorder(scenario_id=args.scenario_id, prompt=prompt)
        if args.save_evidence else None
    )
    try:
        with ExitStack() as stack:
            destination = (
                stack.enter_context(args.save_evidence.open("x", encoding="utf-8"))
                if args.save_evidence else None
            )
            result = _run_cli(prompt, evidence)
            output = result.model_dump(mode="json", by_alias=True)
            print(json.dumps(
                evidence.redact(output) if evidence is not None else output,
                ensure_ascii=False, indent=2,
            ))
            if destination is not None and evidence is not None:
                destination.write(evidence.serialize(result))
    except OSError:
        print("EVIDENCE_WRITE_FAILED: Use a new file in an existing writable directory.",
              file=sys.stderr)
        return 2
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
