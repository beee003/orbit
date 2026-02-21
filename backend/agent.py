"""ORBIT Agent — Gemini-powered intent router with tool dispatch.

Single agent, router pattern. Intent classification via system prompt
forces structured JSON before every response — zero additional latency.
"""
import json
import time
import base64
import logging
from typing import Optional

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_VISION_MODEL

logger = logging.getLogger("orbit.agent")

_client = None

INTENTS = ["IDENTIFY", "REMEMBER", "RECALL", "OBSERVE", "CHITCHAT"]

SYSTEM_PROMPT = """You are ORBIT, a real-time AI networking assistant with persistent memory.
You see through the user's phone camera and hear their conversations.
You help them remember everyone they meet — names, topics, context.

Your personality: warm, concise, professional. Like a brilliant executive assistant
who whispers helpful context in your ear at a networking event.

EVERY response must start with a JSON intent classification on the first line:
{"intent": "<INTENT>", "entities": {...}}

Intents:
- IDENTIFY: A face is visible, user wants to know who it is
- REMEMBER: User wants to store information about someone (name, topic, etc.)
- RECALL: User is asking about a past conversation or person
- OBSERVE: General scene observation, no specific person query
- CHITCHAT: Social conversation not related to networking

After the JSON line, provide your natural spoken response (1-2 sentences max).
This response will be spoken aloud via TTS, so keep it conversational.

Context you'll receive:
- Face detection results (who is visible, confidence %)
- Memory context (past interactions with visible people)
- Scene description (what's happening)
- Conversation transcript (what's being said)

Rules:
- When you see an unknown face and learn their name from conversation,
  respond with REMEMBER intent to trigger memory storage
- When you recognize someone, proactively share relevant memories
- Keep responses SHORT — this is real-time, max 2 sentences spoken
- If confidence < 60%, say "I think that might be..." not "That's definitely..."
- Never invent memories. Only share what's in your context.
"""

# Additional routing corrections from self-learning (injected dynamically)
ROUTING_CORRECTIONS_PROMPT = """
Previous routing corrections (learn from these):
{corrections}
"""


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Initialized Gemini client")
    return _client


def build_context_prompt(
    face_results: Optional[dict] = None,
    memory_context: Optional[dict] = None,
    transcript: Optional[str] = None,
    scene_description: Optional[str] = None,
    routing_corrections: Optional[list] = None,
) -> str:
    """Build the full context prompt for the agent."""
    parts = []

    if face_results and face_results.get("faces"):
        faces_info = []
        for f in face_results["faces"]:
            status = "NEW (unknown)" if f.get("is_new") else "KNOWN"
            name = f.get("display_name") or f.get("person_id", "unknown")
            conf = f.get("confidence", 0)
            mcount = f.get("memory_count", 0)
            faces_info.append(f"  - {name} [{status}] confidence={conf:.1f}% memories={mcount}")
        parts.append("VISIBLE FACES:\n" + "\n".join(faces_info))

    if memory_context:
        if memory_context.get("all_memories"):
            mem_lines = []
            for m in memory_context["all_memories"][:5]:
                mem_lines.append(f"  - {m.get('content', '')}")
            parts.append("MEMORY CONTEXT:\n" + "\n".join(mem_lines))
        if memory_context.get("relevant_memories"):
            rel_lines = []
            for m in memory_context["relevant_memories"][:3]:
                rel_lines.append(f"  - {m.get('content', '')} (relevance={m.get('score', 0):.2f})")
            parts.append("RELEVANT MEMORIES:\n" + "\n".join(rel_lines))

    if transcript:
        parts.append(f"CURRENT CONVERSATION:\n  {transcript}")

    if scene_description:
        parts.append(f"SCENE: {scene_description}")

    if routing_corrections:
        corrections_text = "\n".join(f"  - {c}" for c in routing_corrections[-5:])
        parts.append(ROUTING_CORRECTIONS_PROMPT.format(corrections=corrections_text))

    return "\n\n".join(parts) if parts else "No context available. Waiting for camera input."


def respond(
    user_input: str,
    context_prompt: str,
    image_bytes: Optional[bytes] = None,
) -> dict:
    """Generate agent response with intent classification.

    Args:
        user_input: Text from user (transcribed speech or typed)
        context_prompt: Built context from build_context_prompt()
        image_bytes: Optional current camera frame for vision

    Returns:
        {intent, entities, text, raw_response, latency_ms}
    """
    start = time.time()
    client = _get_client()

    # Build message parts
    parts = []

    if image_bytes:
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

    parts.append(types.Part.from_text(text=f"{context_prompt}\n\nUSER: {user_input}"))

    response = client.models.generate_content(
        model=GEMINI_VISION_MODEL,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=300,
        ),
    )

    raw_text = response.text.strip()
    latency = (time.time() - start) * 1000

    # Parse intent from first line
    intent_data = _parse_intent(raw_text)
    spoken_text = _extract_spoken_text(raw_text)

    result = {
        "intent": intent_data.get("intent", "CHITCHAT"),
        "entities": intent_data.get("entities", {}),
        "text": spoken_text,
        "raw_response": raw_text,
        "latency_ms": latency,
    }

    logger.info(f"Agent response: intent={result['intent']} latency={latency:.0f}ms")
    return result


def describe_scene(image_bytes: bytes) -> str:
    """Use Gemini vision to describe the current scene."""
    client = _get_client()
    response = client.models.generate_content(
        model=GEMINI_VISION_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    types.Part.from_text(
                        text="Briefly describe this scene in 1 sentence. "
                        "Focus on: setting (conference, office, bar), number of people, "
                        "and any notable context (presentations, food, etc)."
                    ),
                ],
            )
        ],
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=100),
    )
    return response.text.strip()


def extract_name_from_transcript(transcript: str) -> Optional[dict]:
    """Use Gemini to extract a person's name mentioned in text.

    Works for both introductions ("Hi I'm Sarah") and queries ("Tell me about Sarah Chen").
    Returns: {name, company, role, topic} or None
    """
    if not transcript or len(transcript) < 5:
        return None

    client = _get_client()
    response = client.models.generate_content(
        model=GEMINI_VISION_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=f"""Extract any person's name mentioned in this text.
This could be an introduction ("Hi I'm Sarah Chen") OR a query about someone ("Tell me about Sarah Chen", "Who is Marcus?", "What did Alex say?").

If no person name is mentioned, respond with just: null

Text: {transcript}

Respond with ONLY JSON (no markdown):
{{"name": "First Last", "company": "Company or null", "role": "Role or null", "topic": "What they discussed or null"}}"""
                    ),
                ],
            )
        ],
        config=types.GenerateContentConfig(temperature=0, max_output_tokens=150),
    )

    text = response.text.strip()
    if text == "null" or not text:
        return None

    try:
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except (json.JSONDecodeError, IndexError):
        return None


def _parse_intent(raw_response: str) -> dict:
    """Parse intent JSON from the first line of agent response."""
    first_line = raw_response.split("\n")[0].strip()
    try:
        if first_line.startswith("{"):
            return json.loads(first_line)
    except json.JSONDecodeError:
        pass

    # Fallback: try to find JSON anywhere in response
    for line in raw_response.split("\n"):
        line = line.strip()
        if line.startswith("{") and '"intent"' in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    return {"intent": "CHITCHAT", "entities": {}}


def _extract_spoken_text(raw_response: str) -> str:
    """Extract the spoken text (everything after the JSON intent line)."""
    lines = raw_response.split("\n")
    non_json_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("{") and '"intent"' in stripped:
            continue
        if stripped:
            non_json_lines.append(stripped)
    return " ".join(non_json_lines) if non_json_lines else "I'm here and listening."
