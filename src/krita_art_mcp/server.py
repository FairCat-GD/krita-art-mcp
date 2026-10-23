from mcp.server.mcpserver import MCPServer

from krita_art_mcp import __version__, tools
from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.instructions import INSTRUCTIONS

SERVER_NAME = "krita-art"


def build_server(client: BridgeClient | None = None) -> MCPServer:
    return MCPServer(
        SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        tools=tools.build_all(client or BridgeClient()),
    )


def serve() -> None:
    build_server().run("stdio")
