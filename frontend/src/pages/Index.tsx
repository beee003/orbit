import { useEffect, useRef, useState, useCallback } from 'react';
import { toast } from 'sonner';
import CameraFeed from '@/components/orbit/CameraFeed';
import PersonOverlay from '@/components/orbit/PersonOverlay';
import StatusBar from '@/components/orbit/StatusBar';
import ConversationPanel from '@/components/orbit/ConversationPanel';
import RecapView from '@/components/orbit/RecapView';
import { OrbitSocket } from '@/services/orbitSocket';
import type { DetectedFace, ConversationMessage, MemoryEvent, StatusUpdate, RecapPerson, SimEvent } from '@/types/orbit';
import { enrichPersonByName } from '@/services/enrichment';

const Index = () => {
  const socketRef = useRef<OrbitSocket | null>(null);
  const enrichmentRequestedRef = useRef<Map<string, string>>(new Map());
  const audioCtxRef = useRef<AudioContext | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioStreamRef = useRef<MediaStream | null>(null);

  const [faces, setFaces] = useState<DetectedFace[]>([]);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [memoryEvent, setMemoryEvent] = useState<MemoryEvent | null>(null);
  const [status, setStatus] = useState<StatusUpdate>({ connected: false, peopleIdentified: 0, totalInteractions: 0 });
  const [showRecap, setShowRecap] = useState(false);
  const [recapData, setRecapData] = useState<RecapPerson[]>([]);
  const [isRecording, setIsRecording] = useState(false);

  // ─── Audio Playback (TTS from backend) ───

  const playAudio = useCallback(async (base64Mp3: string) => {
    try {
      if (!audioCtxRef.current) audioCtxRef.current = new AudioContext();
      const ctx = audioCtxRef.current;
      if (ctx.state === 'suspended') await ctx.resume();
      const bytes = Uint8Array.from(atob(base64Mp3), c => c.charCodeAt(0));
      const buffer = await ctx.decodeAudioData(bytes.buffer);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.start();
    } catch (err) {
      console.error('Audio playback failed:', err);
    }
  }, []);

  // ─── Event Handler (SimEvents from OrbitSocket) ───

  const handleEvent = useCallback((event: SimEvent) => {
    switch (event.type) {
      case 'status':
        setStatus(event.data);
        break;
      case 'face':
        setFaces(prev => {
          const idx = prev.findIndex(f => f.id === event.data.id);
          if (idx >= 0) {
            // Update existing face — keep enrichment info if already loaded
            const next = [...prev];
            next[idx] = {
              ...event.data,
              info: event.data.info ?? prev[idx].info,
            };
            return next;
          }
          // New face appeared — clear all OTHER faces' info so the
          // previous person's card doesn't linger next to the new one.
          const cleaned = prev.map(f => ({ ...f, info: undefined }));
          return [...cleaned, event.data];
        });

        // Trigger enrichment for newly known faces
        if (event.data.isKnown && event.data.name && !event.data.info) {
          const faceId = event.data.id;
          const lastRequestedName = enrichmentRequestedRef.current.get(faceId);
          if (lastRequestedName !== event.data.name) {
            enrichmentRequestedRef.current.set(faceId, event.data.name);
            enrichPersonByName(event.data.name)
              .then((info) => {
                if (!info) return;
                setFaces((prev) =>
                  prev.map((f) => (f.id === faceId ? { ...f, info } : f)),
                );
              })
              .catch((err) => {
                console.error("Enrichment failed", err);
              });
          }
        }
        break;
      case 'face_remove':
        setFaces(prev => prev.filter(f => f.id !== event.data.id));
        enrichmentRequestedRef.current.delete(event.data.id);
        break;
      case 'message':
        setMessages(prev => [...prev, event.data]);
        break;
      case 'memory':
        setMemoryEvent(event.data);
        if (event.data.type === 'found') {
          setTimeout(() => setMemoryEvent(null), 4000);
        }
        break;
      case 'learning':
        toast(`${event.data.personName} confidence: ${event.data.oldConfidence}% → ${event.data.newConfidence}%`, {
          duration: 4000,
          style: {
            background: 'hsl(0 0% 10%)',
            border: '1px solid hsl(342 100% 60% / 0.3)',
            color: 'white',
          },
        });
        break;
    }
  }, []);

  // ─── WebSocket Setup ───

  useEffect(() => {
    const socket = new OrbitSocket();
    socketRef.current = socket;
    socket.onAudio = playAudio;
    socket.start(handleEvent);
    return () => socket.stop();
  }, [handleEvent, playAudio]);

  // ─── Frame Sender (called by CameraFeed every 2s) ───

  const handleFrame = useCallback((base64: string) => {
    socketRef.current?.send({ type: 'frame', data: base64, timestamp: Date.now() });
  }, []);

  // ─── Text Sender ───

  const handleSendText = useCallback((text: string) => {
    socketRef.current?.send({ type: 'text', message: text });
    // Add user message to local conversation immediately
    setMessages(prev => [...prev, {
      id: `local_${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }]);
  }, []);

  // ─── Mic Toggle (record audio → send to backend for STT) ───

  const handleToggleMic = useCallback(async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
    } else {
      try {
        if (!audioStreamRef.current) {
          audioStreamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
        }
        audioChunksRef.current = [];
        const recorder = new MediaRecorder(audioStreamRef.current, {
          mimeType: 'audio/webm;codecs=opus',
        });
        recorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunksRef.current.push(e.data);
        };
        recorder.onstop = () => {
          const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
          const reader = new FileReader();
          reader.onloadend = () => {
            const base64 = (reader.result as string).split(',')[1];
            socketRef.current?.send({ type: 'audio', data: base64, mime_type: 'audio/webm' });
          };
          reader.readAsDataURL(blob);
        };
        recorder.start();
        mediaRecorderRef.current = recorder;
        setIsRecording(true);
      } catch (err) {
        console.error('Mic error:', err);
        toast('Microphone access denied', { duration: 3000 });
      }
    }
  }, [isRecording]);

  // ─── Recap ───

  const handleRecapOpen = async () => {
    if (socketRef.current) {
      const data = await socketRef.current.getRecapData();
      setRecapData(data);
    }
    setShowRecap(true);
  };

  // ─── Render ───

  return (
    <>
      <CameraFeed onFrame={handleFrame}>
        <PersonOverlay faces={faces} />
        <StatusBar status={status} onRecapOpen={handleRecapOpen} />
        <ConversationPanel
          messages={messages}
          memoryEvent={memoryEvent}
          onSendText={handleSendText}
          onToggleMic={handleToggleMic}
          isRecording={isRecording}
        />
      </CameraFeed>

      {showRecap && (
        <RecapView people={recapData} onClose={() => setShowRecap(false)} />
      )}
    </>
  );
};

export default Index;
