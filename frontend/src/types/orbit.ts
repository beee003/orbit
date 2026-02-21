export interface BoundingBox {
  x: number; // percentage 0-100
  y: number;
  width: number;
  height: number;
}

export interface PersonInfo {
  age?: number;
  sex?: string;
  pronouns?: string;
  occupation?: string;
  work?: string[];
  education?: string[];
  note?: string;
  mutualConnections?: string[];
  connectionSource?: string;
  linkedinUrl?: string;
}

export interface DetectedFace {
  id: string;
  name: string | null;
  confidence: number;
  bbox: BoundingBox;
  isKnown: boolean;
  info?: PersonInfo;
}

export interface ConversationMessage {
  id: string;
  role: 'agent' | 'user';
  content: string;
  timestamp: number;
}

export interface MemoryEvent {
  type: 'searching' | 'found';
  personName: string;
  count?: number;
}

export interface LearningEvent {
  personName: string;
  oldConfidence: number;
  newConfidence: number;
}

export interface StatusUpdate {
  connected: boolean;
  peopleIdentified: number;
  totalInteractions: number;
}

export interface RecapPerson {
  name: string;
  confidence: number;
  topics: string[];
  followUps: string[];
}

export type SimEvent =
  | { type: 'status'; data: StatusUpdate }
  | { type: 'face'; data: DetectedFace }
  | { type: 'face_remove'; data: { id: string } }
  | { type: 'message'; data: ConversationMessage }
  | { type: 'memory'; data: MemoryEvent }
  | { type: 'learning'; data: LearningEvent };
