"""Seed demo contacts — pre-load faces + memories for demo.

Run: python3 seed_data.py
Requires: .env with API keys, sample face images in seed_faces/
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent / "backend"))

import face_pipeline
import memory_store
from self_learning import face_tracker


DEMO_CONTACTS = [
    {
        "name": "Alex Kim",
        "person_id": "alex_kim",
        "company": "Datadog",
        "role": "Senior APM Engineer",
        "memories": [
            "Works on the APM team at Datadog, focused on distributed tracing.",
            "Mentioned they're building a new service map feature.",
            "Interested in AI observability and LLM monitoring.",
            "From San Francisco, moved from Seattle last year.",
        ],
        "topics": ["APM", "distributed tracing", "AI observability"],
    },
    {
        "name": "Sarah Chen",
        "person_id": "sarah_chen",
        "company": "Anthropic",
        "role": "ML Research Engineer",
        "memories": [
            "Works on safety research at Anthropic.",
            "Previously at Google DeepMind working on reinforcement learning.",
            "Gave a great talk about AI alignment at NeurIPS.",
            "Looking for collaboration on interpretability research.",
        ],
        "topics": ["AI safety", "interpretability", "reinforcement learning"],
    },
    {
        "name": "Marcus Johnson",
        "person_id": "marcus_johnson",
        "company": "Stripe",
        "role": "Staff Engineer",
        "memories": [
            "Leads the payments infrastructure team at Stripe.",
            "Built their real-time fraud detection system.",
            "Interested in applying ML to financial compliance.",
            "Organizes the SF Systems meetup group.",
        ],
        "topics": ["payments", "fraud detection", "systems engineering"],
    },
]


def seed_memories():
    """Seed memories for demo contacts (no face images needed)."""
    print("Seeding demo contact memories...\n")

    for contact in DEMO_CONTACTS:
        person_id = contact["person_id"]
        name = contact["name"]
        print(f"  {name} ({person_id})")

        # Store identity
        memory_store.store_identity(
            person_id,
            name,
            metadata={
                "company": contact["company"],
                "role": contact["role"],
            },
        )

        # Store memories
        for mem in contact["memories"]:
            memory_store.add_memory(person_id, mem, metadata={"type": "conversation"})
            print(f"    + {mem[:60]}...")

        # Store conversation summary
        memory_store.store_conversation_summary(
            person_id,
            f"Met {name} from {contact['company']}. They work as {contact['role']}. "
            f"Discussed: {', '.join(contact['topics'])}.",
            topics=contact["topics"],
        )

        # Register in face tracker
        face_tracker.confirm_identity(person_id, name)
        # Register face mapping
        memory_store.update_identity_mapping(person_id, name)

        print(f"    Done ({len(contact['memories'])} memories)\n")

    print(f"Seeded {len(DEMO_CONTACTS)} contacts.")


def seed_faces():
    """Seed face images if available in seed_faces/ directory."""
    faces_dir = Path(__file__).parent / "seed_faces"
    if not faces_dir.exists():
        print("\nNo seed_faces/ directory found. Skipping face indexing.")
        print("To seed faces, create seed_faces/ with images named like: alex_kim.jpg")
        return

    print("\nIndexing seed face images...")
    for img_file in faces_dir.glob("*.jpg"):
        person_id = img_file.stem  # e.g., "alex_kim"
        image_bytes = img_file.read_bytes()

        # Index face in Rekognition
        result = face_pipeline.index_face(image_bytes, person_id=person_id)
        print(f"  Indexed {person_id}: face_id={result.get('face_id')}")

        # Compute and store CLIP embedding
        clip_emb = face_pipeline.compute_clip_embedding(image_bytes)
        face_tracker.record_sighting(
            person_id=person_id,
            confidence=99.0,  # Seed at high confidence
            clip_embedding=clip_emb.tolist(),
        )

    print("Face indexing complete.")


if __name__ == "__main__":
    seed_memories()
    seed_faces()
    print("\nDone! Run the backend to start using ORBIT.")
