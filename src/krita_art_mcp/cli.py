import argparse
import sys
from collections.abc import Sequence

from krita_art_mcp import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="krita-art-mcp", description="An MCP server that lets AI agents paint in Krita."
    )
    parser.add_argument("--version", action="version", version=f"krita-art-mcp {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.add_parser("serve", help="run the MCP server over stdio")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        from krita_art_mcp.server import serve

        serve()
        return 0
    parser.print_usage(sys.stderr)
    return 2
