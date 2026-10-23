from mcp.server.mcpserver import MCPServer

from krita_art_mcp import __version__

SERVER_NAME = "krita-art"


def build_server() -> MCPServer:
    return MCPServer(SERVER_NAME, version=__version__)


def serve() -> None:
    build_server().run("stdio")
