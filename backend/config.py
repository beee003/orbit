"""ORBIT configuration — all keys and constants."""
import os

# AWS Rekognition
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
REKOGNITION_COLLECTION_ID = os.getenv("REKOGNITION_COLLECTION_ID", "orbit-faces")

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_VISION_MODEL = "gemini-2.5-flash"

# Pinecone
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "orbit-memory")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT", "us-east-1")

# ElevenLabs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # Adam

# Datadog
DD_API_KEY = os.getenv("DD_API_KEY", "")
DD_APP_KEY = os.getenv("DD_APP_KEY", "")
DD_SERVICE = "orbit"
DD_ENV = os.getenv("DD_ENV", "hackathon")

# mem0
MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")

# LinkedIn OAuth
LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/api/linkedin/callback")

# Firecrawl
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

# App
FRAME_INTERVAL_MS = 2000  # Extract frame every 2s
FACE_MATCH_THRESHOLD = 90.0  # Rekognition confidence threshold (strict)
CLIP_MODEL = "ViT-B-32"
CLIP_PRETRAINED = "openai"
UNKNOWN_FACE_PREFIX = "unknown_"
