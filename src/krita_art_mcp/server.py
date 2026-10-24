import logging
import threading

from mcp.server.mcpserver import MCPServer

from krita_art_mcp import __version__, baselines, paths, tools
from krita_art_mcp.bridge_client import BridgeClient
from krita_art_mcp.instructions import INSTRUCTIONS
from krita_art_mcp.journal import Journal
from krita_art_mcp.paths import Places

SERVER_NAME = "krita-art"
# The orphan sweep only reports; it never waits out a busy Krita.
SWEEP_BUDGET_S = 5.0

log = logging.getLogger(__name__)


def build_server(client: BridgeClient, journal: Journal, places: Places) -> MCPServer:
    return MCPServer(
        SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        tools=tools.build_all(client, journal, places),
    )


def serve() -> None:
    places = Places.default()
    # On its own thread, so a busy Krita never delays the client's handshake.
    threading.Thread(
        target=_sweep_baselines, args=(places,), name="krita-art-mcp-baselines", daemon=True
    ).start()
    build_server(BridgeClient(), Journal(paths.journal_dir()), places).run("stdio")


def _sweep_baselines(places: Places) -> None:
    try:
        baselines.sweep(BridgeClient(budget_s=SWEEP_BUDGET_S), places.baselines_dir)
    except Exception:
        log.exception("the orphaned baselines were not swept")
