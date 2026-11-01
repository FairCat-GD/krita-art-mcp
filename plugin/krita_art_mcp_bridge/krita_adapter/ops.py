from typing import Any

from krita import Krita

from ..bridge_core.errors import no_arguments
from ..bridge_core.jobs import Call, Handler


def unsaved_documents(args: dict[str, Any], call: Call) -> dict[str, Any]:
    # A session restarts Krita only when this reports nothing unsaved.
    no_arguments(args)
    documents = Krita.instance().documents()
    return {
        "open": len(documents),
        "unsaved": sum(1 for document in documents if document.modified()),
    }


HANDLERS: dict[str, Handler] = {
    "bridge.unsaved_documents": unsaved_documents,
}
