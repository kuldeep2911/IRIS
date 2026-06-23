"""agentmemory MCP server — persistent semantic memory over chromadb.

GOLDEN RULE #1 (MCP-first / "don't build a vector DB"): the vector store IS
chromadb (a maintained library); this is only a thin MCP adapter exposing it as
tools. (The PyPI `agentmemory` package is incompatible with current chromadb, so
we call chroma directly — same capability, no broken glue.)

Run as a stdio MCP server: ``python -m iris.mcp.servers.agentmemory_server``.
Storage persists on disk (so facts learned in one session are recalled in the
next). Tenant isolation is by collection name, chosen by the IRIS-side wrapper.

Tools: ``memory_store``, ``memory_search``, ``memory_update``, ``memory_delete``,
``memory_list``, ``memory_count``. Each returns a JSON string.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import chromadb
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agentmemory")


def _storage_path() -> str:
    # Default to <repo>/data/chroma; overridable via env. cwd is the repo root
    # when IRIS spawns this server.
    return os.environ.get("IRIS_MEMORY_PATH") or str(Path("data") / "chroma")


_client: chromadb.api.ClientAPI | None = None


def _col(collection: str):
    global _client
    if _client is None:
        Path(_storage_path()).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=_storage_path())
    # collection names: 3-63 chars, alnum/_/-, start+end alnum.
    safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in collection)[:63]
    safe = safe or "default"
    return _client.get_or_create_collection(safe)


@mcp.tool()
def memory_store(collection: str, text: str, metadata: dict | None = None) -> str:
    """Store a memory and return its id (JSON: {"id": ...})."""
    mem_id = uuid.uuid4().hex
    _col(collection).upsert(ids=[mem_id], documents=[text], metadatas=[metadata or {"_": "1"}])
    return json.dumps({"id": mem_id})


@mcp.tool()
def memory_search(
    collection: str, query: str, n_results: int = 8, where: dict | None = None
) -> str:
    """Semantic search. Returns JSON list of {id, text, metadata, distance}."""
    col = _col(collection)
    count = col.count()
    if count == 0:
        return json.dumps([])
    res = col.query(
        query_texts=[query],
        n_results=min(n_results, count),
        where=where or None,
    )
    out: list[dict[str, Any]] = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for i, mem_id in enumerate(ids):
        out.append(
            {
                "id": mem_id,
                "text": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": float(dists[i]) if i < len(dists) else None,
            }
        )
    return json.dumps(out)


@mcp.tool()
def memory_update(
    collection: str, id: str, text: str | None = None, metadata: dict | None = None
) -> str:
    """Update a memory's text and/or metadata."""
    kwargs: dict[str, Any] = {"ids": [id]}
    if text is not None:
        kwargs["documents"] = [text]
    if metadata is not None:
        kwargs["metadatas"] = [metadata]
    _col(collection).update(**kwargs)
    return json.dumps({"id": id, "updated": True})


@mcp.tool()
def memory_delete(collection: str, id: str) -> str:
    """Delete a memory by id."""
    _col(collection).delete(ids=[id])
    return json.dumps({"id": id, "deleted": True})


@mcp.tool()
def memory_list(collection: str, limit: int = 50, where: dict | None = None) -> str:
    """List stored memories (JSON list of {id, text, metadata})."""
    res = _col(collection).get(where=where or None, limit=limit)
    ids = res.get("ids") or []
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    out = [
        {"id": ids[i], "text": docs[i] if i < len(docs) else "", "metadata": metas[i] if i < len(metas) else {}}
        for i in range(len(ids))
    ]
    return json.dumps(out)


@mcp.tool()
def memory_count(collection: str) -> str:
    """Return the number of memories in a collection."""
    return json.dumps({"count": _col(collection).count()})


if __name__ == "__main__":
    mcp.run()
