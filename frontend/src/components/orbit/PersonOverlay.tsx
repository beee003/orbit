import { DetectedFace } from '@/types/orbit';
import { useEffect, useRef, useState } from 'react';
import { ExternalLink } from 'lucide-react';

interface PersonOverlayProps {
  faces: DetectedFace[];
}

interface InterpolatedFace extends DetectedFace {
  displayX: number;
  displayY: number;
  displayW: number;
  displayH: number;
}

const PersonOverlay = ({ faces }: PersonOverlayProps) => {
  const [rendered, setRendered] = useState<InterpolatedFace[]>([]);
  const prevRef = useRef<Map<string, InterpolatedFace>>(new Map());

  useEffect(() => {
    const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
    const prev = prevRef.current;

    // Build set of current face IDs
    const currentIds = new Set(faces.map(f => f.id));

    // Only keep interpolation state for faces still in frame
    const staleIds: string[] = [];
    prev.forEach((_, id) => {
      if (!currentIds.has(id)) staleIds.push(id);
    });
    staleIds.forEach(id => prev.delete(id));

    const next: InterpolatedFace[] = faces.map(f => {
      const p = prev.get(f.id);
      const t = 0.3;
      return {
        ...f,
        displayX: p ? lerp(p.displayX, f.bbox.x, t) : f.bbox.x,
        displayY: p ? lerp(p.displayY, f.bbox.y, t) : f.bbox.y,
        displayW: p ? lerp(p.displayW, f.bbox.width, t) : f.bbox.width,
        displayH: p ? lerp(p.displayH, f.bbox.height, t) : f.bbox.height,
      };
    });
    const map = new Map<string, InterpolatedFace>();
    next.forEach(f => map.set(f.id, f));
    prevRef.current = map;
    setRendered(next);
  }, [faces]);

  return (
    <div className="absolute inset-0 pointer-events-none z-10">
      {rendered.map(face => (
        <div
          key={face.id}
          className={`absolute transition-all duration-200 ease-out ${face.isKnown ? 'face-box-known' : 'face-box-unknown'} rounded-sm`}
          style={{
            left: `${face.displayX}%`,
            top: `${face.displayY}%`,
            width: `${face.displayW}%`,
            height: `${face.displayH}%`,
          }}
        >
          {/* Info card — only for the face currently being tracked */}
          {face.isKnown && (
            <div
              className="absolute left-full top-0 ml-3"
              style={{ maxHeight: 'calc(100vh - 40px)' }}
            >
              <div className="backdrop-blur-2xl bg-background/40 border border-primary/25 rounded-2xl px-5 py-4 shadow-xl shadow-primary/10 min-w-[220px] max-w-[260px] max-h-[70vh] overflow-y-auto">
                <p className="text-base font-bold tracking-tight text-primary">
                  {face.name || 'Unknown'}
                </p>
                {face.confidence > 0 && (
                  <p className="text-xs text-muted-foreground mt-1 font-medium">
                    Confidence: {face.confidence}%
                  </p>
                )}

                {/* LinkedIn link — clickable */}
                {face.info?.linkedinUrl && (
                  <a
                    href={face.info.linkedinUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="pointer-events-auto flex items-center gap-1.5 mt-2 px-3 py-1.5 rounded-lg bg-[#0A66C2]/20 border border-[#0A66C2]/30 hover:bg-[#0A66C2]/40 transition-colors text-[#0A66C2] text-xs font-semibold no-underline"
                  >
                    <ExternalLink className="w-3 h-3" />
                    LinkedIn Profile
                  </a>
                )}

                {!face.info && (
                  <p className="text-xs text-muted-foreground mt-2 animate-pulse">
                    Fetching profile...
                  </p>
                )}

                {face.info && (
                  <div className="mt-2.5 space-y-1 text-xs text-foreground/80 whitespace-normal">
                    {face.info.occupation && (
                      <p><span className="text-muted-foreground">Role:</span> {face.info.occupation}</p>
                    )}
                    {face.info.connectionSource && (
                      <div className="mt-2 pt-2 border-t border-white/10">
                        <p className="text-primary font-semibold text-[11px] uppercase tracking-wider mb-1">Connected Via</p>
                        <p className="text-foreground/70 leading-snug">{face.info.connectionSource}</p>
                      </div>
                    )}
                    {face.info.mutualConnections && face.info.mutualConnections.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-white/10">
                        <p className="text-primary font-semibold text-[11px] uppercase tracking-wider mb-1">Mutual Connections</p>
                        {face.info.mutualConnections.map((c, i) => <p key={i} className="text-foreground/70 leading-snug">- {c}</p>)}
                      </div>
                    )}
                    {face.info.note && (
                      <div className="mt-2 pt-2 border-t border-white/10">
                        <p className="text-primary font-semibold text-[11px] uppercase tracking-wider mb-1">Note</p>
                        <p className="text-foreground/70 leading-snug italic">{face.info.note}</p>
                      </div>
                    )}
                    {face.info.work && face.info.work.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-white/10">
                        <p className="text-primary font-semibold text-[11px] uppercase tracking-wider mb-1">Work</p>
                        {face.info.work.map((w, i) => <p key={i} className="text-foreground/70 leading-snug">- {w}</p>)}
                      </div>
                    )}
                    {face.info.education && face.info.education.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-white/10">
                        <p className="text-primary font-semibold text-[11px] uppercase tracking-wider mb-1">Education</p>
                        {face.info.education.map((e, i) => <p key={i} className="text-foreground/70 leading-snug">- {e}</p>)}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default PersonOverlay;
