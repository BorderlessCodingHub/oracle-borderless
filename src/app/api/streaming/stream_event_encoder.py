"""Serialização do `GraphEvent` em blocos SSE (ADR-0021).

Camada `app`: aqui — e só aqui, além do request schema — o fio existe. O grafo
fala `GraphEvent` (`src/support/agent/ports.py`, já redigido); esta função pura
o escreve como `event: <nome>\\ndata: <StreamEvent JSON>\\n\\n`.

O único evento que não vem do grafo é `error_event()`: um `on_chain_error` do
raiz para falha no meio do stream. Ele é terminal — não há `on_chain_end`
depois dele.
"""

import dataclasses
import json

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import ROOT_NAME, GraphEvent

CONTENT_TYPE = "text/event-stream"
ERROR_EVENT = "on_chain_error"


def _json_default(obj):
    if isinstance(obj, Citation):
        # page_id fica de fora: é o id interno do Notion (regra 4).
        return {"source_type": obj.source_type, "title": obj.title, "url": obj.url, "snippet": obj.snippet}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"objeto não serializável no fio: {type(obj).__name__}")


def encode(event: GraphEvent) -> str:
    payload = {
        "event": event.event,
        "name": event.name,
        "run_id": event.run_id,
        "tags": list(event.tags),
        "metadata": dict(event.metadata),
        "parent_ids": list(event.parent_ids),
        "data": event.data,
    }
    return f"event: {event.event}\ndata: {json.dumps(payload, ensure_ascii=False, default=_json_default)}\n\n"


def error_event(run_id: str, thread_id: str, message: str) -> GraphEvent:
    return GraphEvent(
        event=ERROR_EVENT,
        name=ROOT_NAME,
        run_id=run_id,
        tags=[],
        metadata={"thread_id": thread_id},
        parent_ids=[],
        data={"error": message},
    )
