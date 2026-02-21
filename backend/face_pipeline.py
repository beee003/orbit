"""Face pipeline — Rekognition for matching + CLIP for self-learning embeddings."""
import io
import uuid
import time
import logging
from typing import Optional

import boto3
import numpy as np
from PIL import Image

from config import (
    AWS_REGION, REKOGNITION_COLLECTION_ID,
    FACE_MATCH_THRESHOLD, CLIP_MODEL, CLIP_PRETRAINED,
    UNKNOWN_FACE_PREFIX,
)

logger = logging.getLogger("orbit.face")

# Lazy-loaded globals
_rekognition = None
_clip_model = None
_clip_preprocess = None
_clip_tokenizer = None


def _get_rekognition():
    global _rekognition
    if _rekognition is None:
        _rekognition = boto3.client("rekognition", region_name=AWS_REGION)
        # Ensure collection exists
        try:
            _rekognition.create_collection(CollectionId=REKOGNITION_COLLECTION_ID)
            logger.info(f"Created Rekognition collection: {REKOGNITION_COLLECTION_ID}")
        except _rekognition.exceptions.ResourceAlreadyExistsException:
            pass
    return _rekognition


def _get_clip():
    global _clip_model, _clip_preprocess
    if _clip_model is None:
        import open_clip
        _clip_model, _, _clip_preprocess = open_clip.create_model_and_transforms(
            CLIP_MODEL, pretrained=CLIP_PRETRAINED
        )
        _clip_model.eval()
        logger.info(f"Loaded CLIP model: {CLIP_MODEL}")
    return _clip_model, _clip_preprocess


def detect_faces(image_bytes: bytes) -> list[dict]:
    """Detect faces in an image, return bounding boxes."""
    rek = _get_rekognition()
    resp = rek.detect_faces(
        Image={"Bytes": image_bytes},
        Attributes=["DEFAULT"],
    )
    return [
        {
            "bounding_box": face["BoundingBox"],
            "confidence": face["Confidence"],
            "landmarks": face.get("Landmarks", []),
        }
        for face in resp["FaceDetails"]
    ]


def search_face(image_bytes: bytes) -> Optional[dict]:
    """Search for a face in the collection. Returns match info or None."""
    rek = _get_rekognition()
    try:
        resp = rek.search_faces_by_image(
            CollectionId=REKOGNITION_COLLECTION_ID,
            Image={"Bytes": image_bytes},
            MaxFaces=1,
            FaceMatchThreshold=FACE_MATCH_THRESHOLD,
        )
        if resp["FaceMatches"]:
            match = resp["FaceMatches"][0]
            return {
                "face_id": match["Face"]["FaceId"],
                "external_id": match["Face"].get("ExternalImageId", ""),
                "confidence": match["Similarity"],
            }
    except rek.exceptions.InvalidParameterException:
        # No face detected in image
        pass
    return None


def index_face(image_bytes: bytes, person_id: Optional[str] = None) -> dict:
    """Index a new face into the collection."""
    rek = _get_rekognition()
    if person_id is None:
        person_id = f"{UNKNOWN_FACE_PREFIX}{uuid.uuid4().hex[:8]}"

    resp = rek.index_faces(
        CollectionId=REKOGNITION_COLLECTION_ID,
        Image={"Bytes": image_bytes},
        ExternalImageId=person_id,
        MaxFaces=1,
        QualityFilter="AUTO",
    )
    if resp["FaceRecords"]:
        face = resp["FaceRecords"][0]["Face"]
        return {
            "face_id": face["FaceId"],
            "external_id": person_id,
            "confidence": face["Confidence"],
        }
    return {"face_id": None, "external_id": person_id, "confidence": 0}


def update_face_identity(old_external_id: str, new_name: str) -> bool:
    """Re-label a face by deleting old entry and the caller re-indexes.
    Rekognition doesn't support updating ExternalImageId directly,
    so we track the mapping in memory_store instead."""
    # Identity mapping is stored in mem0, not in Rekognition
    return True


def compute_clip_embedding(image_bytes: bytes) -> np.ndarray:
    """Compute CLIP embedding for a face crop. Returns 768-dim vector."""
    import torch
    model, preprocess = _get_clip()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_tensor = preprocess(img).unsqueeze(0)
    with torch.no_grad():
        embedding = model.encode_image(img_tensor)
        embedding = embedding / embedding.norm(dim=-1, keepdim=True)
    return embedding.squeeze().cpu().numpy()


def crop_face(image_bytes: bytes, bounding_box: dict) -> bytes:
    """Crop a face from an image given a Rekognition bounding box."""
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    left = int(bounding_box["Left"] * w)
    top = int(bounding_box["Top"] * h)
    right = left + int(bounding_box["Width"] * w)
    bottom = top + int(bounding_box["Height"] * h)
    # Add 20% padding
    pad_w = int((right - left) * 0.2)
    pad_h = int((bottom - top) * 0.2)
    left = max(0, left - pad_w)
    top = max(0, top - pad_h)
    right = min(w, right + pad_w)
    bottom = min(h, bottom + pad_h)
    cropped = img.crop((left, top, right, bottom))
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG")
    return buf.getvalue()


def process_frame(image_bytes: bytes) -> dict:
    """Full face pipeline for a single frame.
    Returns: {faces: [{person_id, confidence, bbox, is_new, clip_embedding}]}
    """
    start = time.time()
    faces_detected = detect_faces(image_bytes)
    results = []

    for face_info in faces_detected:
        bbox = face_info["bounding_box"]
        face_crop = crop_face(image_bytes, bbox)

        # Search for match
        match = search_face(face_crop)

        if match:
            person_id = match["external_id"]
            confidence = match["confidence"]
            is_new = False
        else:
            # New face — index it
            indexed = index_face(face_crop)
            person_id = indexed["external_id"]
            confidence = indexed["confidence"]
            is_new = True

        # Compute CLIP embedding for self-learning
        try:
            clip_emb = compute_clip_embedding(face_crop)
        except Exception as e:
            logger.warning(f"CLIP embedding failed: {e}")
            clip_emb = None

        results.append({
            "person_id": person_id,
            "confidence": confidence,
            "bounding_box": bbox,
            "is_new": is_new,
            "clip_embedding": clip_emb.tolist() if clip_emb is not None else None,
        })

    elapsed = time.time() - start
    logger.info(f"Processed frame: {len(results)} faces in {elapsed:.2f}s")
    return {"faces": results, "processing_time_ms": elapsed * 1000}
