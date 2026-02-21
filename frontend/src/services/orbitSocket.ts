import type { SimEvent, RecapPerson } from "@/types/orbit";

type EventHandler = (event: SimEvent) => void;
type AudioHandler = (base64: string) => void;

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];

/**
 * OrbitSocket — WebSocket client with adapter layer.
 *
 * Translates the ORBIT backend's flat message format into the frontend's
 * typed SimEvent format so the React components receive a clean contract.
 */
export class OrbitSocket {
  private ws: WebSocket | null = null;
  private handler: EventHandler | null = null;
  private url: string;
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private prevFaceIds = new Set<string>();
  private msgCounter = 0;

  /** Set this to receive raw base64 MP3 for TTS playback. */
  public onAudio: AudioHandler | null = null;

  constructor(url?: string) {
    if (url) {
      this.url = url;
    } else if (import.meta.env.VITE_WS_URL) {
      this.url = import.meta.env.VITE_WS_URL;
    } else {
      // Auto-detect from page URL (works when served by backend or ngrok)
      this.url =
        location.protocol === "https:"
          ? `wss://${location.host}/ws`
          : `ws://${location.hostname}:8000/ws`;
    }
  }

  start(handler: EventHandler) {
    this.handler = handler;
    this.stopped = false;
    this.connect();
  }

  private connect() {
    if (this.stopped) return;

    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      this.attempt = 0;
      this.handler?.({
        type: "status",
        data: { connected: true, peopleIdentified: 0, totalInteractions: 0 },
      });
    };

    this.ws.onmessage = (msg) => {
      try {
        const raw = JSON.parse(msg.data);
        const events = this.translateBackendEvent(raw);
        for (const event of events) {
          this.handler?.(event);
        }
      } catch {
        console.error("OrbitSocket: failed to parse message", msg.data);
      }
    };

    this.ws.onclose = () => {
      this.handler?.({
        type: "status",
        data: { connected: false, peopleIdentified: 0, totalInteractions: 0 },
      });
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  // ─── Backend → SimEvent Adapter ───
  //
  // Backend now sends {type, data} events. We normalize field names
  // so React components get a clean contract.

  private translateBackendEvent(raw: any): SimEvent[] {
    const events: SimEvent[] = [];
    const d = raw.data ?? {};

    switch (raw.type) {
      // {type:"face", data:{id, name, confidence, bbox, isKnown}}
      case "face": {
        this.prevFaceIds.add(d.id);
        events.push({ type: "face", data: d });
        break;
      }

      // {type:"face_remove", data:{id}}
      case "face_remove": {
        this.prevFaceIds.delete(d.id);
        events.push({ type: "face_remove", data: d });
        break;
      }

      // {type:"message", data:{id, sender, text, timestamp}}
      case "message": {
        events.push({
          type: "message",
          data: {
            id: d.id || `msg_${++this.msgCounter}`,
            role: d.sender || "agent",
            content: d.text || "",
            timestamp: d.timestamp ? d.timestamp * 1000 : Date.now(),
          },
        });
        break;
      }

      // {type:"memory", data:{type:"searching"|"found", personName, count?}}
      case "memory": {
        events.push({ type: "memory", data: d });
        break;
      }

      // {type:"learning", data:{metric, personName, old, new}}
      case "learning": {
        events.push({
          type: "learning",
          data: {
            personName: d.personName || "Unknown",
            oldConfidence: Math.round(d.old ?? 0),
            newConfidence: Math.round(d.new ?? 0),
          },
        });
        break;
      }

      // {type:"status", data:{peopleIdentified, interactions, memoryItems}}
      case "status": {
        events.push({
          type: "status",
          data: {
            connected: true,
            peopleIdentified: d.peopleIdentified ?? 0,
            totalInteractions: d.interactions ?? 0,
          },
        });
        break;
      }

      // {type:"audio", data:{base64, text}}
      case "audio": {
        this.onAudio?.(d.base64 || d.data);
        break;
      }

      // Legacy flat formats (backwards compat with test_camera.html)
      case "faces":
      case "response":
      case "transcript":
      case "error": {
        events.push(...this.translateLegacy(raw));
        break;
      }

      default: {
        if (d && typeof raw.type === "string") {
          events.push(raw as SimEvent);
        }
      }
    }

    return events;
  }

  /** Translate legacy flat messages (backwards compat). */
  private translateLegacy(raw: any): SimEvent[] {
    const events: SimEvent[] = [];
    switch (raw.type) {
      case "faces": {
        const currentIds = new Set<string>();
        for (const f of raw.faces || []) {
          const id: string = f.person_id || f.id;
          currentIds.add(id);
          const displayName = f.display_name || f.name;
          const isKnown = !f.is_new && !!displayName && !displayName.startsWith("unknown_");
          events.push({
            type: "face",
            data: {
              id,
              name: isKnown ? displayName : null,
              confidence: Math.round(f.confidence ?? 0),
              bbox: {
                x: (f.bounding_box?.Left ?? 0) * 100,
                y: (f.bounding_box?.Top ?? 0) * 100,
                width: (f.bounding_box?.Width ?? 0) * 100,
                height: (f.bounding_box?.Height ?? 0) * 100,
              },
              isKnown,
            },
          });
        }
        for (const oldId of this.prevFaceIds) {
          if (!currentIds.has(oldId)) events.push({ type: "face_remove", data: { id: oldId } });
        }
        this.prevFaceIds = currentIds;
        break;
      }
      case "response":
        events.push({ type: "message", data: { id: `msg_${++this.msgCounter}`, role: "agent", content: raw.text || "", timestamp: Date.now() } });
        break;
      case "transcript":
        events.push({ type: "message", data: { id: `msg_${++this.msgCounter}`, role: "user", content: raw.text || "", timestamp: Date.now() } });
        break;
      case "error":
        events.push({ type: "message", data: { id: `msg_${++this.msgCounter}`, role: "agent", content: `Error: ${raw.message}`, timestamp: Date.now() } });
        break;
    }
    return events;
  }

  // ─── Reconnect ───

  private scheduleReconnect() {
    if (this.stopped) return;
    const delay =
      RECONNECT_DELAYS[Math.min(this.attempt, RECONNECT_DELAYS.length - 1)];
    this.attempt++;
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  stop() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
    this.handler = null;
    this.onAudio = null;
  }

  send(payload: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  async getRecapData(): Promise<RecapPerson[]> {
    const base = this.url.replace(/^ws/, "http").replace(/\/ws$/, "");
    try {
      const res = await fetch(`${base}/api/recap`);
      if (!res.ok) return [];
      return (await res.json()) as RecapPerson[];
    } catch {
      return [];
    }
  }
}
