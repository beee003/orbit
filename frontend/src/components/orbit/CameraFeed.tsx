import { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, CameraOff, SwitchCamera } from 'lucide-react';

interface CameraFeedProps {
  children?: React.ReactNode;
  onFrame?: (base64: string) => void;
  frameIntervalMs?: number;
}

const CameraFeed = ({ children, onFrame, frameIntervalMs = 2000 }: CameraFeedProps) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [needsTap, setNeedsTap] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [facingMode, setFacingMode] = useState<'user' | 'environment'>('user');

  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }, []);

  const startCamera = useCallback(async () => {
    setError(null);
    setNeedsTap(false);
    setLoading(true);

    try {
      if (!window.isSecureContext) {
        setError(`Camera requires HTTPS. Open: ${window.location.origin.replace(/^http:/, "https:")}`);
        setLoading(false);
        return;
      }

      stopCamera();
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;

      const video = videoRef.current;
      if (!video) {
        setLoading(false);
        return;
      }

      video.srcObject = stream;

      try {
        await video.play();
      } catch {
        // iOS Safari may require a user gesture
        setNeedsTap(true);
      } finally {
        setLoading(false);
      }
    } catch (err: any) {
      const name = err?.name as string | undefined;
      if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
        setError('Camera permission denied. Enable it in your browser settings.');
      } else if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
        setError('No camera found on this device.');
      } else {
        setError('Unable to start camera.');
      }
      setLoading(false);
    }
  }, [stopCamera, facingMode]);

  useEffect(() => {
    startCamera();
    return () => stopCamera();
  }, [retryCount, facingMode, startCamera, stopCamera]);

  // Frame capture interval — sends JPEG base64 to backend every N ms
  useEffect(() => {
    if (!onFrame) return;
    if (!canvasRef.current) canvasRef.current = document.createElement('canvas');

    const interval = setInterval(() => {
      const video = videoRef.current;
      if (!video || video.readyState < 2) return;

      const canvas = canvasRef.current!;
      canvas.width = video.videoWidth || 1280;
      canvas.height = video.videoHeight || 720;
      const ctx = canvas.getContext('2d')!;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
      const base64 = dataUrl.split(',')[1];
      onFrame(base64);
    }, frameIntervalMs);

    return () => clearInterval(interval);
  }, [onFrame, frameIntervalMs]);

  const flipCamera = () => {
    setFacingMode(prev => prev === 'user' ? 'environment' : 'user');
  };

  if (error) {
    return (
      <div className="fixed inset-0 bg-background flex flex-col items-center justify-center gap-4">
        <CameraOff className="w-16 h-16 text-muted-foreground" />
        <p className="text-muted-foreground text-lg text-center px-8">{error}</p>
        <p className="text-muted-foreground/60 text-sm text-center px-8">
          Tip: on iPhone, open FaceLink over HTTPS (not plain HTTP).
        </p>
        <button
          onClick={() => setRetryCount(c => c + 1)}
          className="mt-2 px-5 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          Try Again
        </button>
        {children}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-background overflow-hidden">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center z-10">
          <div className="flex flex-col items-center gap-3">
            <Camera className="w-10 h-10 text-primary memory-pulse" />
            <p className="text-muted-foreground text-sm">Initializing camera...</p>
          </div>
        </div>
      )}
      {needsTap && (
        <div className="absolute inset-0 flex items-center justify-center z-20">
          <button
            onClick={async () => {
              try {
                await videoRef.current?.play();
                setNeedsTap(false);
              } catch {
                // keep prompt visible
              }
            }}
            className="px-5 py-3 rounded-xl glass-panel text-sm font-medium hover:bg-white/10 transition-colors pointer-events-auto"
          >
            Tap to enable camera
          </button>
        </div>
      )}
      <video
        ref={videoRef}
        className="w-full h-full object-cover"
        playsInline
        muted
        autoPlay
      />

      {/* Camera flip button */}
      <button
        onClick={flipCamera}
        className="absolute top-16 right-4 z-30 glass-panel p-2.5 rounded-lg hover:bg-white/10 transition-colors"
        aria-label="Flip camera"
      >
        <SwitchCamera className="w-5 h-5 text-primary" />
      </button>

      {children}
    </div>
  );
};

export default CameraFeed;
