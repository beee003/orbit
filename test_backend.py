"""Quick smoke test for each backend module.
Run: python3 test_backend.py
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent / "backend"))


def test_config():
    print("=== Config ===")
    import config
    keys = {
        "GEMINI_API_KEY": bool(config.GEMINI_API_KEY),
        "AWS_ACCESS_KEY_ID": bool(os.getenv("AWS_ACCESS_KEY_ID")),
        "PINECONE_API_KEY": bool(config.PINECONE_API_KEY),
        "MEM0_API_KEY": bool(config.MEM0_API_KEY),
        "ELEVENLABS_API_KEY": bool(config.ELEVENLABS_API_KEY),
        "DD_API_KEY": bool(config.DD_API_KEY),
    }
    for k, v in keys.items():
        status = "OK" if v else "MISSING"
        print(f"  {k}: {status}")
    missing = [k for k, v in keys.items() if not v]
    if missing:
        print(f"\n  WARNING: {len(missing)} keys missing. Some tests will fail.\n")
    return not missing


def test_gemini():
    print("\n=== Gemini Agent ===")
    try:
        import agent
        result = agent.respond(
            "Hello, who am I talking to?",
            "No faces visible. Scene: conference hall.",
        )
        print(f"  Intent: {result['intent']}")
        print(f"  Text: {result['text'][:100]}")
        print(f"  Latency: {result['latency_ms']:.0f}ms")
        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_mem0():
    print("\n=== mem0 + Pinecone ===")
    try:
        import memory_store
        # Store
        result = memory_store.add_memory("test_user", "This is a test memory from ORBIT smoke test.")
        print(f"  Store: {result['status']}")
        # Search
        results = memory_store.search_memories("test_user", "test memory", limit=1)
        print(f"  Search: found {len(results)} results")
        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_rekognition():
    print("\n=== AWS Rekognition ===")
    try:
        import face_pipeline
        # Just test collection creation
        rek = face_pipeline._get_rekognition()
        resp = rek.list_collections()
        collections = resp.get("CollectionIds", [])
        print(f"  Collections: {collections}")
        has_orbit = "orbit-faces" in collections
        print(f"  orbit-faces exists: {has_orbit}")
        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_elevenlabs():
    print("\n=== ElevenLabs TTS ===")
    try:
        import tts
        result = tts.synthesize("Hello, I am ORBIT.")
        print(f"  Audio size: {result['size_bytes']} bytes")
        print(f"  Latency: {result['latency_ms']:.0f}ms")
        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_self_learning():
    print("\n=== Self-Learning ===")
    try:
        from self_learning import face_tracker, retrieval_evaluator, intent_calibrator

        # Loop 1: Face confidence
        r = face_tracker.record_sighting("test_person", 75.0, display_name="Test Person")
        print(f"  Face tracker: sighting #{r['sighting_count']}, confidence={r['weighted_confidence']:.1f}")

        # Loop 2: Memory retrieval
        r2 = retrieval_evaluator.evaluate_retrieval(
            "test_person", "test query",
            [{"content": "test memory", "score": 0.8}],
        )
        print(f"  Retrieval evaluator: score={r2['quality_score']}, ewma={r2['ewma_score']}")

        # Loop 3: Intent calibration
        intent_calibrator.record_decision("hello", "CHITCHAT", face_visible=False, had_memory=False)
        print(f"  Intent calibrator: {len(intent_calibrator.decisions)} decisions recorded")

        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_datadog():
    print("\n=== Datadog ===")
    try:
        import datadog_integration as dd
        dd.increment_interaction()
        dd.gauge_face_confidence("test", 85.0)
        dd.gauge_memory_retrieval_score(7.5)
        dd.gauge_routing_accuracy(0.9)
        print("  Metrics emitted (noop if no agent running)")
        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


if __name__ == "__main__":
    print("ORBIT Backend Smoke Test")
    print("=" * 40)

    all_keys = test_config()

    results = {}
    results["self_learning"] = test_self_learning()
    results["datadog"] = test_datadog()

    if all_keys:
        results["gemini"] = test_gemini()
        results["mem0"] = test_mem0()
        results["rekognition"] = test_rekognition()
        results["elevenlabs"] = test_elevenlabs()
    else:
        print("\nSkipping API tests due to missing keys.")

    print("\n" + "=" * 40)
    print("RESULTS:")
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n{passed}/{total} passed")
