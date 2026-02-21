# ORBIT — Build Plan & Task Division

## Team Split

### Person A — Backend & AI/ML
**Focus:** Face pipeline, agent brain, self-learning, Datadog instrumentation.

### Person B — Frontend & Integration
**Focus:** React app, camera/audio, WebSocket plumbing, UI/UX, demo polish.

---

## Hour-by-Hour Plan

### Hour 1: Foundation (0:00 – 1:00)

#### Person A (Backend + AI/ML)
- [ ] Set up FastAPI scaffold with WebSocket endpoint (`main.py`)
- [ ] Configure Docker + docker-compose with Datadog agent sidecar
- [ ] Create AWS Rekognition face collection, test `IndexFaces` / `SearchFacesByImage`
- [ ] Test CLIP embedding generation on sample images
- [ ] Wire up mem0 + Pinecone (create index, test store/retrieve)
- [ ] Write `config.py` with all env vars
- [ ] Write `face_pipeline.py` — detect, search, index, crop, CLIP embed

#### Person B (Frontend + Integration)
- [ ] Scaffold React + Vite + TypeScript project
- [ ] Build `CameraCapture.tsx` — getUserMedia, canvas frame extraction every 2s
- [ ] Build `AudioRecorder.tsx` — MediaRecorder, chunked audio capture
- [ ] Build `useWebSocket.ts` hook — connect, reconnect, binary message handling
- [ ] Build `useMediaStream.ts` hook — camera + mic permissions, stream management
- [ ] Basic layout: camera feed full-screen, overlay layer on top
- [ ] Test: camera works on phone browser, frames being extracted

**Sync point:** WebSocket message format agreed (JSON for control, binary for audio/frames)

---

### Hour 2: Core Pipeline (1:00 – 2:00)

#### Person A (Backend + AI/ML)
- [ ] Write `memory_store.py` — mem0 wrapper (add_memory, search, get_person_context)
- [ ] Write `agent.py` — Gemini system prompt with intent router, tool dispatch
- [ ] Wire full pipeline: frame → face_pipeline → memory_store → agent → response
- [ ] Write `tts.py` — ElevenLabs streaming TTS
- [ ] Write `datadog_integration.py` — trace decorator, custom metrics stubs
- [ ] Add ddtrace instrumentation to FastAPI + all tool calls
- [ ] Test: send frame via WebSocket → get face result + agent response back

#### Person B (Frontend + Integration)
- [ ] Build `PersonOverlay.tsx` — render bounding boxes + names over camera feed
- [ ] Build `ConversationPanel.tsx` — sliding panel with live transcript
- [ ] Handle WebSocket messages: face results → overlay, text → panel, audio → playback
- [ ] Audio playback pipeline: receive TTS chunks → AudioContext → speaker
- [ ] Style: dark theme, hot pink (#ff3366) accents, frosted glass overlays
- [ ] Test: mock face data renders correctly on overlay

**Sync point:** End-to-end test — point camera → see face box → hear response

---

### Hour 3: Self-Learning + Datadog (2:00 – 3:00)

#### Person A (Backend + AI/ML)
- [ ] Write `self_learning.py` — all 3 loops:
  - Loop 1: Face confidence tracker + CLIP embedding accumulator
  - Loop 2: Memory retrieval self-evaluator
  - Loop 3: Intent routing calibrator (batch review every 10 interactions)
- [ ] Wire Datadog custom metrics:
  - `orbit.face.confidence` (gauge, per person)
  - `orbit.memory.retrieval_score` (gauge)
  - `orbit.routing.accuracy` (gauge)
  - `orbit.interactions.count` (counter)
  - `orbit.people.identified` (counter)
- [ ] Create Datadog dashboard (4 panels: service map, self-learning, logs, analytics)
- [ ] Test self-learning: face confidence increases on re-encounter

#### Person B (Frontend + Integration)
- [ ] Build `MemoryIndicator.tsx` — show memory retrieval happening (pulse animation)
- [ ] Build `StatusBar.tsx` — connection status, face count, interaction count
- [ ] Mobile optimization: viewport meta, touch handling, orientation lock
- [ ] Add visual feedback: box color transitions (yellow→green), confidence %
- [ ] Smooth animations: face box tracking, panel slide-in, status transitions
- [ ] Test on actual phone via ngrok/local network

**Sync point:** Self-learning metrics visible in Datadog, UI responsive on phone

---

### Hour 4: Integration + Polish (3:00 – 4:00)

#### Person A (Backend + AI/ML)
- [ ] Write `seed_data.py` — pre-seed 3-5 demo contacts with faces + memories
- [ ] Lightdash export — topics × people heatmap data
- [ ] Error handling: graceful degradation if any service is down
- [ ] Stress test face recognition pipeline (multiple faces, varied angles)
- [ ] End-to-end test: full conversation flow with all 3 self-learning loops firing
- [ ] Performance optimization: ensure <500ms face pipeline response

#### Person B (Frontend + Integration)
- [ ] Build `RecapView.tsx` — post-event summary (people met, topics, follow-ups)
- [ ] Branding: ORBIT logo, consistent typography (Inter), spacing
- [ ] Transitions: smooth state changes, loading states, error states
- [ ] PWA setup: manifest.json, service worker for offline resilience
- [ ] Cross-browser test (Safari iOS + Chrome Android)
- [ ] Screenshot/record demo flow for backup

**Sync point:** Full flow works end-to-end, no crashes, looks polished

---

### Hour 5: Demo Prep (4:00 – 5:00)

#### Both Together
- [ ] **Rehearsal 1** — full demo, note all issues
- [ ] Fix any bugs found in rehearsal 1
- [ ] **Rehearsal 2** — full demo with timing (target 4-5 min)
- [ ] Adjust pacing, cut/add content as needed
- [ ] **Rehearsal 3** — final run, no stops
- [ ] Prepare backup plan (pre-recorded video of key moments)
- [ ] Ensure Datadog dashboard is open and showing live data
- [ ] Final check: phone charged, WiFi stable, all services running

---

## WebSocket Message Protocol

### Client → Server
```json
// Video frame (every 2s)
{
  "type": "frame",
  "data": "<base64 JPEG>",
  "timestamp": 1708000000000
}

// Audio chunk (continuous)
{
  "type": "audio",
  "data": "<base64 PCM>",
  "sample_rate": 16000
}

// Text input (fallback)
{
  "type": "text",
  "message": "What did Sarah say about AI?"
}
```

### Server → Client
```json
// Face detection result
{
  "type": "faces",
  "faces": [
    {
      "person_id": "sarah_chen",
      "display_name": "Sarah Chen",
      "confidence": 94.2,
      "bounding_box": {"Left": 0.3, "Top": 0.2, "Width": 0.15, "Height": 0.2},
      "is_new": false,
      "memory_count": 5
    }
  ]
}

// Agent text response
{
  "type": "response",
  "text": "That's Sarah Chen from Datadog. Last time you spoke about APM best practices.",
  "intent": "IDENTIFY"
}

// Agent audio response (TTS)
{
  "type": "audio",
  "data": "<base64 MP3>",
  "text": "That's Sarah Chen..."
}

// Self-learning update
{
  "type": "learning",
  "metric": "face_confidence",
  "person_id": "sarah_chen",
  "old_value": 72.1,
  "new_value": 94.2
}

// Status update
{
  "type": "status",
  "people_identified": 5,
  "interactions": 23,
  "memory_items": 47
}
```

---

## Key Decisions
- **Single agent, not multi-agent** — intent router via system prompt, zero overhead
- **Gemini for everything** — voice, vision, reasoning (one API, one connection)
- **Rekognition over face_recognition** — no dlib compilation, single API call
- **mem0 over raw Pinecone** — structured memory with automatic summarization
- **ElevenLabs over Gemini TTS** — noticeably better voice quality for demo
- **No LangChain** — unnecessary abstraction for a single-agent system
