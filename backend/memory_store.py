"""Memory store — mem0 wrapper with Pinecone backend for per-person structured memory."""
import logging
import re
import time
import urllib.parse
from typing import Optional

import httpx

from config import MEM0_API_KEY, PINECONE_API_KEY, PINECONE_INDEX

logger = logging.getLogger("orbit.memory")

_mem0_client = None
_face_name_map: dict[str, str] = {}  # exact face_id → name mapping (in-memory)


def _get_mem0():
    global _mem0_client
    if _mem0_client is None:
        from mem0 import MemoryClient
        _mem0_client = MemoryClient(api_key=MEM0_API_KEY)
        logger.info("Initialized mem0 client")
    return _mem0_client


def add_memory(person_id: str, content: str, metadata: Optional[dict] = None) -> dict:
    """Store a SHARED memory associated with a person (visible to all users).

    Args:
        person_id: Unique person identifier (e.g. 'sarah_chen')
        content: The memory content (e.g. 'Works at Datadog on APM team')
        metadata: Optional metadata (topic, timestamp, etc.)
    """
    m = _get_mem0()
    meta = metadata or {}
    meta["stored_at"] = time.time()
    meta["scope"] = "shared"

    result = m.add(
        content,
        user_id=person_id,
        metadata=meta,
    )
    logger.info(f"Stored shared memory for {person_id}: {content[:80]}...")
    return {"status": "stored", "person_id": person_id, "result": result}


def add_private_memory(user_id: str, person_id: str, content: str, metadata: Optional[dict] = None) -> dict:
    """Store a PRIVATE memory — only this user can see it.

    Private memories are stored under a composite key: user_id + person_id.
    e.g., "ben_private_austin_omala" — only Ben sees his notes about Austin.
    """
    m = _get_mem0()
    meta = metadata or {}
    meta["stored_at"] = time.time()
    meta["scope"] = "private"
    meta["owner"] = user_id
    meta["about"] = person_id

    private_key = f"{user_id}_private_{person_id}"
    result = m.add(
        content,
        user_id=private_key,
        metadata=meta,
    )
    logger.info(f"Stored private memory ({user_id}) about {person_id}: {content[:80]}...")
    return {"status": "stored", "person_id": person_id, "user_id": user_id, "result": result}


def get_private_memories(user_id: str, person_id: str) -> list[dict]:
    """Get all private memories a user has about a person."""
    private_key = f"{user_id}_private_{person_id}"
    return get_all_memories(private_key)


def search_memories(person_id: str, query: str, limit: int = 5) -> list[dict]:
    """Search memories for a specific person.

    Args:
        person_id: The person to search memories for
        query: Natural language search query
        limit: Max results
    """
    m = _get_mem0()
    results = m.search(query, user_id=person_id, limit=limit, filters={"user_id": person_id})
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
    results = m.get_all(user_id=person_id, filters={"user_id": person_id})
    memories = []
    for r in (results.get("results", []) if isinstance(results, dict) else results):
        memories.append({
            "content": r.get("memory", r.get("content", "")),
            "metadata": r.get("metadata", {}),
        })
    return memories


def get_person_context(person_id: str, current_query: Optional[str] = None,
                       user_id: Optional[str] = None) -> dict:
    """Build full context for a person — shared + private memories.

    Args:
        person_id: The person to get context for
        current_query: Optional query to search relevant memories
        user_id: Optional user ID to include private memories

    Returns a structured context dict for the Gemini prompt.
    """
    # Shared memories (visible to everyone)
    shared_memories = get_all_memories(person_id)

    # Private memories (only this user's notes)
    private_memories = []
    if user_id:
        private_memories = get_private_memories(user_id, person_id)

    all_memories = shared_memories + private_memories

    relevant = []
    if current_query:
        relevant = search_memories(person_id, current_query, limit=3)

    # Build context summary
    context = {
        "person_id": person_id,
        "total_memories": len(all_memories),
        "shared_memories": len(shared_memories),
        "private_memories": len(private_memories),
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

    Uses in-memory dict for exact lookup + mem0 for persistence.
    """
    _face_name_map[face_external_id] = display_name
    logger.info(f"Mapped face {face_external_id} → {display_name}")
    return add_memory(
        "system_face_mappings",
        f"Face ID '{face_external_id}' belongs to '{display_name}'.",
        metadata={"type": "face_mapping", "face_id": face_external_id, "name": display_name},
    )


def lookup_face_name(face_external_id: str) -> Optional[str]:
    """Look up the display name for a face external ID. Uses exact match only."""
    # Exact in-memory lookup — no semantic search fuzzy matching
    return _face_name_map.get(face_external_id)


def store_system_memory(key: str, content: str) -> dict:
    """Store a system-level memory (e.g., routing corrections, learned preferences)."""
    return add_memory("system", content, metadata={"type": "system", "key": key})


def get_system_memories(query: str, limit: int = 5) -> list[dict]:
    """Retrieve system-level memories."""
    return search_memories("system", query, limit=limit)


def lookup_linkedin(name: str, company: Optional[str] = None) -> Optional[str]:
    """Search for a person's LinkedIn profile URL.

    Tries DuckDuckGo then Google to find linkedin.com/in/ profile pages.
    Returns the LinkedIn URL or a search fallback.
    """
    query_parts = [name]
    if company:
        query_parts.append(company)
    query_parts.append("linkedin")
    search_query = " ".join(query_parts)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    # Try DuckDuckGo first (less blocking)
    for search_url in [
        f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(search_query + ' site:linkedin.com/in/')}",
        f"https://www.google.com/search?q={urllib.parse.quote(search_query + ' site:linkedin.com/in/')}&num=3",
    ]:
        try:
            resp = httpx.get(search_url, headers=headers, timeout=5.0, follow_redirects=True)
            linkedin_urls = re.findall(r'https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+/?', resp.text)
            if linkedin_urls:
                profile_url = linkedin_urls[0].rstrip("/")
                logger.info(f"Found LinkedIn for {name}: {profile_url}")
                return profile_url
        except Exception as e:
            logger.warning(f"Search failed for {name}: {e}")
            continue

    # Fallback: construct a LinkedIn search URL (always works)
    fallback = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(name)}"
    logger.info(f"Using LinkedIn search URL for {name}: {fallback}")
    return fallback


def store_linkedin(person_id: str, name: str, linkedin_url: str) -> dict:
    """Store a person's LinkedIn URL in their memory."""
    return add_memory(
        person_id,
        f"{name}'s LinkedIn profile: {linkedin_url}",
        metadata={"type": "linkedin", "linkedin_url": linkedin_url, "name": name},
    )


def _summarize_memories(memories: list[dict]) -> str:
    """Create a brief text summary from a list of memories."""
    if not memories:
        return "No previous interactions recorded."
    contents = [m.get("content", "") for m in memories[:10]]
    return " | ".join(contents)
