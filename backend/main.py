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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")

import config
import face_pipeline
import memory_store
import agent
import tts
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ORBIT backend starting...")
    logger.info(f"Gemini model: {config.GEMINI_VISION_MODEL}")
    logger.info(f"Rekognition collection: {config.REKOGNITION_COLLECTION_ID}")
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


# ─── WebSocket Handler ───

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)
    logger.info(f"Client connected. Total: {len(active_connections)}")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "frame":
                await handle_frame(ws, msg)
            elif msg_type == "audio":
                await handle_audio(ws, msg)
            elif msg_type == "text":
                await handle_text(ws, msg)
            else:
                await ws.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if ws in active_connections:
            active_connections.remove(ws)


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
        # No faces — send empty result
        await ws.send_json({"type": "faces", "faces": []})
        return

    # Process each detected face
    enriched_faces = []
    for face in face_results["faces"]:
        person_id = face["person_id"]
        confidence = face["confidence"]
        is_new = face["is_new"]

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
        if not is_new:
            mem_start = time.time()
            memory_context = memory_store.get_person_context(person_id)
            mem_ms = (time.time() - mem_start) * 1000
            dd.gauge_pipeline_latency("memory_retrieval", mem_ms)
            memory_count = memory_context.get("total_memories", 0)
            dd.trace_memory_retrieval(person_id, "face_context", memory_count, mem_ms)

        enriched_faces.append({
            "person_id": person_id,
            "display_name": display_name or person_id,
            "confidence": learning_result["weighted_confidence"],
            "bounding_box": face["bounding_box"],
            "is_new": is_new,
            "memory_count": memory_count,
        })

    # Send face results
    await ws.send_json({"type": "faces", "faces": enriched_faces})

    # If we have a known face, generate agent response
    primary_face = enriched_faces[0]
    if not primary_face["is_new"] or primary_face["memory_count"] > 0:
        person_id = primary_face["person_id"]
        memory_context = memory_store.get_person_context(person_id)

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
        await ws.send_json({
            "type": "response",
            "text": agent_result["text"],
            "intent": agent_result["intent"],
        })

        # Generate and send TTS
        if agent_result["text"]:
            tts_start = time.time()
            tts_result = await loop.run_in_executor(None, tts.synthesize, agent_result["text"])
            tts_ms = (time.time() - tts_start) * 1000
            dd.gauge_pipeline_latency("tts", tts_ms)
            dd.trace_tts(len(agent_result["text"]), tts_result["size_bytes"], tts_ms)

            if tts_result["audio_base64"]:
                await ws.send_json({
                    "type": "audio",
                    "data": tts_result["audio_base64"],
                    "text": agent_result["text"],
                })

        # Send learning update if confidence improved
        if enriched_faces:
            face_profile = face_tracker.get_profile(primary_face["person_id"])
            if face_profile and len(face_profile.get("confidence_trend", [])) > 1:
                trend = face_profile["confidence_trend"]
                await ws.send_json({
                    "type": "learning",
                    "metric": "face_confidence",
                    "person_id": primary_face["person_id"],
                    "old_value": round(trend[-2], 1) if len(trend) > 1 else 0,
                    "new_value": round(trend[-1], 1),
                })

    # Send status update
    await ws.send_json({
        "type": "status",
        "people_identified": people_identified,
        "interactions": interaction_count,
        "memory_items": 0,  # Will be updated with actual count
    })


async def handle_audio(ws: WebSocket, msg: dict):
    """Process an audio chunk — transcribe and potentially trigger agent response."""
    # Audio is buffered and processed when combined with face context
    # In v1, we use text input as the primary voice interface
    # Gemini Live API integration would replace this
    pass


async def handle_text(ws: WebSocket, msg: dict):
    """Process a text message — intent route and respond."""
    global interaction_count

    user_text = msg.get("message", "").strip()
    if not user_text:
        return

    loop = asyncio.get_event_loop()

    # Check for active face context
    active_faces = face_tracker.get_all_profiles()
    active_person = None
    memory_context = None

    # Find most recent face
    for profile in active_faces:
        if profile and profile.get("sighting_count", 0) > 0:
            active_person = profile["person_id"]
            memory_context = memory_store.get_person_context(active_person, current_query=user_text)

            # Self-learning Loop 2: Evaluate retrieval quality
            if memory_context and memory_context.get("relevant_memories"):
                eval_result = retrieval_evaluator.evaluate_retrieval(
                    person_id=active_person,
                    query=user_text,
                    results=memory_context["relevant_memories"],
                    context=memory_context.get("summary", ""),
                )
                # Use improved results if available
                if eval_result.get("improved") and eval_result.get("improved_results"):
                    memory_context["relevant_memories"] = eval_result["improved_results"]
            break

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

    # Handle REMEMBER intent — store new memory
    if intent == "REMEMBER" and active_person:
        entities = agent_result.get("entities", {})
        name = entities.get("name")

        if name:
            # Generator-Verifier: confirm identity
            face_tracker.confirm_identity(active_person, name)
            memory_store.update_identity_mapping(active_person, name)
            memory_store.store_identity(active_person, name, metadata=entities)

        # Store conversation content as memory
        memory_store.add_memory(active_person, user_text)

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
    await ws.send_json({
        "type": "response",
        "text": agent_result["text"],
        "intent": intent,
    })

    # TTS
    if agent_result["text"]:
        tts_result = await loop.run_in_executor(None, tts.synthesize, agent_result["text"])
        dd.trace_tts(len(agent_result["text"]), tts_result["size_bytes"], tts_result["latency_ms"])

        if tts_result["audio_base64"]:
            await ws.send_json({
                "type": "audio",
                "data": tts_result["audio_base64"],
                "text": agent_result["text"],
            })

    # Status
    await ws.send_json({
        "type": "status",
        "people_identified": people_identified,
        "interactions": interaction_count,
        "memory_items": memory_context.get("total_memories", 0) if memory_context else 0,
    })


# ─── Entry point ───

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
