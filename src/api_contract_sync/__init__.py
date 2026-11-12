"""Keep a Spring Boot backend and a TypeScript frontend in sync.

Three steps, each usable from the command line (``api-contract-sync --help``) or
from Python:

    from api_contract_sync import build_contract, check, render_client

    contract = build_contract("backend")                 # Spring code -> contract dict
    files = render_client(contract)                      # {"types.ts": ..., "client.ts": ..., "index.ts": ...}
    findings = check(contract, "frontend/src")           # drift findings, most severe first

Standard library only; Python 3.9+.
"""

from __future__ import annotations

from pathlib import Path

from .check_drift import Checker, Finding, render_md
from .extract_spring import build_contract
from .generate_ts import render as render_client
from .ts_parser import TsProject

__version__ = "0.1.0"

__all__ = ["build_contract", "check", "render_client", "render_md", "Checker", "Finding", "TsProject", "__version__"]

_ORDER = {"error": 0, "warning": 1, "info": 2}


def check(contract: dict | str | Path, frontend: str | Path, *, strict_nulls: bool = False,
          client_fns: dict[str, str] | None = None, exclude: list[str] | None = None) -> list[Finding]:
    """Compare a frontend source directory with a contract (or a backend directory).

    ``client_fns`` maps extra fetch-like wrapper names to the base path they prepend,
    e.g. ``{"apiFetch": "/api"}``.
    """
    if not isinstance(contract, dict):
        contract = build_contract(Path(contract))
    checker = Checker(contract, TsProject(Path(frontend), exclude or [], client_fns or {}), strict_nulls)
    checker.run()
    return sorted(checker.findings.values(), key=lambda f: (_ORDER[f.severity], f.code, f.frontend or ""))
