"""ORBIT Backend — FastAPI + WebSocket server.

Wires: Camera frames → face_pipeline → memory_store → agent → TTS → WebSocket response
Every interaction traced via Datadog. Self-learning loops run automatically.
"""
import asyncio
import base64
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")

import config
import face_pipeline
import memory_store
import agent
import tts
import stt
import enrichment
import linkedin_auth
import datadog_integration as dd
from self_learning import face_tracker, retrieval_evaluator, intent_calibrator, get_learning_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("orbit.main")

# Track connected clients and state
active_connections: list[WebSocket] = []
interaction_count = 0
people_identified = 0
transcript_buffer: dict[str, str] = {}  # person_id → accumulated transcript
_last_agent_call: dict[str, float] = {}  # person_id → last time agent was called
_last_seen_face: Optional[str] = None  # most recently detected primary face ID
_prev_face_ids: dict[int, set[str]] = {}  # ws id → set of face IDs from last frame
_msg_counter = 0
AGENT_COOLDOWN_SECS = 10  # Don't call agent for same person more than once per 10s


async def emit(ws: WebSocket, event_type: str, data: dict):
    """Send a {type, data} event to the client — single wire format."""
    await ws.send_json({"type": event_type, "data": data})


def _next_msg_id() -> str:
    global _msg_counter
    _msg_counter += 1
    return f"msg_{_msg_counter}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ORBIT backend starting...")
    logger.info(f"Gemini model: {config.GEMINI_VISION_MODEL}")
    logger.info(f"Rekognition collection: {config.REKOGNITION_COLLECTION_ID}")

    # Restore face name mappings from saved profiles
    for profile in face_tracker.get_all_profiles():
        pid = profile.get("person_id", "")
        name = profile.get("display_name", "")
        if pid and name and profile.get("identity_confirmed"):
            memory_store._face_name_map[pid] = name
            logger.info(f"Restored face mapping: {pid} → {name}")

    yield
    logger.info("ORBIT backend shutting down")


app = FastAPI(
    title="ORBIT",
    description="Observability for Real-world Behavioral Intelligence & Tracking",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── REST Endpoints ───

# Serve React frontend build (if it exists), fallback to test_camera.html
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the React frontend (or fallback to test_camera.html)."""
    index_html = _frontend_dist / "index.html"
    if index_html.exists():
        return HTMLResponse(content=index_html.read_text())
    html_path = Path(__file__).parent.parent / "test_camera.html"
    return HTMLResponse(content=html_path.read_text())


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "orbit",
        "interactions": interaction_count,
        "people": people_identified,
    }


@app.get("/api/learning-report")
async def learning_report():
    """Get the current state of all 3 self-learning loops."""
    return get_learning_report()


@app.get("/api/profiles")
async def list_profiles():
    """List all tracked face profiles."""
    return face_tracker.get_all_profiles()


@app.get("/api/memories/{person_id}")
async def get_memories(person_id: str):
    """Get all memories for a person."""
    return memory_store.get_all_memories(person_id)


@app.get("/api/dashboard")
async def get_dashboard():
    """Get Datadog dashboard definition JSON."""
    return dd.DASHBOARD_JSON


@app.get("/api/linkedin/status")
async def linkedin_status():
    """Check if LinkedIn is authenticated."""
    return {"authenticated": linkedin_auth.is_authenticated()}


@app.get("/api/linkedin/auth")
async def linkedin_auth_start():
    """Generate LinkedIn OAuth URL for the user to visit."""
    url = linkedin_auth.get_auth_url()
    return {"url": url}


@app.get("/api/linkedin/callback")
async def linkedin_auth_callback(code: str = "", state: str = ""):
    """Handle LinkedIn OAuth callback — exchange code for token, then redirect to app."""
    if not code or not state:
        return HTMLResponse("<h2>LinkedIn auth failed — missing code or state.</h2>", status_code=400)
    profile = await linkedin_auth.handle_callback(code, state)
    if not profile:
        return HTMLResponse("<h2>LinkedIn auth failed — invalid token.</h2>", status_code=401)
    # Redirect back to the main app with success indicator
    return HTMLResponse(
        '<html><head><meta http-equiv="refresh" content="0;url=/"></head>'
        '<body><p>LinkedIn connected! Redirecting...</p>'
        '<script>window.opener&&window.opener.postMessage({type:"linkedin_auth",ok:true},"*");'
        'setTimeout(()=>window.close(),500)</script></body></html>'
    )


@app.post("/api/enrich")
async def enrich_person_endpoint(body: dict):
    """Enrich a person's profile from LinkedIn + memory.

    Request: { "name": "Austin Omala", "linkedin_url": "..." (optional) }
    Response: { "info": PersonInfo | null, "linkedinAuth": bool }
    """
    name = body.get("name", "").strip()
    has_linkedin_auth = linkedin_auth.is_authenticated()

    if not name:
        return {"info": None, "linkedinAuth": has_linkedin_auth}

    # Look for a confirmed LinkedIn URL from stored data first
    linkedin_url = body.get("linkedin_url")

    # Check mem0 memories for a stored LinkedIn URL
    person_id = name.lower().replace(" ", "_")
    memories = memory_store.get_all_memories(person_id)
    for mem in (memories or []):
        meta = mem.get("metadata", {})
        if meta.get("type") == "linkedin" and meta.get("linkedin_url"):
            stored = meta["linkedin_url"]
            # Only trust stored URLs that point to a specific profile (/in/)
            if "/in/" in stored and not linkedin_url:
                linkedin_url = stored

    # Enrich — only passes linkedin_url if we have a confirmed one
    info: dict = {}
    try:
        enriched = await enrichment.enrich_person(name, linkedin_url)
        if enriched:
            info.update(enriched)
    except Exception as e:
        logger.warning(f"Enrichment failed for {name}: {e}")

    # Supplement with mem0 memories
    if memories:
        for mem in memories:
            content = mem.get("content", "")
            meta = mem.get("metadata", {})
            if meta.get("type") == "identity":
                if meta.get("company"):
                    info.setdefault("work", [])
                    if meta["company"] not in info["work"]:
                        info["work"].append(meta["company"])
                if meta.get("role"):
                    info["occupation"] = meta["role"]

    if not info:
        return {"info": None, "linkedinAuth": has_linkedin_auth}

    return {"info": info, "linkedinAuth": has_linkedin_auth}


@app.get("/api/recap")
async def get_recap():
    """Return session recap — all tracked people with confidence and topics.

    Response: RecapPerson[] = [{ name, confidence, topics, followUps }]
    """
    profiles = face_tracker.get_all_profiles()

    # Group by display name to deduplicate
    by_name: dict[str, dict] = {}
    for profile in profiles:
        pid = profile.get("person_id", "")
        display_name = profile.get("display_name") or memory_store.lookup_face_name(pid)
        if not display_name or display_name.startswith("unknown_"):
            continue

        trend = profile.get("confidence_trend", [])
        confidence = trend[-1] if trend else 0

        if display_name not in by_name or confidence > by_name[display_name]["confidence"]:
            by_name[display_name] = {"pid": pid, "confidence": confidence}

    recap = []
    for display_name, info in by_name.items():
        pid = info["pid"]
        memories = memory_store.get_all_memories(pid)

        topics = set()
        follow_ups = []
        for mem in memories:
            content = mem.get("content", "")
            meta = mem.get("metadata", {})
            if meta.get("topics"):
                topics.update(meta["topics"])
            if meta.get("type") == "linkedin":
                follow_ups.append(f"Connect on LinkedIn: {meta.get('linkedin_url', '')}")
            for keyword in ["AI", "ML", "startup", "investing", "engineering", "product", "design", "data", "cloud"]:
                if keyword.lower() in content.lower():
                    topics.add(keyword)

        recap.append({
            "name": display_name,
            "confidence": round(info["confidence"]),
            "topics": list(topics)[:5],
            "followUps": follow_ups[:3] if follow_ups else ["Follow up after event"],
        })

    return recap


# ─── Per-connection user session ───
_ws_sessions: dict[int, dict] = {}  # ws id → {user_id, ...}


def get_user_id(ws: WebSocket) -> str:
    """Get the user ID for this WebSocket connection."""
    session = _ws_sessions.get(id(ws), {})
    return session.get("user_id", "anonymous")


# ─── WebSocket Handler ───

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)
    _ws_sessions[id(ws)] = {"user_id": f"user_{id(ws) % 10000}"}
    logger.info(f"Client connected. Total: {len(active_connections)}")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "set_user":
                user_id = msg.get("user_id", "").strip()
                if user_id:
                    _ws_sessions[id(ws)]["user_id"] = user_id
                    logger.info(f"User identified as: {user_id}")
                    await emit(ws, "message", {"id": _next_msg_id(), "sender": "system", "text": f"Welcome, {user_id}!", "timestamp": time.time()})
            elif msg_type == "frame":
                await handle_frame(ws, msg)
            elif msg_type == "audio":
                await handle_audio(ws, msg)
            elif msg_type == "text":
                await handle_text(ws, msg)
            else:
                await emit(ws, "message", {"id": _next_msg_id(), "sender": "system", "text": f"Unknown type: {msg_type}", "timestamp": time.time()})

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if ws in active_connections:
            active_connections.remove(ws)
        _ws_sessions.pop(id(ws), None)
        _prev_face_ids.pop(id(ws), None)


async def handle_frame(ws: WebSocket, msg: dict):
    """Process a camera frame: detect faces → match → build context → respond."""
    global interaction_count, people_identified

    frame_b64 = msg.get("data", "")
    if not frame_b64:
        return

    image_bytes = base64.b64decode(frame_b64)
    frame_start = time.time()

    # Run face pipeline in thread pool (CPU-bound CLIP + network Rekognition)
    loop = asyncio.get_event_loop()
    face_results = await loop.run_in_executor(None, face_pipeline.process_frame, image_bytes)

    face_ms = (time.time() - frame_start) * 1000
    dd.gauge_pipeline_latency("face_pipeline", face_ms)

    if not face_results.get("faces"):
        # No faces — emit face_remove for any previously-tracked faces
        prev = _prev_face_ids.get(id(ws), set())
        for old_id in prev:
            await emit(ws, "face_remove", {"id": old_id})
        _prev_face_ids[id(ws)] = set()
        return

    # Process each detected face
    enriched_faces = []
    current_ids: set[str] = set()
    for face in face_results["faces"]:
        person_id = face["person_id"]
        confidence = face["confidence"]
        is_new = face["is_new"]
        current_ids.add(person_id)

        # Self-learning Loop 1: Record sighting
        display_name = memory_store.lookup_face_name(person_id)
        learning_result = face_tracker.record_sighting(
            person_id=person_id,
            confidence=confidence,
            clip_embedding=face.get("clip_embedding"),
            display_name=display_name,
        )

        # Trace face recognition
        dd.trace_face_recognition(person_id, confidence, is_new, face_ms)

        if is_new:
            people_identified += 1
            dd.increment_person_identified()

        # Get memory context for known faces
        memory_context = None
        memory_count = 0
        is_known = not is_new and bool(display_name) and not display_name.startswith("unknown_")
        if not is_new:
            await emit(ws, "memory", {"type": "searching", "personName": display_name or person_id})
            mem_start = time.time()
            memory_context = memory_store.get_person_context(person_id, user_id=get_user_id(ws))
            mem_ms = (time.time() - mem_start) * 1000
            dd.gauge_pipeline_latency("memory_retrieval", mem_ms)
            memory_count = memory_context.get("total_memories", 0)
            dd.trace_memory_retrieval(person_id, "face_context", memory_count, mem_ms)
            if memory_count > 0:
                await emit(ws, "memory", {"type": "found", "personName": display_name or person_id, "count": memory_count})

        bbox = face.get("bounding_box", {})
        # Emit individual face event ({type, data} wire format)
        await emit(ws, "face", {
            "id": person_id,
            "name": display_name if is_known else None,
            "confidence": round(learning_result["weighted_confidence"]),
            "bbox": {
                "x": round((bbox.get("Left", 0)) * 100, 1),
                "y": round((bbox.get("Top", 0)) * 100, 1),
                "width": round((bbox.get("Width", 0)) * 100, 1),
                "height": round((bbox.get("Height", 0)) * 100, 1),
            },
            "isKnown": is_known,
        })

        enriched_faces.append({
            "person_id": person_id,
            "display_name": display_name or person_id,
            "confidence": learning_result["weighted_confidence"],
            "bounding_box": face["bounding_box"],
            "is_new": is_new,
            "memory_count": memory_count,
        })

    # Emit face_remove for faces that left the frame
    prev = _prev_face_ids.get(id(ws), set())
    for old_id in prev:
        if old_id not in current_ids:
            await emit(ws, "face_remove", {"id": old_id})
    _prev_face_ids[id(ws)] = current_ids

    # Track last seen face for text handler association
    global _last_seen_face
    _last_seen_face = enriched_faces[0]["person_id"]

    # If we have a known face, generate agent response (with cooldown to save API quota)
    primary_face = enriched_faces[0]
    person_id = primary_face["person_id"]
    now = time.time()
    last_call = _last_agent_call.get(person_id, 0)
    has_identity = (primary_face["display_name"] and
                    not primary_face["display_name"].startswith("unknown_"))
    should_call_agent = (
        (has_identity or primary_face["memory_count"] > 0)
        and (now - last_call) > AGENT_COOLDOWN_SECS
    )

    if should_call_agent:
        _last_agent_call[person_id] = now
        memory_context = memory_store.get_person_context(person_id, user_id=get_user_id(ws))

        # Get routing corrections from self-learning Loop 3
        routing_corrections = intent_calibrator.get_corrections()

        context_prompt = agent.build_context_prompt(
            face_results={"faces": enriched_faces},
            memory_context=memory_context,
            routing_corrections=routing_corrections,
        )

        # Agent response
        agent_start = time.time()
        agent_result = await loop.run_in_executor(
            None, agent.respond, "I see someone", context_prompt, image_bytes
        )
        agent_ms = (time.time() - agent_start) * 1000
        dd.gauge_pipeline_latency("agent_response", agent_ms)

        # Self-learning Loop 3: Record routing decision
        intent_calibrator.record_decision(
            user_input="frame_detection",
            predicted_intent=agent_result["intent"],
            face_visible=True,
            had_memory=primary_face["memory_count"] > 0,
        )

        # Trace & log
        dd.trace_agent_response(agent_result["intent"], agent_ms, len(agent_result["text"]))
        dd.increment_interaction()
        interaction_count += 1
        dd.log_interaction(
            person_id, agent_result["intent"],
            primary_face["confidence"], primary_face["memory_count"],
            agent_result["text"],
        )

        # Send text response
        await emit(ws, "message", {
            "id": _next_msg_id(),
            "sender": "agent",
            "text": agent_result["text"],
            "timestamp": time.time(),
        })

        # Generate and send TTS
        if agent_result["text"]:
            try:
                tts_result = await loop.run_in_executor(None, tts.synthesize, agent_result["text"])
                dd.gauge_pipeline_latency("tts", tts_result.get("latency_ms", 0))
                dd.trace_tts(len(agent_result["text"]), tts_result.get("size_bytes", 0), tts_result.get("latency_ms", 0))
                if tts_result.get("audio_base64"):
                    await emit(ws, "audio", {
                        "base64": tts_result["audio_base64"],
                        "text": agent_result["text"],
                    })
            except Exception as e:
                logger.warning(f"TTS failed: {e}")

        # Send learning update if confidence improved
        if enriched_faces:
            face_profile = face_tracker.get_profile(primary_face["person_id"])
            if face_profile and len(face_profile.get("confidence_trend", [])) > 1:
                trend = face_profile["confidence_trend"]
                await emit(ws, "learning", {
                    "metric": "face_confidence",
                    "personName": primary_face["display_name"],
                    "old": round(trend[-2], 1) if len(trend) > 1 else 0,
                    "new": round(trend[-1], 1),
                })

    # Send status update
    await emit(ws, "status", {
        "peopleIdentified": people_identified,
        "interactions": interaction_count,
        "memoryItems": 0,
    })


async def handle_audio(ws: WebSocket, msg: dict):
    """Process an audio recording — transcribe with Gemini then handle as text."""
    audio_b64 = msg.get("data", "")
    if not audio_b64:
        return

    audio_bytes = base64.b64decode(audio_b64)
    mime_type = msg.get("mime_type", "audio/webm")
    loop = asyncio.get_event_loop()

    # Transcribe with Gemini
    try:
        result = await loop.run_in_executor(None, stt.transcribe, audio_bytes, mime_type)
        transcript = result.get("text", "").strip()
        dd.gauge_pipeline_latency("stt", result["latency_ms"])
    except Exception as e:
        logger.error(f"STT failed: {e}")
        await emit(ws, "message", {"id": _next_msg_id(), "sender": "system", "text": f"Transcription failed: {e}", "timestamp": time.time()})
        return

    if not transcript:
        await emit(ws, "message", {"id": _next_msg_id(), "sender": "agent", "text": "I didn't catch that. Try again?", "timestamp": time.time()})
        return

    # Send transcript back to client for display
    await emit(ws, "message", {"id": _next_msg_id(), "sender": "user", "text": transcript, "timestamp": time.time()})

    # Process as text message
    await handle_text(ws, {"message": transcript})


async def handle_text(ws: WebSocket, msg: dict):
    """Process a text message — intent route and respond."""
    global interaction_count

    user_text = msg.get("message", "").strip()
    if not user_text:
        return

    loop = asyncio.get_event_loop()

    # ─── SEARCH MODE: "search [name]" or "find [name]" or "lookup [name]" ───
    import re
    search_match = re.match(r'(?:search|find|lookup|look up|linkedin)\s+(.+)', user_text, re.IGNORECASE)
    if search_match:
        search_name = search_match.group(1).strip()
        logger.info(f"Search mode: looking up {search_name}")

        # Extract company if present
        company = None
        co_match = re.search(r'(?:at|from|@)\s+([A-Z][a-zA-Z\s&]+)', search_name)
        if co_match:
            company = co_match.group(1).strip()
            search_name = search_name[:co_match.start()].strip()

        try:
            linkedin_url = await loop.run_in_executor(
                None, memory_store.lookup_linkedin, search_name, company
            )
            response_text = f"Found LinkedIn for {search_name}: {linkedin_url}"
            await emit(ws, "message", {"id": _next_msg_id(), "sender": "agent", "text": response_text, "timestamp": time.time()})

            # Also store as memory if we have a face on camera
            if _last_seen_face:
                memory_store.store_linkedin(_last_seen_face, search_name, linkedin_url)
        except Exception as e:
            await emit(ws, "message", {"id": _next_msg_id(), "sender": "system", "text": f"Search failed: {e}", "timestamp": time.time()})

        dd.increment_interaction()
        interaction_count += 1
        return

    # ─── TAG MODE: "this is [name]" — tag the face currently on camera ───
    tag_match = re.match(
        r'(?:this is|that is|that\'s|it\'s|his name is|her name is|name is)\s+(.+)',
        user_text, re.IGNORECASE
    )
    if tag_match and _last_seen_face:
        tag_text = tag_match.group(1).strip()
        # Extract name (capitalized words)
        name_parts = re.findall(r'\b([A-Z][a-z]+)\b', tag_text)
        if name_parts:
            name = " ".join(name_parts[:3])  # Max 3-word name
            # Extract company
            company = None
            co_match = re.search(r'(?:at|from|works at|@)\s+([A-Z][a-zA-Z\s&]+)', tag_text, re.IGNORECASE)
            if co_match:
                company = co_match.group(1).strip()

            # Store identity
            face_tracker.confirm_identity(_last_seen_face, name)
            memory_store.update_identity_mapping(_last_seen_face, name)
            entities = {"name": name}
            if company:
                entities["company"] = company
            memory_store.store_identity(_last_seen_face, name, metadata=entities)
            memory_store.add_memory(_last_seen_face, user_text)

            # LinkedIn lookup
            try:
                linkedin_url = await loop.run_in_executor(
                    None, memory_store.lookup_linkedin, name, company
                )
                if linkedin_url:
                    memory_store.store_linkedin(_last_seen_face, name, linkedin_url)
                    await emit(ws, "message", {"id": _next_msg_id(), "sender": "agent", "text": f"Got it! Tagged as {name}. LinkedIn: {linkedin_url}", "timestamp": time.time()})
                else:
                    await emit(ws, "message", {"id": _next_msg_id(), "sender": "agent", "text": f"Got it! Tagged as {name}.", "timestamp": time.time()})
            except Exception as e:
                await emit(ws, "message", {"id": _next_msg_id(), "sender": "agent", "text": f"Tagged as {name}. LinkedIn lookup failed.", "timestamp": time.time()})
                logger.warning(f"LinkedIn lookup failed: {e}")

            logger.info(f"Tagged face {_last_seen_face} as {name}")
            dd.increment_interaction()
            interaction_count += 1
            return

    # ─── GENERAL MODE: agent-based routing for everything else ───
    active_person = None
    memory_context = None

    # Try to find person by name in text (for RECALL queries like "what did Austin say?")
    name_matches = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', user_text)
    for name_match in name_matches:
        person_id = name_match.lower().replace(" ", "_")
        memory_context = memory_store.get_person_context(person_id, current_query=user_text, user_id=get_user_id(ws))
        if memory_context and memory_context.get("total_memories", 0) > 0:
            active_person = person_id
            logger.info(f"Found person by name: {name_match} → {person_id}")
            break

    # Fall back to last seen face
    if not active_person and _last_seen_face:
        active_person = _last_seen_face
        memory_context = memory_store.get_person_context(active_person, current_query=user_text, user_id=get_user_id(ws))

    # Self-learning Loop 2: Evaluate retrieval quality
    if active_person and memory_context and memory_context.get("relevant_memories"):
        eval_result = retrieval_evaluator.evaluate_retrieval(
            person_id=active_person,
            query=user_text,
            results=memory_context["relevant_memories"],
            context=memory_context.get("summary", ""),
        )
        if eval_result.get("improved") and eval_result.get("improved_results"):
            memory_context["relevant_memories"] = eval_result["improved_results"]

    # Get routing corrections
    routing_corrections = intent_calibrator.get_corrections()

    context_prompt = agent.build_context_prompt(
        memory_context=memory_context,
        transcript=user_text,
        routing_corrections=routing_corrections,
    )

    # Agent response
    agent_result = await loop.run_in_executor(None, agent.respond, user_text, context_prompt)
    intent = agent_result["intent"]

    # Self-learning Loop 3: Record routing
    intent_calibrator.record_decision(
        user_input=user_text,
        predicted_intent=intent,
        face_visible=active_person is not None,
        had_memory=memory_context is not None and memory_context.get("total_memories", 0) > 0,
    )

    # Detect name corrections — force REMEMBER intent
    import re as _re
    correction_patterns = [
        r'(?:no|actually|correction|wrong|not .+,?\s*(?:it\'?s?|that\'?s?|name is|he\'?s?|she\'?s?))\s+(.+)',
        r'(?:his|her|their)\s+name\s+is\s+(.+)',
        r'(?:rename|correct|update|change)\s+(?:to|name to)\s+(.+)',
        r'(?:that\'?s?|it\'?s?|this is)\s+(.+)',
    ]
    for pattern in correction_patterns:
        match = _re.search(pattern, user_text, _re.IGNORECASE)
        if match and intent != "REMEMBER":
            # Extract the corrected name
            corrected = match.group(1).strip().rstrip('.')
            # Check if it looks like a name (has capital letters or multiple words)
            name_check = _re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', corrected)
            if name_check:
                intent = "REMEMBER"
                agent_result["entities"]["name"] = name_check[0]
                logger.info(f"Name correction detected: → {name_check[0]}")
                break

    # Handle REMEMBER intent — store new memory + LinkedIn lookup
    if intent == "REMEMBER" and active_person:
        entities = agent_result.get("entities", {})
        name = entities.get("name")

        # Fallback: extract name from user text if agent didn't
        if not name:
            import re
            name_matches = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', user_text)
            if name_matches:
                name = name_matches[0]
                logger.info(f"Extracted name from text: {name}")

        if name:
            # Generator-Verifier: confirm identity
            face_tracker.confirm_identity(active_person, name)
            memory_store.update_identity_mapping(active_person, name)
            memory_store.store_identity(active_person, name, metadata=entities)

            # LinkedIn lookup (async in thread pool) — works with or without company
            company = entities.get("company")
            # Try extracting company from user text if not in entities
            if not company:
                import re as _re
                # Match "at/from/works at [Company]"
                co_match = _re.search(r'(?:at|from|works at|@)\s+([A-Z][a-zA-Z\s&]+)', user_text)
                if co_match:
                    company = co_match.group(1).strip()
            try:
                linkedin_url = await loop.run_in_executor(
                    None, memory_store.lookup_linkedin, name, company
                )
                if linkedin_url:
                    memory_store.store_linkedin(active_person, name, linkedin_url)
                    await emit(ws, "message", {"id": _next_msg_id(), "sender": "agent", "text": f"Found {name}'s LinkedIn: {linkedin_url}", "timestamp": time.time()})
                    logger.info(f"Stored LinkedIn for {name}: {linkedin_url}")
            except Exception as e:
                logger.warning(f"LinkedIn lookup failed: {e}")

        # Store conversation content as PRIVATE memory (only this user sees it)
        user_id = get_user_id(ws)
        memory_store.add_private_memory(user_id, active_person, user_text)

    # Trace & count
    dd.trace_agent_response(intent, agent_result["latency_ms"], len(agent_result["text"]))
    dd.increment_interaction()
    interaction_count += 1

    if active_person:
        dd.log_interaction(
            active_person, intent,
            0, memory_context.get("total_memories", 0) if memory_context else 0,
            agent_result["text"],
        )

    # Send response
    await emit(ws, "message", {
        "id": _next_msg_id(),
        "sender": "agent",
        "text": agent_result["text"],
        "timestamp": time.time(),
    })

    # TTS
    if agent_result["text"]:
        try:
            tts_result = await loop.run_in_executor(None, tts.synthesize, agent_result["text"])
            dd.trace_tts(len(agent_result["text"]), tts_result.get("size_bytes", 0), tts_result.get("latency_ms", 0))
            if tts_result.get("audio_base64"):
                await emit(ws, "audio", {
                    "base64": tts_result["audio_base64"],
                    "text": agent_result["text"],
                })
        except Exception as e:
            logger.warning(f"TTS failed: {e}")

    # Status
    await emit(ws, "status", {
        "peopleIdentified": people_identified,
        "interactions": interaction_count,
        "memoryItems": memory_context.get("total_memories", 0) if memory_context else 0,
    })


# ─── Entry point ───

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
