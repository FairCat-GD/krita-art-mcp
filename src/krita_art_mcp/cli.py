import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from krita_art_mcp import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="krita-art-mcp", description="An MCP server that lets AI agents paint in Krita."
    )
    parser.add_argument("--version", action="version", version=f"krita-art-mcp {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")
    commands.add_parser("serve", help="run the MCP server over stdio")
    install = commands.add_parser("install-plugin", help="copy the plugin into Krita's pykrita")
    install.add_argument(
        "--krita-data-dir",
        type=Path,
        help="Krita's resource folder (default: ~/Library/Application Support/Krita)",
    )
    roots = commands.add_parser("roots", help="the folders agents may use")
    actions = roots.add_subparsers(dest="action", metavar="action", required=True)
    actions.add_parser("add", help="allow a folder").add_argument("directory")
    actions.add_parser("list", help="list the allowed folders")
    actions.add_parser("remove", help="stop allowing a folder").add_argument("directory")
    commands.add_parser("doctor", help="name the first failing setup step")
    commands.add_parser("probe", help="run the live harness against the running Krita")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        from krita_art_mcp.server import serve

        serve()
        return 0
    if args.command == "install-plugin":
        from krita_art_mcp import install, paths

        return install.run(args.krita_data_dir or paths.krita_data_dir(), paths.kritarc())
    if args.command == "roots":
        from krita_art_mcp import paths, roots

        return roots.run(
            args.action,
            getattr(args, "directory", None),
            paths.config_file(),
            data_dirs=[paths.default_data_dir(), paths.server_data_dir()],
        )
    if args.command == "doctor":
        from krita_art_mcp import doctor

        return doctor.run()
    if args.command == "probe":
        from krita_art_mcp import probe

        return probe.run()
    parser.print_usage(sys.stderr)
    return 2
