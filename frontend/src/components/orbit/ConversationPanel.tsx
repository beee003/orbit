import { ConversationMessage, MemoryEvent } from '@/types/orbit';
import { useEffect, useRef, useState } from 'react';
import { Brain, Mic, Send } from 'lucide-react';

interface ConversationPanelProps {
  messages: ConversationMessage[];
  memoryEvent: MemoryEvent | null;
  onSendText?: (text: string) => void;
  onToggleMic?: () => void;
  isRecording?: boolean;
}

const ConversationPanel = ({
  messages,
  memoryEvent,
  onSendText,
  onToggleMic,
  isRecording,
}: ConversationPanelProps) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState('');

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, memoryEvent]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || !onSendText) return;
    onSendText(text);
    setInput('');
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 z-20 pointer-events-none" style={{ height: '40vh' }}>
      {/* Scrollable message area */}
      <div
        ref={scrollRef}
        className="h-full overflow-y-auto px-4 pb-20 pt-4 flex flex-col justify-end pointer-events-auto"
      >
        {/* Memory indicator */}
        {memoryEvent && (
          <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-primary/10 border border-primary/20 memory-pulse backdrop-blur-md">
            <Brain className="w-4 h-4 text-primary" />
            <span className="text-xs text-primary font-medium">
              {memoryEvent.type === 'searching'
                ? `Remembering ${memoryEvent.personName}...`
                : `Found ${memoryEvent.count} memories about ${memoryEvent.personName}`}
            </span>
          </div>
        )}

        {/* Messages */}
        <div className="flex flex-col gap-3">
          {messages.map(msg => (
            <div
              key={msg.id}
              className={`max-w-[85%] ${msg.role === 'user' ? 'self-end' : 'self-start'}`}
            >
              <div
                className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed backdrop-blur-xl ${
                  msg.role === 'agent'
                    ? 'bg-background/40 border border-primary/30 text-foreground'
                    : 'bg-background/50 border border-white/10 text-foreground'
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Input bar */}
      <div className="fixed bottom-0 left-0 right-0 z-30 glass-panel p-3 flex items-center gap-2 safe-area-bottom pointer-events-auto">
        <button
          onClick={onToggleMic}
          className={`p-2.5 rounded-full transition-all ${
            isRecording
              ? 'bg-destructive text-white pulse-glow'
              : 'bg-secondary text-muted-foreground hover:bg-secondary/80'
          }`}
          aria-label={isRecording ? 'Stop recording' : 'Start recording'}
        >
          <Mic className="w-5 h-5" />
        </button>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          placeholder="Say a name or ask..."
          className="flex-1 bg-secondary/50 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/50 transition-colors"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim()}
          className="p-2.5 rounded-full bg-primary text-primary-foreground disabled:opacity-30 transition-opacity"
          aria-label="Send message"
        >
          <Send className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
};

export default ConversationPanel;
