"""Command line entry point: api-contract-sync <extract|generate|check> ..."""

from __future__ import annotations

import sys

from . import __version__, check_drift, extract_spring, generate_ts

COMMANDS = {
    "extract": (extract_spring.main, "Spring backend -> contract JSON"),
    "generate": (generate_ts.main, "contract or backend -> TypeScript types + typed fetch client"),
    "check": (check_drift.main, "contract or backend + frontend/src -> drift report (exit 1 on errors)"),
}

USAGE = f"""usage: api-contract-sync <command> [options]

Keep a Spring Boot backend and a TypeScript frontend in sync.

commands:
{chr(10).join(f"  {name:<9} {desc}" for name, (_, desc) in COMMANDS.items())}

examples:
  api-contract-sync check backend frontend/src
  api-contract-sync check backend frontend/src --github-annotations --md drift.md
  api-contract-sync generate backend -o frontend/src/api/generated
  api-contract-sync generate backend -o frontend/src/api/generated --check
  api-contract-sync extract backend -o contract.json --summary

Run 'api-contract-sync <command> --help' for a command's options.
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"api-contract-sync {__version__}")
        return 0
    cmd = argv.pop(0)
    if cmd not in COMMANDS:
        print(f"api-contract-sync: unknown command {cmd!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    sys.argv[0] = f"api-contract-sync {cmd}"  # so argparse --help shows the right program name
    return COMMANDS[cmd][0](argv)


if __name__ == "__main__":
    sys.exit(main())
