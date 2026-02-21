"""Self-learning loops — 3 feedback loops that make ORBIT smarter over time.

Adapted from:
- Vynn's self_improvement.py (EWMA drift detection, confidence-weighted scoring, auto-trigger)
- Astrai Alpha's self_learner.py (EVALUATE → REFLECT → OPTIMIZE → AUDIT cycle)

Loop 1: Face Confidence Bootstrapping (Generator-Verifier)
Loop 2: Memory Retrieval Self-Improvement
Loop 3: Intent Routing Calibration
"""
import json
import math
import time
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger("orbit.self_learning")

# Persist state to disk
STATE_DIR = Path.home() / ".orbit" / "learning"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Auto-trigger threshold (from Vynn pattern)
_interaction_counter = 0
_counter_lock = threading.Lock()
_cycle_lock = threading.Lock()
CALIBRATION_EVERY_N = 10  # Calibrate routing every 10 interactions


# ─── Loop 1: Face Confidence Bootstrapping ───

@dataclass
class FaceProfile:
    """Tracked state for a face (CLIP embeddings + confidence)."""
    person_id: str
    display_name: Optional[str] = None
    sighting_count: int = 0
    clip_embeddings: list = field(default_factory=list)  # List of 768-dim vectors
    avg_embedding: Optional[list] = None
    confidence_history: list = field(default_factory=list)  # (timestamp, confidence)
    identity_confirmed: bool = False


class FaceConfidenceTracker:
    """Loop 1: Face confidence bootstrapping.

    - Unknown face → temp ID → conversation reveals name → label face
    - CLIP embeddings averaged across sightings → improves re-identification
    - Emits orbit.face.confidence gauge (should trend UP)

    Adapted from Astrai's confidence = score * min(1.0, n/20) pattern.
    """

    def __init__(self):
        self.profiles: dict[str, FaceProfile] = {}
        self._load_state()

    def record_sighting(
        self,
        person_id: str,
        confidence: float,
        clip_embedding: Optional[list] = None,
        display_name: Optional[str] = None,
    ) -> dict:
        """Record a face sighting. Returns updated confidence info."""
        if person_id not in self.profiles:
            self.profiles[person_id] = FaceProfile(person_id=person_id)

        profile = self.profiles[person_id]
        profile.sighting_count += 1
        profile.confidence_history.append((time.time(), confidence))

        if display_name and not profile.display_name:
            profile.display_name = display_name

        # Accumulate CLIP embeddings (self-learning: more data = better matching)
        if clip_embedding is not None:
            profile.clip_embeddings.append(clip_embedding)
            # Running average — lightweight, CPU-friendly
            profile.avg_embedding = np.mean(profile.clip_embeddings, axis=0).tolist()

        # Confidence-weighted score (from Vynn pattern)
        # score * min(1.0, n/20) — scales with sample size
        raw_confidence = confidence
        weighted_confidence = raw_confidence * min(1.0, profile.sighting_count / 10)

        old_confidence = profile.confidence_history[-2][1] if len(profile.confidence_history) > 1 else 0
        self._save_state()

        # Emit Datadog metric
        try:
            from datadog_integration import gauge_face_confidence
            gauge_face_confidence(person_id, weighted_confidence)
        except Exception:
            pass

        return {
            "person_id": person_id,
            "sighting_count": profile.sighting_count,
            "raw_confidence": raw_confidence,
            "weighted_confidence": weighted_confidence,
            "old_confidence": old_confidence,
            "improved": weighted_confidence > old_confidence,
            "display_name": profile.display_name,
        }

    def confirm_identity(self, person_id: str, display_name: str) -> dict:
        """Generator-verifier: conversation confirmed the person's identity."""
        if person_id not in self.profiles:
            self.profiles[person_id] = FaceProfile(person_id=person_id)

        profile = self.profiles[person_id]
        profile.display_name = display_name
        profile.identity_confirmed = True
        self._save_state()

        logger.info(f"Identity confirmed: {person_id} → {display_name}")
        return {
            "person_id": person_id,
            "display_name": display_name,
            "sighting_count": profile.sighting_count,
            "confirmed": True,
        }

    def get_profile(self, person_id: str) -> Optional[dict]:
        """Get profile data for a face."""
        profile = self.profiles.get(person_id)
        if not profile:
            return None
        return {
            "person_id": profile.person_id,
            "display_name": profile.display_name,
            "sighting_count": profile.sighting_count,
            "identity_confirmed": profile.identity_confirmed,
            "confidence_trend": [c for _, c in profile.confidence_history[-10:]],
            "avg_embedding": profile.avg_embedding,
        }

    def get_all_profiles(self) -> list[dict]:
        """Get all tracked profiles."""
        return [self.get_profile(pid) for pid in self.profiles]

    def _load_state(self):
        state_file = STATE_DIR / "face_profiles.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                for pid, pdata in data.items():
                    self.profiles[pid] = FaceProfile(
                        person_id=pid,
                        display_name=pdata.get("display_name"),
                        sighting_count=pdata.get("sighting_count", 0),
                        confidence_history=pdata.get("confidence_history", []),
                        identity_confirmed=pdata.get("identity_confirmed", False),
                        # Don't persist embeddings to disk (too large)
                    )
            except Exception as e:
                logger.warning(f"Failed to load face profiles: {e}")

    def _save_state(self):
        state_file = STATE_DIR / "face_profiles.json"
        data = {}
        for pid, profile in self.profiles.items():
            data[pid] = {
                "display_name": profile.display_name,
                "sighting_count": profile.sighting_count,
                "confidence_history": profile.confidence_history[-50:],  # Keep last 50
                "identity_confirmed": profile.identity_confirmed,
            }
        try:
            state_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save face profiles: {e}")


# ─── Loop 2: Memory Retrieval Self-Improvement ───

@dataclass
class RetrievalAttempt:
    """Record of a memory retrieval and its self-evaluated quality."""
    timestamp: float
    person_id: str
    query: str
    results_count: int
    quality_score: float  # 1-10
    improved_query: Optional[str] = None
    improved_score: Optional[float] = None


class MemoryRetrievalEvaluator:
    """Loop 2: Memory retrieval self-improvement.

    After every RECALL, agent self-evaluates retrieval quality (1-10).
    If score < 7 → re-queries with improved search terms.
    Emits orbit.memory.retrieval_score gauge (should trend UP).

    Adapted from Vynn's feedback validation + EWMA drift detection.
    """

    def __init__(self):
        self.attempts: list[RetrievalAttempt] = []
        self.ewma_score: float = 7.0  # EWMA of retrieval quality
        self.ewma_lambda: float = 0.2  # From Vynn: 20% new, 80% history
        self._load_state()

    def evaluate_retrieval(
        self,
        person_id: str,
        query: str,
        results: list[dict],
        context: str = "",
    ) -> dict:
        """Self-evaluate a memory retrieval and potentially re-query.

        Uses Gemini to score retrieval quality 1-10.
        """
        quality_score = self._score_retrieval(query, results, context)

        attempt = RetrievalAttempt(
            timestamp=time.time(),
            person_id=person_id,
            query=query,
            results_count=len(results),
            quality_score=quality_score,
        )

        # Update EWMA (from Vynn pattern)
        self.ewma_score = self.ewma_lambda * quality_score + (1 - self.ewma_lambda) * self.ewma_score

        improved_results = None
        if quality_score < 7 and results:
            # Re-query with improved terms
            improved_query = self._improve_query(query, results, context)
            if improved_query and improved_query != query:
                attempt.improved_query = improved_query
                try:
                    from memory_store import search_memories
                    improved_results = search_memories(person_id, improved_query, limit=5)
                    attempt.improved_score = self._score_retrieval(improved_query, improved_results, context)
                    # Update EWMA with improved score
                    if attempt.improved_score and attempt.improved_score > quality_score:
                        self.ewma_score = self.ewma_lambda * attempt.improved_score + (1 - self.ewma_lambda) * self.ewma_score
                except Exception as e:
                    logger.warning(f"Improved retrieval failed: {e}")

        self.attempts.append(attempt)
        self._save_state()

        # Emit Datadog metric
        try:
            from datadog_integration import gauge_memory_retrieval_score
            gauge_memory_retrieval_score(self.ewma_score)
        except Exception:
            pass

        return {
            "quality_score": quality_score,
            "ewma_score": round(self.ewma_score, 2),
            "improved": attempt.improved_score is not None and attempt.improved_score > quality_score,
            "improved_query": attempt.improved_query,
            "improved_results": improved_results,
        }

    def _score_retrieval(self, query: str, results: list[dict], context: str) -> float:
        """Score retrieval quality 1-10 using heuristics (fast, no LLM call).

        Scoring rubric:
        - 0 results = 2
        - 1-2 results = 5 (something found but sparse)
        - 3+ results = 7 (good coverage)
        - Bonus: high relevance scores, identity matches
        """
        if not results:
            return 2.0

        base_score = min(7, 3 + len(results))

        # Bonus for high relevance scores
        avg_score = np.mean([r.get("score", 0) for r in results]) if results else 0
        if avg_score > 0.8:
            base_score += 1.5
        elif avg_score > 0.6:
            base_score += 1.0

        # Bonus for query terms appearing in results
        query_terms = set(query.lower().split())
        result_text = " ".join(r.get("content", "") for r in results).lower()
        match_ratio = sum(1 for t in query_terms if t in result_text) / max(len(query_terms), 1)
        base_score += match_ratio * 1.5

        return min(10.0, round(base_score, 1))

    def _improve_query(self, original_query: str, results: list[dict], context: str) -> Optional[str]:
        """Generate an improved search query based on poor results.

        Uses simple heuristics — add context terms, broaden scope.
        """
        # Extract useful terms from context that aren't in original query
        context_terms = set(context.lower().split()) if context else set()
        query_terms = set(original_query.lower().split())
        new_terms = context_terms - query_terms

        # Pick up to 3 contextually relevant terms
        useful_terms = [t for t in new_terms if len(t) > 3][:3]
        if useful_terms:
            return f"{original_query} {' '.join(useful_terms)}"
        return None

    def get_trend(self, last_n: int = 20) -> dict:
        """Get retrieval quality trend."""
        recent = self.attempts[-last_n:]
        if not recent:
            return {"trend": "no_data", "ewma": self.ewma_score}

        scores = [a.quality_score for a in recent]
        improved_count = sum(1 for a in recent if a.improved_score and a.improved_score > a.quality_score)

        return {
            "avg_score": round(np.mean(scores), 2),
            "ewma": round(self.ewma_score, 2),
            "improvement_rate": round(improved_count / len(recent), 2) if recent else 0,
            "total_attempts": len(self.attempts),
            "trend": "up" if len(scores) > 1 and scores[-1] > scores[0] else "stable",
        }

    def _load_state(self):
        state_file = STATE_DIR / "retrieval_evaluator.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                self.ewma_score = data.get("ewma_score", 7.0)
            except Exception:
                pass

    def _save_state(self):
        state_file = STATE_DIR / "retrieval_evaluator.json"
        data = {
            "ewma_score": self.ewma_score,
            "total_attempts": len(self.attempts),
            "last_updated": time.time(),
        }
        try:
            state_file.write_text(json.dumps(data, indent=2))
        except Exception:
            pass


# ─── Loop 3: Intent Routing Calibration ───

@dataclass
class RoutingDecision:
    """A recorded intent routing decision for later review."""
    timestamp: float
    user_input: str
    predicted_intent: str
    face_visible: bool
    had_memory_context: bool
    correct: Optional[bool] = None  # Set during calibration


class IntentCalibrator:
    """Loop 3: Intent routing calibration.

    Every N interactions → batch self-review of routing decisions.
    Corrections stored in mem0 system memory → injected into future routing context.
    Emits orbit.routing.accuracy gauge (should trend UP).

    Adapted from Vynn's auto-trigger pattern (counter + daemon thread).
    """

    def __init__(self):
        self.decisions: list[RoutingDecision] = []
        self.corrections: list[str] = []  # Natural language corrections for system prompt
        self.accuracy_history: list[tuple[float, float]] = []  # (timestamp, accuracy)
        self._load_state()

    def record_decision(self, user_input: str, predicted_intent: str, face_visible: bool, had_memory: bool):
        """Record a routing decision for later batch review."""
        self.decisions.append(RoutingDecision(
            timestamp=time.time(),
            user_input=user_input,
            predicted_intent=predicted_intent,
            face_visible=face_visible,
            had_memory_context=had_memory,
        ))

        # Auto-trigger calibration (from Vynn pattern)
        global _interaction_counter
        should_calibrate = False
        with _counter_lock:
            _interaction_counter += 1
            if _interaction_counter >= CALIBRATION_EVERY_N:
                _interaction_counter = 0
                should_calibrate = True

        if should_calibrate:
            t = threading.Thread(target=self._safe_calibrate, daemon=True, name="intent-calibrator")
            t.start()

    def _safe_calibrate(self):
        """Thread-safe calibration (from Vynn's non-blocking lock pattern)."""
        acquired = _cycle_lock.acquire(blocking=False)
        if not acquired:
            return  # Another calibration is running
        try:
            self.calibrate()
        except Exception as e:
            logger.error(f"Calibration failed: {e}")
        finally:
            _cycle_lock.release()

    def calibrate(self) -> dict:
        """Batch self-review of recent routing decisions.

        Uses heuristic rules to identify likely misroutes:
        - IDENTIFY without a face visible → probably CHITCHAT
        - RECALL without memory context → probably OBSERVE
        - REMEMBER without new information → probably CHITCHAT
        """
        recent = [d for d in self.decisions if d.correct is None][-CALIBRATION_EVERY_N:]
        if not recent:
            return {"calibrated": 0, "corrections": 0}

        new_corrections = []
        correct_count = 0

        for d in recent:
            likely_correct = True
            correction = None

            # Rule: IDENTIFY requires a visible face
            if d.predicted_intent == "IDENTIFY" and not d.face_visible:
                likely_correct = False
                correction = f"IDENTIFY should only be used when a face is visible. Input '{d.user_input[:50]}' had no face."

            # Rule: RECALL usually needs memory context
            if d.predicted_intent == "RECALL" and not d.had_memory_context:
                # Could be valid if asking "who did I meet?"
                question_words = {"who", "what", "when", "where", "how", "tell"}
                if not any(w in d.user_input.lower() for w in question_words):
                    likely_correct = False
                    correction = f"RECALL should be for memory queries. Input '{d.user_input[:50]}' wasn't a question."

            # Rule: OBSERVE is for scene-only, no person interaction
            if d.predicted_intent == "OBSERVE" and d.face_visible and d.had_memory_context:
                likely_correct = False
                correction = f"OBSERVE with a known face should be IDENTIFY or RECALL. Input: '{d.user_input[:50]}'"

            d.correct = likely_correct
            if likely_correct:
                correct_count += 1
            if correction:
                new_corrections.append(correction)

        # Compute accuracy
        accuracy = correct_count / len(recent) if recent else 1.0
        self.accuracy_history.append((time.time(), accuracy))

        # Store corrections for future routing (injected into system prompt)
        if new_corrections:
            self.corrections.extend(new_corrections)
            # Also persist to mem0
            try:
                from memory_store import store_system_memory
                for corr in new_corrections:
                    store_system_memory("routing_correction", corr)
            except Exception as e:
                logger.warning(f"Failed to store routing correction: {e}")

        self._save_state()

        # Emit Datadog metric
        try:
            from datadog_integration import gauge_routing_accuracy
            gauge_routing_accuracy(accuracy)
        except Exception:
            pass

        logger.info(f"Calibration: {correct_count}/{len(recent)} correct ({accuracy:.0%}), {len(new_corrections)} corrections")
        return {
            "calibrated": len(recent),
            "correct": correct_count,
            "accuracy": round(accuracy, 3),
            "new_corrections": new_corrections,
        }

    def get_corrections(self, limit: int = 5) -> list[str]:
        """Get recent routing corrections for injection into system prompt."""
        return self.corrections[-limit:]

    def get_accuracy_trend(self) -> dict:
        """Get routing accuracy trend."""
        if not self.accuracy_history:
            return {"trend": "no_data", "current": 1.0}

        recent = self.accuracy_history[-10:]
        accuracies = [a for _, a in recent]

        return {
            "current": accuracies[-1] if accuracies else 1.0,
            "avg": round(np.mean(accuracies), 3),
            "trend": "up" if len(accuracies) > 1 and accuracies[-1] > accuracies[0] else "stable",
            "calibrations": len(self.accuracy_history),
        }

    def _load_state(self):
        state_file = STATE_DIR / "intent_calibrator.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                self.corrections = data.get("corrections", [])
                self.accuracy_history = data.get("accuracy_history", [])
            except Exception:
                pass

    def _save_state(self):
        state_file = STATE_DIR / "intent_calibrator.json"
        data = {
            "corrections": self.corrections[-20:],  # Keep last 20
            "accuracy_history": self.accuracy_history[-50:],
            "total_decisions": len(self.decisions),
            "last_updated": time.time(),
        }
        try:
            state_file.write_text(json.dumps(data, indent=2))
        except Exception:
            pass


# ─── Singleton instances ───

face_tracker = FaceConfidenceTracker()
retrieval_evaluator = MemoryRetrievalEvaluator()
intent_calibrator = IntentCalibrator()


# ─── Unified Learning Report ───

def get_learning_report() -> dict:
    """Get a combined report of all 3 self-learning loops."""
    face_profiles = face_tracker.get_all_profiles()
    retrieval_trend = retrieval_evaluator.get_trend()
    routing_trend = intent_calibrator.get_accuracy_trend()

    return {
        "timestamp": time.time(),
        "face_confidence": {
            "profiles_tracked": len(face_profiles),
            "confirmed_identities": sum(1 for p in face_profiles if p and p.get("identity_confirmed")),
            "profiles": face_profiles,
        },
        "memory_retrieval": retrieval_trend,
        "intent_routing": routing_trend,
    }
