from mcp.server.mcpserver import MCPServer

from krita_art_mcp import __version__, paths, tools
from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.instructions import INSTRUCTIONS
from krita_art_mcp.journal import Journal

SERVER_NAME = "krita-art"


def build_server(client: BridgeClient, journal: Journal) -> MCPServer:
    return MCPServer(
        SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        tools=tools.build_all(client, journal),
    )


def serve() -> None:
    build_server(BridgeClient(), Journal(paths.journal_dir())).run("stdio")
