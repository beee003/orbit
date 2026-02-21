"""Memory store — mem0 wrapper with Pinecone backend for per-person structured memory."""
import logging
import time
from typing import Optional

from config import MEM0_API_KEY, PINECONE_API_KEY, PINECONE_INDEX

logger = logging.getLogger("orbit.memory")

_mem0_client = None


def _get_mem0():
    global _mem0_client
    if _mem0_client is None:
        from mem0 import MemoryClient
        _mem0_client = MemoryClient(api_key=MEM0_API_KEY)
        logger.info("Initialized mem0 client")
    return _mem0_client


def add_memory(person_id: str, content: str, metadata: Optional[dict] = None) -> dict:
    """Store a memory associated with a person.

    Args:
        person_id: Unique person identifier (e.g. 'sarah_chen')
        content: The memory content (e.g. 'Works at Datadog on APM team')
        metadata: Optional metadata (topic, timestamp, etc.)
    """
    m = _get_mem0()
    meta = metadata or {}
    meta["stored_at"] = time.time()

    result = m.add(
        content,
        user_id=person_id,
        metadata=meta,
    )
    logger.info(f"Stored memory for {person_id}: {content[:80]}...")
    return {"status": "stored", "person_id": person_id, "result": result}


def search_memories(person_id: str, query: str, limit: int = 5) -> list[dict]:
    """Search memories for a specific person.

    Args:
        person_id: The person to search memories for
        query: Natural language search query
        limit: Max results
    """
    m = _get_mem0()
    results = m.search(query, user_id=person_id, limit=limit)
    memories = []
    for r in (results.get("results", []) if isinstance(results, dict) else results):
        memories.append({
            "content": r.get("memory", r.get("content", "")),
            "score": r.get("score", 0),
            "metadata": r.get("metadata", {}),
        })
    logger.info(f"Found {len(memories)} memories for {person_id} (query: {query[:50]})")
    return memories


def get_all_memories(person_id: str) -> list[dict]:
    """Get all stored memories for a person."""
    m = _get_mem0()
    results = m.get_all(user_id=person_id)
    memories = []
    for r in (results.get("results", []) if isinstance(results, dict) else results):
        memories.append({
            "content": r.get("memory", r.get("content", "")),
            "metadata": r.get("metadata", {}),
        })
    return memories


def get_person_context(person_id: str, current_query: Optional[str] = None) -> dict:
    """Build full context for a person — all memories + relevant search results.

    This is the main function called by the agent before responding.
    Returns a structured context dict for the Gemini prompt.
    """
    all_memories = get_all_memories(person_id)

    relevant = []
    if current_query:
        relevant = search_memories(person_id, current_query, limit=3)

    # Build context summary
    context = {
        "person_id": person_id,
        "total_memories": len(all_memories),
        "all_memories": all_memories,
        "relevant_memories": relevant,
        "summary": _summarize_memories(all_memories),
    }
    return context


def store_identity(person_id: str, display_name: str, metadata: Optional[dict] = None) -> dict:
    """Store or update a person's identity (name, role, company, etc.).

    Called when the agent learns someone's name from conversation.
    """
    identity_str = f"This person's name is {display_name}."
    if metadata:
        if metadata.get("company"):
            identity_str += f" Works at {metadata['company']}."
        if metadata.get("role"):
            identity_str += f" Role: {metadata['role']}."
        if metadata.get("topic"):
            identity_str += f" Discussed: {metadata['topic']}."

    return add_memory(person_id, identity_str, metadata={"type": "identity", **(metadata or {})})


def store_conversation_summary(person_id: str, summary: str, topics: list[str] = None) -> dict:
    """Store a conversation summary after an interaction ends."""
    meta = {"type": "conversation", "topics": topics or []}
    return add_memory(person_id, summary, metadata=meta)


def get_identity(person_id: str) -> Optional[dict]:
    """Retrieve the identity record for a person."""
    memories = search_memories(person_id, "name identity who is this person", limit=1)
    if memories:
        return memories[0]
    return None


def update_identity_mapping(face_external_id: str, display_name: str) -> dict:
    """Map a Rekognition external_id to a human-readable name.

    Stored as a system-level memory so the agent can look up names from face IDs.
    """
    return add_memory(
        "system_face_mappings",
        f"Face ID '{face_external_id}' belongs to '{display_name}'.",
        metadata={"type": "face_mapping", "face_id": face_external_id, "name": display_name},
    )


def lookup_face_name(face_external_id: str) -> Optional[str]:
    """Look up the display name for a face external ID."""
    results = search_memories("system_face_mappings", f"face ID {face_external_id}", limit=1)
    if results:
        meta = results[0].get("metadata", {})
        if meta.get("name"):
            return meta["name"]
        # Parse from content
        content = results[0].get("content", "")
        if "belongs to" in content:
            return content.split("belongs to '")[1].rstrip("'.")
    return None


def store_system_memory(key: str, content: str) -> dict:
    """Store a system-level memory (e.g., routing corrections, learned preferences)."""
    return add_memory("system", content, metadata={"type": "system", "key": key})


def get_system_memories(query: str, limit: int = 5) -> list[dict]:
    """Retrieve system-level memories."""
    return search_memories("system", query, limit=limit)


def _summarize_memories(memories: list[dict]) -> str:
    """Create a brief text summary from a list of memories."""
    if not memories:
        return "No previous interactions recorded."
    contents = [m.get("content", "") for m in memories[:10]]
    return " | ".join(contents)
