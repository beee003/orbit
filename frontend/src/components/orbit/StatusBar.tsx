import { StatusUpdate } from '@/types/orbit';
import { Users, MessageSquare, BarChart3, Linkedin } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';
import ThemeToggle from './ThemeToggle';

interface StatusBarProps {
  status: StatusUpdate;
  onRecapOpen: () => void;
}

function getBaseUrl(): string {
  return `${location.protocol}//${location.host}`;
}

const StatusBar = ({ status, onRecapOpen }: StatusBarProps) => {
  const [linkedinAuth, setLinkedinAuth] = useState(false);
  const [linking, setLinking] = useState(false);

  // Check LinkedIn auth status on mount
  useEffect(() => {
    fetch(`${getBaseUrl()}/api/linkedin/status`)
      .then(r => r.json())
      .then(d => setLinkedinAuth(!!d.authenticated))
      .catch(() => {});
  }, []);

  // Listen for OAuth popup completion
  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      if (e.data?.type === 'linkedin_auth' && e.data.ok) {
        setLinkedinAuth(true);
        setLinking(false);
      }
    };
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, []);

  const handleLinkedinLogin = useCallback(async () => {
    setLinking(true);
    try {
      const resp = await fetch(`${getBaseUrl()}/api/linkedin/auth`);
      const data = await resp.json();
      if (data.url) {
        // Open LinkedIn OAuth in popup
        const w = 600, h = 700;
        const left = (screen.width - w) / 2;
        const top = (screen.height - h) / 2;
        window.open(data.url, 'linkedin_oauth', `width=${w},height=${h},left=${left},top=${top}`);
      }
    } catch (err) {
      console.error('LinkedIn auth failed:', err);
      setLinking(false);
    }
  }, []);

  return (
    <header className="fixed top-0 left-0 right-0 z-30 glass-panel px-4 py-3 flex items-center justify-between safe-area-top">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-bold tracking-wider text-primary">ORBIT</h1>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${status.connected ? 'bg-orbit-success' : 'bg-destructive'}`} />
          <span className="text-xs text-muted-foreground">
            {status.connected ? 'Connected' : 'Offline'}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Users className="w-3.5 h-3.5" />
          <span>{status.peopleIdentified}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <MessageSquare className="w-3.5 h-3.5" />
          <span>{status.totalInteractions}</span>
        </div>

        {/* LinkedIn connect button */}
        <button
          onClick={handleLinkedinLogin}
          disabled={linkedinAuth || linking}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
            linkedinAuth
              ? 'bg-[#0A66C2]/20 text-[#0A66C2] border border-[#0A66C2]/30 cursor-default'
              : linking
              ? 'bg-[#0A66C2]/10 text-[#0A66C2]/60 border border-[#0A66C2]/20 animate-pulse'
              : 'bg-[#0A66C2] text-white hover:bg-[#0A66C2]/80 active:scale-95'
          }`}
        >
          <Linkedin className="w-3.5 h-3.5" />
          {linkedinAuth ? 'Connected' : linking ? 'Linking...' : 'LinkedIn'}
        </button>

        <ThemeToggle />
        <button
          onClick={onRecapOpen}
          className="glass-panel p-1.5 rounded-md hover:bg-white/10 transition-colors"
        >
          <BarChart3 className="w-4 h-4 text-primary" />
        </button>
      </div>
    </header>
  );
};

export default StatusBar;
