"""Vercel entrypoint for the existing src-layout FastAPI application."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from onchain_risk_api.main import app  # noqa: E402,F401
