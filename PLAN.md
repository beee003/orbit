# ORBIT — Build Plan & Task Division

## Team Roles

| | Person A | Person B |
|--|---------|---------|
| **Focus** | Backend, AI/ML, Datadog | Frontend, integration, UI/UX |
| **Works in** | `backend/` + root scripts | `frontend/` + `docker-compose.yml` |
| **Language** | Python | TypeScript / React |
| **Runs** | `uvicorn main:app` | `npm run dev` |

---

## File Ownership

Every file has exactly one owner. **Only touch your own files.** Coordinate at sync points.

### Person A — owns these files

```
backend/
├── main.py                 # FastAPI app + WebSocket endpoint
├── face_pipeline.py        # Rekognition + CLIP face processing
├── memory_store.py         # mem0 wrapper with Pinecone backend
├── agent.py                # Gemini intent router + tool dispatch
├── self_learning.py        # 3 self-learning feedback loops
├── tts.py                  # ElevenLabs text-to-speech
├── datadog_integration.py  # Metrics, traces, dashboard config
├── config.py               # All env var loading + constants
└── requirements.txt        # Python dependencies

seed_data.py                # Pre-seed demo contacts for demo
.env.example                # Template for API keys
```

### Person B — owns these files

```
frontend/
├── src/
│   ├── App.tsx                        # Root app, layout, routing
│   ├── components/
│   │   ├── CameraCapture.tsx          # Camera feed + frame extraction every 2s
│   │   ├── AudioRecorder.tsx          # Mic input + chunked audio streaming
│   │   ├── PersonOverlay.tsx          # Bounding boxes + names drawn over video
│   │   ├── ConversationPanel.tsx      # Sliding panel with live transcript
│   │   ├── MemoryIndicator.tsx        # Pulse animation when memory is accessed
│   │   ├── StatusBar.tsx              # Connection status, face count, interaction count
│   │   └── RecapView.tsx              # Post-event summary screen
│   └── hooks/
│       ├── useWebSocket.ts            # WebSocket connection manager + reconnect
│       └── useMediaStream.ts          # Camera + mic permissions + stream lifecycle
├── public/
│   └── manifest.json                  # PWA manifest
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts

docker-compose.yml                     # Orchestrates backend + frontend + Datadog agent
```

### Shared (both edit carefully)

```
README.md          # Project documentation
PLAN.md            # This file — update checkboxes as you go
.env.example       # Person A adds backend keys, Person B adds frontend keys
```

---

## Hour-by-Hour Plan

### Hour 1: Foundation (0:00 – 1:00)

#### Person A
- [ ] `config.py` — all env vars with defaults *(DONE)*
- [ ] `requirements.txt` — pin all deps *(DONE)*
- [ ] `face_pipeline.py` — detect, search, index, crop, CLIP embed *(DONE)*
- [ ] `main.py` — FastAPI scaffold with `/ws` WebSocket endpoint, health check
- [ ] Create AWS Rekognition collection, verify `IndexFaces` / `SearchFacesByImage` work
- [ ] Test CLIP embedding on a sample image
- [ ] `memory_store.py` — create Pinecone index, wire mem0, test store/retrieve

#### Person B
- [ ] `npm create vite@latest frontend -- --template react-ts`
- [ ] `package.json` — add dependencies (see Person B Setup below)
- [ ] `vite.config.ts` — proxy `/ws` to backend, HTTPS for camera access
- [ ] `useMediaStream.ts` — getUserMedia for camera + mic, cleanup
- [ ] `CameraCapture.tsx` — video element + canvas, extract JPEG frame every 2s
- [ ] `AudioRecorder.tsx` — MediaRecorder, emit PCM chunks
- [ ] `useWebSocket.ts` — connect to `ws://localhost:8000/ws`, auto-reconnect, message dispatch
- [ ] `App.tsx` — full-screen camera with overlay layer on top
- [ ] Test: camera works on phone browser, frames logged to console

**Sync point:** Agree on WebSocket message format (see Protocol section below). Test: frontend sends a frame, backend receives it.

---

### Hour 2: Core Pipeline (1:00 – 2:00)

#### Person A
- [ ] `agent.py` — Gemini system prompt with intent router (IDENTIFY/REMEMBER/RECALL/OBSERVE/CHITCHAT), tool dispatch
- [ ] `tts.py` — ElevenLabs streaming TTS, return base64 MP3
- [ ] `datadog_integration.py` — `@traced` decorator, span creation, log helper
- [ ] Wire full pipeline in `main.py`: frame → `face_pipeline.process_frame()` → `memory_store.get_context()` → `agent.respond()` → `tts.synthesize()` → WebSocket response
- [ ] Add ddtrace auto-instrumentation to FastAPI
- [ ] Test: send frame via WebSocket → get `faces` + `response` + `audio` messages back

#### Person B
- [ ] `PersonOverlay.tsx` — render bounding boxes + name labels + confidence % on top of video feed. Yellow box = new face, green = known. Animate color transition.
- [ ] `ConversationPanel.tsx` — bottom sheet / sliding panel, shows live transcript. Agent text appears as chat bubbles.
- [ ] Wire WebSocket message handler in `App.tsx`: `faces` → PersonOverlay, `response` → ConversationPanel, `audio` → AudioContext playback
- [ ] Audio playback: decode base64 MP3 → AudioContext → play through speaker
- [ ] Style everything: dark background (#0a0a0a), hot pink accents (#ff3366), Inter font, frosted glass (backdrop-filter: blur)
- [ ] Test with mock data: paste fake `faces` JSON → verify overlay renders

**Sync point:** End-to-end test — point camera at a face → see bounding box → hear agent response through speaker.

---

### Hour 3: Self-Learning + Datadog (2:00 – 3:00)

#### Person A
- [ ] `self_learning.py`:
  - `FaceConfidenceTracker` — accumulate CLIP embeddings per person, average on re-encounter, emit `orbit.face.confidence` gauge
  - `MemoryRetrievalEvaluator` — after each RECALL, self-score 1-10, re-query if < 7, emit `orbit.memory.retrieval_score` gauge
  - `IntentCalibrator` — every 10 interactions, batch review routing decisions, store corrections in mem0, emit `orbit.routing.accuracy` gauge
- [ ] Wire self-learning into `main.py` interaction loop
- [ ] Datadog custom metrics: `orbit.face.confidence`, `orbit.memory.retrieval_score`, `orbit.routing.accuracy`, `orbit.interactions.count`, `orbit.people.identified`
- [ ] Create Datadog dashboard JSON (4 panels)
- [ ] Test: re-encounter same face → confidence metric increases

#### Person B
- [ ] `MemoryIndicator.tsx` — small pill that pulses when memory is being accessed. Shows "Remembering..." or "3 memories found"
- [ ] `StatusBar.tsx` — top bar: connection dot (green/red), people count, interaction count, uptime
- [ ] Handle `learning` WebSocket message — show toast: "Confidence for Sarah: 72% → 94%"
- [ ] Handle `status` WebSocket message — update StatusBar counters
- [ ] Mobile optimization: `<meta name="viewport">`, touch events, prevent pinch-zoom, lock to portrait
- [ ] Smooth animations: face boxes lerp to new positions, panel slides in/out, status bar fades
- [ ] Test on actual phone (connect phone to same WiFi, open `https://<local-ip>:5173`)

**Sync point:** Self-learning metrics show up in Datadog dashboard. UI is responsive on phone.

---

### Hour 4: Integration + Polish (3:00 – 4:00)

#### Person A
- [ ] `seed_data.py` — pre-index 3-5 faces into Rekognition, pre-load memories into mem0 (gives demo a head start)
- [ ] Lightdash export: write interaction data to CSV/JSON that Lightdash can ingest (topics × people heatmap)
- [ ] Error handling: if Rekognition/Gemini/ElevenLabs down → graceful fallback (text-only, skip face, etc.)
- [ ] Stress test: multiple faces in frame, varied angles, lighting changes
- [ ] Performance: face pipeline < 500ms, agent response < 2s end-to-end
- [ ] `docker-compose.yml` — review Person B's compose, add Datadog agent sidecar config

#### Person B
- [ ] `RecapView.tsx` — swipe-to view after event. Lists: people met (with confidence), topics discussed, suggested follow-ups
- [ ] Branding: ORBIT logo (text-based is fine), consistent spacing, Inter font loaded from Google Fonts
- [ ] Loading/error states: skeleton screens while connecting, error banner if WebSocket drops
- [ ] `docker-compose.yml` — backend + frontend + Datadog agent services
- [ ] PWA: `manifest.json`, register service worker, "Add to Home Screen" works on iOS/Android
- [ ] Cross-browser test: Safari iOS + Chrome Android
- [ ] Record screen capture of working demo as backup

**Sync point:** Full end-to-end flow works. No crashes. Looks polished on phone.

---

### Hour 5: Demo Prep (4:00 – 5:00)

#### Both Together
- [ ] **Rehearsal 1** — full 5-min demo, write down every issue
- [ ] Fix bugs from rehearsal 1
- [ ] **Rehearsal 2** — full demo with stopwatch (target: 4-5 min)
- [ ] Adjust pacing, cut anything that's flaky
- [ ] **Rehearsal 3** — final clean run, no stops
- [ ] Backup plan: pre-recorded video of each act in case of live failure
- [ ] Datadog dashboard open on laptop, phone ready on charger
- [ ] WiFi tested, all services green, `.env` keys verified

---

## WebSocket Message Protocol

This is the contract between Person A (backend) and Person B (frontend). **Do not change without syncing.**

### Client → Server (Person B sends these)

```json
// Video frame — send every 2 seconds
{
  "type": "frame",
  "data": "<base64-encoded JPEG>",
  "timestamp": 1708000000000
}

// Audio chunk — send continuously while recording
{
  "type": "audio",
  "data": "<base64-encoded PCM 16-bit>",
  "sample_rate": 16000
}

// Text input — fallback if voice isn't working
{
  "type": "text",
  "message": "What did Sarah say about AI?"
}
```

### Server → Client (Person A sends these)

```json
// Face detection results — sent after processing each frame
{
  "type": "faces",
  "faces": [
    {
      "person_id": "sarah_chen",
      "display_name": "Sarah Chen",
      "confidence": 94.2,
      "bounding_box": { "Left": 0.3, "Top": 0.2, "Width": 0.15, "Height": 0.2 },
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
  "data": "<base64-encoded MP3>",
  "text": "That's Sarah Chen..."
}

// Self-learning update — show as toast notification
{
  "type": "learning",
  "metric": "face_confidence",
  "person_id": "sarah_chen",
  "old_value": 72.1,
  "new_value": 94.2
}

// Status counters — update StatusBar
{
  "type": "status",
  "people_identified": 5,
  "interactions": 23,
  "memory_items": 47
}
```

---

## Quick Reference

| What | Command |
|------|---------|
| Start backend | `cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload` |
| Start frontend | `cd frontend && npm run dev -- --host` |
| Start everything | `docker-compose up` |
| Run on phone | Open `https://<your-local-ip>:5173` on phone (same WiFi) |
| Seed demo data | `python3 seed_data.py` |
| View Datadog | `https://app.datadoghq.com` |
