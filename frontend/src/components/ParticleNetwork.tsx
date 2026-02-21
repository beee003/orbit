import { useEffect, useRef } from 'react';

interface Point {
  x: number; y: number;
  ox: number; oy: number;
  tx: number; ty: number;
  t: number; dur: number;
  sx: number; sy: number;
  radius: number;
  closest: Point[];
}

function dist2(a: { x: number; y: number }, b: { x: number; y: number }) {
  return (a.x - b.x) ** 2 + (a.y - b.y) ** 2;
}

function ease(t: number) {
  return t < 0.5
    ? (1 - Math.sqrt(1 - 4 * t * t)) / 2
    : (Math.sqrt(1 - (-2 * t + 2) ** 2) + 1) / 2;
}

function newDrift(p: Point) {
  p.sx = p.x;
  p.sy = p.y;
  p.tx = p.ox - 50 + Math.random() * 100;
  p.ty = p.oy - 50 + Math.random() * 100;
  p.dur = 1500 + Math.random() * 2000;
  p.t = 0;
}

const ParticleNetwork = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const isMobile = window.innerWidth < 768;

    let W = 0, H = 0;
    const target = { x: -1000, y: -1000 };
    let points: Point[] = [];
    let animId = 0;
    let resizeTimer: number | undefined;

    // FaceLink cyan — RGB(0, 229, 255)
    const cr = 0, cg = 229, cb = 255;

    function initPoints() {
      points = [];
      const cols = isMobile ? 8 : 20;
      const rows = Math.round(cols * (H / W));
      const stepX = W / cols;
      const stepY = H / rows;
      const neighborCount = isMobile ? 3 : 5;

      for (let x = 0; x < W; x += stepX) {
        for (let y = 0; y < H; y += stepY) {
          const px = x + Math.random() * stepX;
          const py = y + Math.random() * stepY;
          points.push({
            x: px, y: py,
            ox: px, oy: py,
            tx: 0, ty: 0,
            t: 1, dur: 0,
            sx: 0, sy: 0,
            radius: isMobile ? 1.5 + Math.random() * 1.5 : 2 + Math.random() * 2,
            closest: [],
          });
        }
      }

      for (let i = 0; i < points.length; i++) {
        const dists: { idx: number; d: number }[] = [];
        for (let j = 0; j < points.length; j++) {
          if (i === j) continue;
          dists.push({ idx: j, d: dist2(points[i], points[j]) });
        }
        dists.sort((a, b) => a.d - b.d);
        points[i].closest = dists.slice(0, neighborCount).map(d => points[d.idx]);
        newDrift(points[i]);
      }
    }

    function resize() {
      W = canvas!.width = window.innerWidth;
      H = canvas!.height = window.innerHeight;
      initPoints();
    }

    function debouncedResize() {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(resize, 200);
    }

    function animate() {
      ctx!.clearRect(0, 0, W, H);

      for (const p of points) {
        p.t += 16.67 / p.dur;
        if (p.t >= 1) {
          p.x = p.tx;
          p.y = p.ty;
          newDrift(p);
        } else {
          const e = ease(p.t);
          p.x = p.sx + (p.tx - p.sx) * e;
          p.y = p.sy + (p.ty - p.sy) * e;
        }
      }

      for (const p of points) {
        const d = dist2(target, p);
        let lineA: number, circA: number;

        if (d < 4000) {
          lineA = 0.6; circA = 1.0;
        } else if (d < 20000) {
          lineA = 0.4; circA = 0.6;
        } else if (d < 50000) {
          lineA = 0.2; circA = 0.35;
        } else {
          lineA = 0.1; circA = 0.2;
        }

        for (const c of p.closest) {
          ctx!.beginPath();
          ctx!.moveTo(p.x, p.y);
          ctx!.lineTo(c.x, c.y);
          ctx!.strokeStyle = `rgba(${cr},${cg},${cb},${lineA})`;
          ctx!.lineWidth = lineA > 0.2 ? 1 : 0.6;
          ctx!.stroke();
        }

        ctx!.beginPath();
        ctx!.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx!.fillStyle = `rgba(${cr},${cg},${cb},${circA})`;
        ctx!.fill();
      }

      animId = requestAnimationFrame(animate);
    }

    const onMouseMove = (e: MouseEvent) => { target.x = e.clientX; target.y = e.clientY; };
    const onMouseLeave = () => { target.x = -1000; target.y = -1000; };
    const onTouchMove = (e: TouchEvent) => { target.x = e.touches[0].clientX; target.y = e.touches[0].clientY; };
    const onTouchEnd = () => { target.x = -1000; target.y = -1000; };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseleave', onMouseLeave);
    window.addEventListener('touchmove', onTouchMove, { passive: true });
    window.addEventListener('touchend', onTouchEnd);
    window.addEventListener('resize', debouncedResize);

    resize();
    animate();

    return () => {
      cancelAnimationFrame(animId);
      if (resizeTimer) clearTimeout(resizeTimer);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseleave', onMouseLeave);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onTouchEnd);
      window.removeEventListener('resize', debouncedResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        zIndex: 0,
        pointerEvents: 'none',
      }}
    />
  );
};

export default ParticleNetwork;
