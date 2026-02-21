# ORBIT — Observability for Real-world Behavioral Intelligence & Tracking

> **"Datadog for humans — every person is a service, every conversation is a trace."**

A voice + vision AI agent with persistent memory for professional networking. Point your phone at someone, have a conversation, and ORBIT remembers everything — names, topics, context — and gets smarter with every interaction.

Built for the Datadog Hackathon 2026.

---

## Demo (4-5 min, 3 acts)

| Act | What Happens | Duration |
|-----|-------------|----------|
| **First Contact** | Point camera → yellow box "Unknown" → conversation reveals name → box turns green "Alex — Datadog APM — 72%" | 90s |
| **Self-Learning** | Walk away, come back → confidence jumps to 94% → voice query "what did Alex say?" → agent recalls via ElevenLabs → Datadog graphs trend up | 90s |
| **Datadog Wow** | Service map with people as nodes → self-learning metrics → click into a trace showing face→memory→reasoning→TTS spans | 60s |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        PHONE (React + Vite)                  │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Camera Feed │  │ Audio Stream │  │ Person Overlay +    │ │
│  │ (2s frames) │  │ (continuous) │  │ Conversation Panel  │ │
│  └──────┬──────┘  └──────┬───────┘  └─────────────────────┘ │
│         │                │                                    │
│         └────── WebSocket ──────┘                             │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    BACKEND (FastAPI)                          │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                   ORBIT AGENT                           │ │
│  │                                                         │ │
│  │  Intent Router (Gemini system prompt)                   │ │
│  │  → IDENTIFY / REMEMBER / RECALL / OBSERVE / CHITCHAT   │ │
│  │                    │                                    │ │
│  │  Tool Dispatcher                                        │ │
│  │  → face_lookup / memory_store / memory_query /          │ │
│  │    context_build / scene_describe / log_interaction     │ │
│  │                    │                                    │ │
│  │  Context Builder                                        │ │
│  │  → face match + past convos + relationship + scene      │ │
│  │                    │                                    │ │
│  │  Response → Gemini reasoning → ElevenLabs TTS           │ │
│  └────────────────────┼────────────────────────────────────┘ │
│                       │                                      │
│  ┌────────┐ ┌────────┐ ┌─────────┐ ┌───────┐ ┌───────────┐ │
│  │Rekog.  │ │ CLIP   │ │  mem0   │ │Eleven │ │ Datadog   │ │
│  │faces   │ │embeds  │ │+Pinecone│ │Labs   │ │APM+Metrics│ │
│  └────────┘ └────────┘ └─────────┘ └───────┘ └───────────┘ │
└──────────────────────────────────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │    Datadog      │
              │  Service Map    │
              │  Dashboard      │
              │  Lightdash      │
              └─────────────────┘
```

### Vision + Voice Pipeline

```
Phone Camera → every 2s extract frame
  ├→ Rekognition SearchFacesByImage → known? return name+confidence
  │                                 → unknown? IndexFaces + temp ID
  └→ CLIP encode cropped face → store in Pinecone → self-learning layer

Audio → continuous stream to Gemini Live API → real-time transcription + reasoning
     → ElevenLabs TTS → audio response back to phone
```

---

## Tech Stack

| Layer | Tool | Why |
|-------|------|-----|
| Camera + Voice | Gemini 2.5 Flash Live API | Native camera+voice over WebSocket, one connection |
| Face matching | AWS Rekognition | `IndexFaces` + `SearchFacesByImage`, production-grade |
| Face embeddings | CLIP ViT-L/14 (`open_clip`) | CPU, <100ms/frame, 768-dim, captures appearance beyond geometry |
| Scene understanding | Gemini 2.5 Flash | Already connected, send frames for context |
| Memory | mem0 + Pinecone | Structured per-person memory with vector search |
| TTS | ElevenLabs | Premium voice output |
| STT (backup) | Whisper local | Fallback if Gemini Live unavailable |
| Observability | Datadog APM + Logs + Metrics | Tracing, custom metrics, dashboards |
| Analytics | Lightdash | Post-event heatmaps (topics × people) |
| Backend | FastAPI + WebSockets | Real-time bidirectional comms |
| Frontend | React + Vite + TypeScript | Mobile-first PWA |

---

## Self-Learning — 3 Loops

### Loop 1: Face Confidence Bootstrapping (Generator-Verifier)
Unknown face → temp ID → conversation reveals name → agent **generates** identity → **verifies** ("Nice to meet you Sarah!") → confirmation → label face. CLIP embeddings averaged across sightings → improves re-identification.
- **Metric:** `orbit.face.confidence` trending UP per person

### Loop 2: Memory Retrieval Self-Improvement
After every RECALL, agent self-evaluates retrieval quality (1-10). If score < 7 → re-queries with improved search terms.
- **Metric:** `orbit.memory.retrieval_score` trending UP

### Loop 3: Intent Routing Calibration
Every 10 interactions → batch self-review of routing decisions. Corrections stored in mem0 system memory → injected into future routing context.
- **Metric:** `orbit.routing.accuracy` trending UP

**Judges see THREE live graphs all trending upward = "zero-label self-learning"**

---

## Datadog Integration

| Networking Concept | Datadog Concept |
|-------------------|-----------------|
| Each person | Service (`person_{id}`) |
| Each conversation | Trace |
| Each utterance | Span |
| Face recognition | External service span |
| Memory retrieval | Database span |

### Dashboard (4 panels)
1. **Service Map** — you at center, people as nodes, traces flowing between
2. **Self-Learning Metrics** — 3 lines trending up (face, memory, routing)
3. **Live Log Stream** — `Identified Sarah (98%) → Retrieved 3 memories → ...`
4. **Event Analytics** — people/hour, topic cloud, avg conversation duration

---

## Project Structure

```
orbit/
├── backend/
│   ├── main.py                 # FastAPI + WebSocket endpoints
│   ├── face_pipeline.py        # Rekognition + CLIP face processing
│   ├── memory_store.py         # mem0 wrapper with Pinecone backend
│   ├── agent.py                # Gemini intent router + tool dispatch
│   ├── self_learning.py        # 3 self-learning feedback loops
│   ├── tts.py                  # ElevenLabs text-to-speech
│   ├── datadog_integration.py  # Metrics, traces, dashboard setup
│   ├── config.py               # Keys + constants
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── CameraCapture.tsx    # Camera feed + frame extraction
│   │   │   ├── AudioRecorder.tsx    # Mic input + streaming
│   │   │   ├── PersonOverlay.tsx    # Bounding boxes + names on video
│   │   │   ├── ConversationPanel.tsx # Live transcript + responses
│   │   │   ├── MemoryIndicator.tsx  # Self-learning status display
│   │   │   ├── StatusBar.tsx        # Connection + system status
│   │   │   └── RecapView.tsx        # Post-event summary
│   │   └── hooks/
│   │       ├── useWebSocket.ts      # WebSocket connection manager
│   │       └── useMediaStream.ts    # Camera + mic access
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
├── seed_data.py                # Pre-seed demo contacts
├── .env.example
└── README.md
```

---

## Setup

```bash
# Backend
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env  # Fill in API keys
uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run dev

# With Docker
docker-compose up
```

### Required API Keys
```
GEMINI_API_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
PINECONE_API_KEY=
ELEVENLABS_API_KEY=
DD_API_KEY=
DD_APP_KEY=
MEM0_API_KEY=
```

---

## Team

Built by **Person A** (backend/AI) and **Person B** (frontend/integrations) at the Datadog Hackathon 2026.
