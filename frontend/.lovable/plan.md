

# ORBIT Frontend — Implementation Plan

## Overview
Build the full ORBIT frontend: a mobile-first, dark-themed PWA that uses the real camera feed, overlays dummy face detections, shows a live conversation panel, and simulates the backend via timed fake WebSocket messages. All data is dummy for now; the real backend will be swapped in later.

## Design System
- **Background:** `#0a0a0a` (near black)
- **Accent:** `#ff3366` (hot pink)
- **Text:** `#ffffff` primary, `#888888` secondary
- **Font:** Inter (Google Fonts)
- **Panels:** `backdrop-filter: blur(12px)`, semi-transparent
- **Face boxes:** Yellow dashed = unknown, Green solid = known

---

## Phase 1: Camera + Core Layout

### Full-screen camera feed
- Request camera permission (rear-facing), display as full-screen `<video>` element
- Dark fallback screen if permission denied
- Mobile-optimized: `playsInline`, no controls, locked to portrait

### StatusBar (fixed top)
- Connection status dot (green/red) + "Connected" / "Offline"
- Counters: people identified, total interactions
- Semi-transparent with blur backdrop

### PersonOverlay (over camera feed)
- Renders bounding boxes over the camera feed
- Yellow dashed border for unknown faces, green solid for known
- Shows name + confidence percentage
- Smooth lerp animation between position updates

---

## Phase 2: Conversation + Memory

### ConversationPanel (bottom sheet)
- Draggable bottom sheet — collapsed by default, swipe up to expand
- Agent messages: dark bubbles with hot pink left border
- User messages: lighter bubbles, right-aligned
- Auto-scrolls to latest message

### MemoryIndicator
- Pill inside ConversationPanel that pulses when "memory is accessed"
- Shows "Remembering..." then "Found X memories about [Name]"

### Learning Toasts
- When a simulated learning event fires, show a toast: "Sarah confidence: 72% → 94%"

---

## Phase 3: Recap + Simulated Demo Loop

### RecapView
- Accessed via a button in the StatusBar
- Full-screen overlay listing: people met (with confidence), key topics discussed, suggested follow-ups
- Clean card-based layout

### Simulated backend (dummy data engine)
- A mock data service that fires timed events simulating the WebSocket protocol:
  1. **t=0s:** Status update (0 people)
  2. **t=3s:** Face detected — "Unknown" (yellow box, dashed)
  3. **t=6s:** Agent response: "I don't recognize this person yet..."
  4. **t=9s:** Face updated — "Alex Chen" (green box, 72% confidence)
  5. **t=12s:** Memory indicator pulses, conversation bubble appears
  6. **t=15s:** Learning event toast — confidence 72% → 94%
  7. Continues cycling with 2-3 preset "people" and conversations
- This mock service follows the exact WebSocket message protocol from PLAN.md so it can be swapped for the real WebSocket with minimal changes

---

## Phase 4: Polish & Mobile

- Smooth animations throughout (200ms ease-out transitions)
- Viewport meta tag, prevent pinch-zoom
- PWA manifest for "Add to Home Screen"
- Loading/error states (skeleton while camera initializes, error banner)
- ORBIT text-based branding/logo in StatusBar

