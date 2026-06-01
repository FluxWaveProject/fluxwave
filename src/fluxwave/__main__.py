"""Command line helpers for FluxWave."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys

import fluxwave


def main(argv: list[str] | None = None) -> int:
    """Run the FluxWave command line interface."""

    parser = argparse.ArgumentParser(prog="fluxwave")
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show FluxWave version and debug information.",
    )

    args = parser.parse_args(argv)
    if args.version:
        print(debug_info())
        return 0

    parser.print_help()
    return 0


def debug_info() -> str:
    """Return version, Python, platform, and Java diagnostic information."""

    python_info = "\n        - ".join(sys.version.splitlines())
    java_info = "\n        - ".join(_java_version().splitlines())
    return f"""fluxwave: {fluxwave.__version__}

Python:
        - {python_info}
System:
        - {platform.platform()}
Java:
        - {java_info}
"""


def _java_version() -> str:
    try:
        completed = subprocess.run(
            ["java", "-version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return "Java executable not found"

    output = (completed.stderr or completed.stdout).strip()
    if not output:
        return "Version not found"

    if completed.returncode != 0:
        return f"Command failed with exit code {completed.returncode}: {output}"

    return output


if __name__ == "__main__":
    raise SystemExit(main())
