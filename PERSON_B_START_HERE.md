# Person B — Frontend & Integration

Welcome! This doc tells you everything you need to get started.

---

## Your Role

You own the **entire frontend** — React app, camera/audio capture, WebSocket communication, UI/UX, mobile optimization, and Docker orchestration.

Person A is building the backend (Python/FastAPI). You two communicate through **one WebSocket connection** with a fixed JSON protocol (see PLAN.md).

---

## First 10 Minutes After Cloning

```bash
# 1. Clone
git clone https://github.com/beee003/orbit.git
cd orbit

# 2. Scaffold the frontend
npm create vite@latest frontend -- --template react-ts
cd frontend

# 3. Install dependencies
npm install
npm install -D @types/node

# 4. Install project dependencies
npm install react-use clsx

# 5. Start dev server (accessible from phone)
npm run dev -- --host
```

---

## Your Files (you own all of these)

```
frontend/
├── src/
│   ├── App.tsx                         # Root layout: fullscreen camera + overlays
│   ├── components/
│   │   ├── CameraCapture.tsx           # <video> + canvas, extracts JPEG every 2s
│   │   ├── AudioRecorder.tsx           # MediaRecorder, streams PCM chunks
│   │   ├── PersonOverlay.tsx           # SVG/canvas overlay: bounding boxes + names
│   │   ├── ConversationPanel.tsx       # Bottom sheet with chat transcript
│   │   ├── MemoryIndicator.tsx         # "Remembering..." pulse pill
│   │   ├── StatusBar.tsx               # Top bar: connection, counts
│   │   └── RecapView.tsx              # Post-event summary screen
│   ├── hooks/
│   │   ├── useWebSocket.ts            # Connect, reconnect, dispatch messages
│   │   └── useMediaStream.ts          # Camera + mic permissions
│   └── styles/
│       └── globals.css                 # Dark theme, hot pink accents
├── public/
│   └── manifest.json                   # PWA manifest
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts

docker-compose.yml                      # At repo root — you create this
```

**Do NOT edit anything in `backend/`.** That's Person A's territory.

---

## Design Spec

| Property | Value |
|----------|-------|
| Background | `#0a0a0a` (near black) |
| Accent | `#ff3366` (hot pink) |
| Text | `#ffffff` primary, `#888888` secondary |
| Font | Inter (Google Fonts) |
| Overlay style | `backdrop-filter: blur(12px)`, semi-transparent panels |
| Unknown face box | Yellow (`#ffcc00`) border, dashed |
| Known face box | Green (`#00ff88`) border, solid |
| Animations | 200ms ease-out transitions, lerp face box positions |

### Layout (mobile portrait)
```
┌──────────────────────┐
│ StatusBar            │  ← fixed top, 40px
│ (green dot) 3 people │
├──────────────────────┤
│                      │
│   CAMERA FEED        │  ← full screen behind everything
│                      │
│  ┌────────┐          │
│  │ Sarah  │          │  ← PersonOverlay (absolute positioned)
│  │ 94%    │          │
│  └────────┘          │
│                      │
│                      │
├──────────────────────┤
│ ConversationPanel    │  ← bottom sheet, draggable
│ "That's Sarah from.."│
│ MemoryIndicator      │  ← inside panel
└──────────────────────┘
```

---

## WebSocket Protocol (your contract with Person A)

### You Send

```typescript
// Every 2 seconds — captured camera frame
ws.send(JSON.stringify({
  type: "frame",
  data: canvasToBase64JPEG(),      // base64 string, no data: prefix
  timestamp: Date.now()
}));

// Continuously while user speaks
ws.send(JSON.stringify({
  type: "audio",
  data: pcmChunkToBase64(),        // 16-bit PCM, base64
  sample_rate: 16000
}));

// Text fallback
ws.send(JSON.stringify({
  type: "text",
  message: "What did Sarah say?"
}));
```

### You Receive

```typescript
type ServerMessage =
  | { type: "faces"; faces: Face[] }
  | { type: "response"; text: string; intent: string }
  | { type: "audio"; data: string; text: string }       // base64 MP3
  | { type: "learning"; metric: string; person_id: string; old_value: number; new_value: number }
  | { type: "status"; people_identified: number; interactions: number; memory_items: number };

interface Face {
  person_id: string;
  display_name: string;
  confidence: number;
  bounding_box: { Left: number; Top: number; Width: number; Height: number };  // 0-1 ratios
  is_new: boolean;
  memory_count: number;
}
```

### Message handling map:
| Message type | What to do |
|-------------|------------|
| `faces` | Update PersonOverlay — draw boxes, show names + confidence |
| `response` | Append to ConversationPanel as agent bubble |
| `audio` | Decode base64 MP3 → AudioContext → play through speaker |
| `learning` | Show toast: "Sarah confidence: 72% → 94%" |
| `status` | Update StatusBar counters |

---

## Component Guide

### CameraCapture.tsx
- Use `navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false })`
- Render `<video>` element fullscreen, autoplay, playsInline
- Every 2 seconds: draw video frame to hidden `<canvas>`, call `canvas.toDataURL("image/jpeg", 0.7)`, strip the `data:image/jpeg;base64,` prefix, send via WebSocket
- Expose the video element ref so PersonOverlay can position boxes relative to it

### AudioRecorder.tsx
- Use `navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 16000, channelCount: 1 } })`
- Use `MediaRecorder` or `AudioWorkletNode` to capture PCM chunks
- Send each chunk via WebSocket as base64
- Show recording indicator (pulsing red dot)

### PersonOverlay.tsx
- Absolutely positioned over the camera feed
- Receives `faces[]` from parent
- For each face: draw a rectangle at `bounding_box` (multiply Left/Top/Width/Height by video dimensions)
- Yellow dashed border if `is_new`, green solid if known
- Label: `display_name` + `confidence%`
- Animate box positions (lerp between frames to avoid jumpiness)

### ConversationPanel.tsx
- Bottom sheet, starts collapsed (just a handle visible)
- Drag up to expand, shows conversation history
- Agent messages: dark bubble with hot pink left border
- User messages (from STT): lighter bubble, right-aligned
- Auto-scroll to bottom on new message

### MemoryIndicator.tsx
- Small pill inside ConversationPanel
- When agent accesses memory, shows "Remembering..." with pulse animation
- After retrieval: "Found 3 memories about Sarah"

### StatusBar.tsx
- Fixed at top, semi-transparent
- Left: green/red connection dot + "Connected"/"Reconnecting..."
- Right: "3 people | 12 interactions"
- Updates from `status` WebSocket messages

### RecapView.tsx (Hour 4)
- Full-screen overlay, accessed via button in StatusBar
- Lists: people met (with photos if available), key topics, suggested follow-ups
- Export as text/screenshot

---

## Testing on Phone

Camera requires HTTPS. Options:

1. **Same WiFi + Vite HTTPS plugin:**
   ```bash
   npm install -D @vitejs/plugin-basic-ssl
   ```
   Add to `vite.config.ts`, then open `https://<your-ip>:5173` on phone

2. **ngrok:**
   ```bash
   ngrok http 5173
   ```
   Open the ngrok URL on phone

3. **USB debugging:** Chrome DevTools → Remote devices → Port forward

---

## vite.config.ts Starter

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';

export default defineConfig({
  plugins: [react(), basicSsl()],
  server: {
    host: true,  // Listen on all interfaces (phone can connect)
    proxy: {
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
});
```

---

## Hour-by-Hour (your tasks only)

### Hour 1
- [ ] Scaffold React + Vite + TS
- [ ] `useMediaStream.ts` — camera + mic permissions
- [ ] `CameraCapture.tsx` — video + frame extraction
- [ ] `AudioRecorder.tsx` — mic recording
- [ ] `useWebSocket.ts` — connect + reconnect + dispatch
- [ ] `App.tsx` — fullscreen camera layout
- [ ] Test: camera works on phone, frames logged to console

### Hour 2
- [ ] `PersonOverlay.tsx` — bounding boxes + names
- [ ] `ConversationPanel.tsx` — bottom sheet transcript
- [ ] Wire all WebSocket message handlers
- [ ] Audio playback (TTS from backend)
- [ ] Dark theme + hot pink styling

### Hour 3
- [ ] `MemoryIndicator.tsx`
- [ ] `StatusBar.tsx`
- [ ] Mobile optimization (viewport, touch, orientation)
- [ ] Animations (box lerp, panel slide, toasts)
- [ ] Phone testing

### Hour 4
- [ ] `RecapView.tsx`
- [ ] Branding + polish
- [ ] `docker-compose.yml`
- [ ] PWA manifest + service worker
- [ ] Cross-browser testing
- [ ] Record backup video

### Hour 5
- [ ] Rehearsals with Person A
- [ ] Bug fixes
- [ ] Final run

---

## Questions? Sync Points?

Check with Person A at these moments:
1. **End of Hour 1** — send a test frame, verify backend receives it
2. **End of Hour 2** — full pipeline test: camera → face box → agent voice
3. **End of Hour 3** — self-learning toasts working, Datadog dashboard live
4. **End of Hour 4** — everything works, polish pass done

Good luck!
