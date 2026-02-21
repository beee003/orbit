import { RecapPerson } from '@/types/orbit';
import { X, User, MessageCircle, ArrowRight } from 'lucide-react';

interface RecapViewProps {
  people: RecapPerson[];
  onClose: () => void;
}

const RecapView = ({ people, onClose }: RecapViewProps) => {
  return (
    <div className="fixed inset-0 z-50 bg-background/95 backdrop-blur-md overflow-y-auto animate-fade-in">
      <div className="max-w-lg mx-auto p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-2xl font-bold text-foreground">Session Recap</h2>
            <p className="text-sm text-muted-foreground mt-1">
              {people.length} {people.length === 1 ? 'person' : 'people'} encountered
            </p>
          </div>
          <button onClick={onClose} className="glass-panel p-2 rounded-lg hover:bg-white/10 transition-colors">
            <X className="w-5 h-5 text-muted-foreground" />
          </button>
        </div>

        {/* Person cards */}
        <div className="flex flex-col gap-4">
          {people.map(person => (
            <div key={person.name} className="glass-panel rounded-xl p-5">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
                  <User className="w-5 h-5 text-primary" />
                </div>
                <div className="flex-1">
                  <h3 className="font-semibold text-foreground">{person.name}</h3>
                  <div className="flex items-center gap-2 mt-0.5">
                    <div className="h-1.5 flex-1 max-w-24 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-orbit-success transition-all duration-500"
                        style={{ width: `${person.confidence}%` }}
                      />
                    </div>
                    <span className="text-xs text-orbit-success font-medium">{person.confidence}%</span>
                  </div>
                </div>
              </div>

              {/* Topics */}
              <div className="mb-3">
                <div className="flex items-center gap-1.5 mb-2">
                  <MessageCircle className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider">Topics</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {person.topics.map(topic => (
                    <span key={topic} className="text-xs px-2.5 py-1 rounded-full bg-secondary text-secondary-foreground">
                      {topic}
                    </span>
                  ))}
                </div>
              </div>

              {/* Follow-ups */}
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <ArrowRight className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider">Follow-ups</span>
                </div>
                <ul className="space-y-1.5">
                  {person.followUps.map(fu => (
                    <li key={fu} className="text-sm text-muted-foreground flex items-start gap-2">
                      <span className="text-primary mt-1">•</span>
                      {fu}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default RecapView;
