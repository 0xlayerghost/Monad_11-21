import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from onchain_risk_api.app import create_app
from onchain_risk_api.domain.models import ApiError
from onchain_risk_api.tools.models import ToolCallResult
from onchain_risk_api.tools.registry import get_tool_definitions


async def _call_tool(name: str, arguments: str) -> ToolCallResult:
    app = create_app()
    async with app.router.lifespan_context(app):
        return await app.state.tool_registry.execute(name, arguments)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or call the registered read-only tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Print tool schemas without loading .env or calling RPC.")
    call = commands.add_parser("call", help="Run one query using the local .env configuration.")
    call.add_argument("name")
    call.add_argument("arguments", help="A JSON object, or - to read JSON from stdin.")
    args = parser.parse_args(argv)
    if args.command == "list":
        definitions = [
            item.model_dump(mode="json", by_alias=True) for item in get_tool_definitions()
        ]
        print(json.dumps(definitions, indent=2))
        return 0
    try:
        arguments = sys.stdin.read() if args.arguments == "-" else args.arguments
        result = asyncio.run(_call_tool(args.name, arguments))
    except ValidationError:
        result = ToolCallResult(
            tool_name=args.name, status="error",
            error=ApiError(
                code="CONFIGURATION_ERROR", message="Check the local service configuration."
            ),
        )
    except Exception:
        result = ToolCallResult(
            tool_name=args.name, status="error",
            error=ApiError(
                code="TOOL_EXECUTION_FAILED", message="The tool could not complete its query."
            ),
        )
    print(result.model_dump_json(by_alias=True, indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
