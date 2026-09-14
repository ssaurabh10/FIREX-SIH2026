"""
FIREX v2 Vision Intelligence Interface
Coordinates optical scene encoding, prompt generation, and multimodal execution.
"""
import os
import logging
from typing import Dict, Any, Optional

from app.intelligence.schemas import AIInvestigationReport
from app.intelligence.prompts import build_investigation_prompt
from app.intelligence.evidence import encode_satellite_image
from app.intelligence.provider import get_ai_provider, BaseAIProvider

logger = logging.getLogger(__name__)

def analyze_incident_scene(
    package: Dict[str, Any],
    provider: Optional[BaseAIProvider] = None
) -> AIInvestigationReport:
    """
    Executes multimodal scene analysis on an assembled Stage 5 Investigation Package.
    """
    ai_provider = provider or get_ai_provider()
    
    # 1. Locate and encode satellite crop
    vis = package.get("visual_context", {})
    incident_id = package.get("incident", {}).get("incident_id") or package.get("incident", {}).get("id")

    annotated_url = vis.get("annotated_image_url") or ""
    # Extract file path on disk: usually stored in data/imagery_cache/{incident_id}/annotated.jpg
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    disk_path = os.path.join(base_dir, "data", "imagery_cache", incident_id, "annotated.jpg")
    
    if not os.path.exists(disk_path):
        # Check raw image
        raw_path = os.path.join(base_dir, "data", "imagery_cache", incident_id, "raw.jpg")
        if os.path.exists(raw_path):
            disk_path = raw_path
        else:
            logger.warning(f"[Vision] No local cached image found at {disk_path}. Using synthetic transparent placeholder.")
            # 1x1 transparent PNG fallback if file is missing
            img_data_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAEASTN7AAAAABJRU5ErkJggg=="
            prompt = build_investigation_prompt(package)
            return ai_provider.investigate(prompt, img_data_uri)

    # 2. Encode to base64 Data URI
    img_data_uri = encode_satellite_image(disk_path)

    # 3. Construct prompt adhering to 12 blueprint rules
    prompt = build_investigation_prompt(package)

    # 4. Invoke multimodal provider
    logger.info(f"[Vision] Invoking AI Provider on incident {incident_id}...")
    report = ai_provider.investigate(prompt, img_data_uri)
    return report
