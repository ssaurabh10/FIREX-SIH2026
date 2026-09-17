"""
FIREX v2 AI Provider Abstraction
Decouples AI models and providers from core business logic.

Spec 6.3 ("Multi-Key Rotation Pool & Fallback Architecture") promises a four-leg
cascade:

    Gemini 2.5 Flash / Pro -> Groq Vision -> OpenAI GPT-4o -> Deterministic Sovereign Mock Provider

What is implemented here is ONE remote leg plus the terminal fallback:

    OpenRouterProvider (settings.AI_MODEL, key pool with spec-6.3 cooldowns)
        -> MockAIProvider (deterministic, offline)

The Gemini, Groq and OpenAI legs are deliberately NOT stubbed. No client for them
exists in this tree and no credentials for them are configured, so adding
placeholder clients would present three unconfigured providers as if they were
live providers -- a worse failure than the documented gap. The last leg of the
cascade IS real and is reachable two ways: the AI_PROVIDER=mock switch, and
automatically when every OpenRouter key is exhausted or quarantined, because
OpenRouterProvider._build_fallback_report delegates its classification to
MockAIProvider instead of hand-building a second verdict.

Closing the remaining gap is a credentials decision, not a code gap: each middle
leg would be another caller of OpenRouterProvider._build_messages() with the same
Section 6.1 twelve-rule system prompt.
"""
import re
import json
import logging
import requests
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.config import settings
from app.intelligence.schemas import (
    AIInvestigationReport,
    AlternativeHypothesis,
    ImageQualityAssessment,
    TaxonomyClass
)
from app.intelligence.key_pool import key_pool
from app.intelligence.prompts import PROMPT_VERSION, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# A terminal fallback report is an investigation that ran with no live model, so it
# must not read as confident: needs_reinvestigation=True is a promise that the scene
# still owes somebody a real look, and intelligence/service.py maps confidence
# >= 60.0 / >= 80.0 onto MEDIUM / LOW uncertainty. The mock supplies the fallback's
# evidence and its reporting structure, but its confidence is capped here so a
# provider outage surfaces as a high-uncertainty investigation rather than a
# confident one. 50.0 is the level the previous hardcoded fallback used, and it is
# what tests/test_stage10_hardening.py::test_failure_injection_openrouter_outage_pipeline_survives
# requires of any outage path.
FALLBACK_CONFIDENCE_CEILING = 50.0

class BaseAIProvider(ABC):
    """
    Abstract interface for multimodal AI investigation providers.
    """
    @abstractmethod
    def investigate(self, prompt: str, image_data_uri: str) -> AIInvestigationReport:
        pass


class OpenRouterProvider(BaseAIProvider):
    """
    OpenRouter multimodal provider with key pool failover and reasoning capture.
    """
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None
    ):
        self.model = model or settings.AI_MODEL
        self.base_url = (base_url or settings.AI_API_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.AI_TIMEOUT_SECONDS
        self.max_retries = max_retries or settings.AI_MAX_RETRIES or key_pool.total_keys

    def _build_messages(self, prompt: str, image_data_uri: str) -> list:
        """
        The one message list every model call is built from: the Section 6.1
        twelve-rule system prompt, then the per-incident user turn.

        F-002: prompts.SYSTEM_PROMPT was defined but never transmitted, so rules
        1-4, 8, 9 and 11 never reached the model. Building the list here (rather
        than inline in the payload) means the first attempt, every retry and every
        failover leg carry the same rules.
        """
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_uri}}
                ]
            }
        ]

    def investigate(self, prompt: str, image_data_uri: str) -> AIInvestigationReport:
        attempts = 0
        endpoint = f"{self.base_url}/chat/completions"
        total_attempts = max(1, self.max_retries)

        while attempts < total_attempts:
            attempts += 1
            key = key_pool.get_current_key()
            key_id = key_pool.get_key_identifier()

            if not key:
                # Every key is unusable -- quarantined by spec 6.3 cooldowns or the
                # pool is empty. Break rather than spin; the deterministic fallback
                # below is the terminal report.
                logger.error("[OpenRouter] No usable API key available in key pool.")
                break

            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://firex-sih2026.gov.in",
                "X-Title": "FIREX-SIH2026"
            }

            payload = {
                "model": self.model,
                "messages": self._build_messages(prompt, image_data_uri),
                "reasoning": {"enabled": True},
                "temperature": settings.AI_TEMPERATURE
            }

            key_pool.record_call()
            try:
                logger.info(f"[OpenRouter] Querying {self.model} via {key_id} (attempt {attempts}/{total_attempts})...")
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=self.timeout)

                if resp.status_code == 200:
                    data = resp.json()
                    choice = data.get("choices", [{}])[0]
                    msg = choice.get("message", {})

                    content = msg.get("content", "").strip()
                    reasoning = msg.get("reasoning_details") or msg.get("reasoning")

                    report = self._parse_json_response(content, reasoning, key_id)
                    key_pool.record_success()
                    key_pool.advance_after_success()
                    return report

                elif resp.status_code in [429, 401, 402, 403]:
                    # Spec 6.3: 429 is quarantined for 60s, 401/403 for 1 hour. 402
                    # (Payment Required) is not in the spec's list; it is treated as
                    # a credential/billing failure and shares the one-hour bucket --
                    # see key_pool.AUTH_FAILURE_STATUS_CODES.
                    logger.warning(
                        f"[OpenRouter] {key_id} returned HTTP {resp.status_code} ({resp.text[:120]}). "
                        f"Quarantining key and failing over..."
                    )
                    key_pool.quarantine_key(resp.status_code)

                else:
                    logger.warning(
                        f"[OpenRouter] {key_id} returned unexpected status {resp.status_code}: {resp.text[:150]}"
                    )
                    key_pool.record_error()
                    key_pool.rotate_key()

            except requests.exceptions.RequestException as e:
                logger.warning(f"[OpenRouter] Network or timeout error with {key_id}: {e}")
                key_pool.record_error()
                key_pool.rotate_key()

        logger.error(f"[OpenRouter] All {total_attempts} attempts exhausted across key pool.")
        return self._build_fallback_report(
            reason="All OpenRouter API keys exhausted or network timed out",
            key_id="Exhausted",
            prompt=prompt,
            image_data_uri=image_data_uri
        )

    def _parse_json_response(
        self,
        content: str,
        reasoning: Optional[Any],
        key_id: str
    ) -> AIInvestigationReport:
        # Strip markdown fences
        clean = re.sub(r"^```json\s*", "", content, flags=re.MULTILINE)
        clean = re.sub(r"^```\s*", "", clean, flags=re.MULTILINE)
        clean = clean.strip("` \n\r\t")

        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            clean = match.group(0)

        try:
            raw_dict = json.loads(clean)
        except Exception as e:
            logger.error(f"[OpenRouter] Failed to parse JSON response: {e}. Raw content: {content[:200]}")
            return self._build_fallback_report(
                reason=f"Failed to parse model JSON: {str(e)}",
                key_id=key_id,
                raw_text=content
            )

        # Map to Pydantic model with validation
        try:
            # Normalize taxonomy classification
            classification = self._normalize_taxonomy(raw_dict.get("classification", "uncertain"))
            alt_raw = raw_dict.get("alternative", {})
            alt_class = self._normalize_taxonomy(alt_raw.get("classification", "uncertain"))
            alt_conf = float(alt_raw.get("confidence", 10.0))

            img_q_raw = raw_dict.get("image_quality", {})

            return AIInvestigationReport(
                classification=classification,
                confidence=float(raw_dict.get("confidence", 70.0)),
                alternative=AlternativeHypothesis(
                    classification=alt_class,
                    confidence=alt_conf
                ),
                visual_evidence=raw_dict.get("visual_evidence", []),
                contextual_evidence=raw_dict.get("contextual_evidence", []),
                uncertainties=raw_dict.get("uncertainties", []),
                image_quality=ImageQualityAssessment(
                    score=float(img_q_raw.get("score", 80.0)),
                    cloud_cover=str(img_q_raw.get("cloud_cover", "low")),
                    visibility=str(img_q_raw.get("visibility", "good"))
                ),
                needs_reinvestigation=bool(raw_dict.get("needs_reinvestigation", False)),
                reasoning_summary=raw_dict.get("reasoning_summary", ""),
                reasoning_details=reasoning,
                model_used=self.model,
                key_used=key_id,
                prompt_version=PROMPT_VERSION,
                investigated_at=datetime.utcnow()
            )
        except Exception as e:
            logger.error(f"[OpenRouter] Pydantic validation error on model output: {e}")
            return self._build_fallback_report(
                reason=f"Schema validation error: {str(e)}",
                key_id=key_id,
                raw_text=content
            )

    def _normalize_taxonomy(self, label: str) -> TaxonomyClass:
        valid_classes = {
            "industrial_fire",
            "gas_flare",
            "wildfire",
            "agricultural_burning",
            "mining_related",
            "uncertain"
        }
        aliases = {
            "wild_fire": "wildfire",
            "forest_fire": "wildfire",
            "crop_burning": "agricultural_burning",
            "stubble_burning": "agricultural_burning",
            "flare": "gas_flare",
            "mining": "mining_related",
            # F-004: spec 6.2 names the sixth class "mining_or_other_thermal_source"
            # while the Blueprint and the wire/schema value use "mining_related". The
            # Blueprint wins for the value that is stored and served, so the spec's
            # literal is accepted here and normalised to the Blueprint spelling.
            # Without this alias the valid_classes check below silently downgraded a
            # spec-conformant model answer to "uncertain" -- that downgrade was the
            # real defect, not the naming difference.
            "mining_or_other_thermal_source": "mining_related",
        }
        cleaned = str(label).strip().lower().replace(" ", "_").replace("-", "_")
        cleaned = aliases.get(cleaned, cleaned)
        if cleaned in valid_classes:
            return cleaned  # type: ignore
        return "uncertain"

    def _build_fallback_report(
        self,
        reason: str,
        key_id: str,
        raw_text: str = "",
        prompt: str = "",
        image_data_uri: str = ""
    ) -> AIInvestigationReport:
        """
        Terminal report for every OpenRouter failure path (unparseable JSON,
        schema violation, exhausted/quarantined key pool).

        F-006: spec 6.3 ends the cascade at the Deterministic Sovereign Mock
        Provider, but this method used to hand-build a second, independent verdict
        and never reached MockAIProvider -- making the mock reachable only through
        the AI_PROVIDER env switch. The report's *shape* -- the evidence lists, the
        reasoning summary, the alternative slot -- now comes from the mock (the
        cascade's real last leg), and the failure metadata is layered on top of its
        output. Its confidence is capped at FALLBACK_CONFIDENCE_CEILING so the
        outage is still reported as an inconclusive investigation.

        The mock's *verdict*, however, is not a verdict about the scene, because
        this path is reached exactly when no model looked at the scene. Its
        rule-based classification is a keyword match over the prompt's own text,
        and it is not display-only: ``severity/service.py`` reads the stored
        classification verbatim into ``calculate_ai_source_severity``, where
        "industrial_fire" (92.0 base) scores 71.0 at the capped confidence against
        "uncertain"'s neutral 50.0. An outage would therefore have raised the
        AI-source contribution -- and the weighted final score with it -- on
        evidence that does not exist. Its image_quality would likewise have
        asserted pristine optical conditions (90.0 / low cloud / good visibility)
        for a crop nobody examined.

        Both are replaced with the neutral midpoint this codebase already uses for
        an unassessed input, and the uncertainty list says so in words, so the
        report states what it does not know instead of guessing (spec rule 4).
        """
        mock_report = MockAIProvider().investigate(prompt, image_data_uri)

        uncertainties = list(mock_report.uncertainties)
        if reason and reason not in uncertainties:
            uncertainties.append(reason)
        # The mock notes that it is the offline provider; this says what that means
        # for the verdict carried above it, which the mock alone cannot know.
        uncertainties.append(
            "No model inspected this scene: the classification is reported as "
            "\"uncertain\" rather than the fallback provider's keyword guess, and "
            "the image quality is left unassessed."
        )

        return mock_report.model_copy(
            update={
                "classification": "uncertain",
                "confidence": min(float(mock_report.confidence), FALLBACK_CONFIDENCE_CEILING),
                "alternative": AlternativeHypothesis(
                    classification="uncertain", confidence=50.0
                ),
                "image_quality": ImageQualityAssessment(
                    score=50.0, cloud_cover="medium", visibility="moderate"
                ),
                "uncertainties": uncertainties,
                "needs_reinvestigation": True,
                "reasoning_details": raw_text if raw_text else mock_report.reasoning_details,
                "model_used": f"{mock_report.model_used} (fallback for {self.model})",
                "key_used": key_id,
                "investigated_at": datetime.utcnow()
            }
        )


class MockAIProvider(BaseAIProvider):
    """
    Offline mock provider for testing and disconnected environments.
    Deterministic rule-based classification based on prompt signals.
    """
    def __init__(self, model_name: str = "mock-vision-v2"):
        self.model_name = model_name

    def investigate(self, prompt: str, image_data_uri: str) -> AIInvestigationReport:
        p_lower = prompt.lower()

        if "steel" in p_lower or "refinery" in p_lower or "smelter" in p_lower or "chemical" in p_lower:
            if "55.0 mw" in p_lower or "150" in p_lower or "spike" in p_lower:
                classification = "industrial_fire"
                confidence = 88.0
                alt_class = "gas_flare"
                alt_conf = 12.0
                visual = [
                    "Dense industrial infrastructure with prominent blast furnace and processing units",
                    "Massive white/grey smoke plume emanating near target crosshairs",
                    "Localized high-temperature thermal core visible within the inner range ring"
                ]
                contextual = [
                    "Thermal radiative power strongly exceeds 95th-percentile operational baseline ceiling",
                    "Proximity to core production units confirms high structural risk"
                ]
                summary = "Extreme thermal excursion within industrial footprint indicates accidental fire."
            else:
                classification = "gas_flare"
                confidence = 85.0
                alt_class = "industrial_fire"
                alt_conf = 15.0
                visual = [
                    "Vertical flare stack structure with localized radiant combustion crown",
                    "No broad smoke dispersion beyond operational venting stack"
                ]
                contextual = [
                    "FRP aligns with empirical baseline bounds for standard flare stack venting",
                    "Persistent localized emission from designated flare system"
                ]
                summary = "Controlled industrial flaring within expected plant operational parameters."

        elif "wildfire" in p_lower or "forest" in p_lower or "canopy" in p_lower:
            classification = "wildfire"
            confidence = 90.0
            alt_class = "agricultural_burning"
            alt_conf = 10.0
            visual = [
                "Unbroken forest canopy showing linear smoke front progression",
                "Absence of industrial machinery or structural geometry"
            ]
            contextual = [
                "Incident located within natural vegetation zone far from industrial assets"
            ]
            summary = "Natural vegetative fire spreading across forest canopy."

        elif "crop" in p_lower or "agricultural" in p_lower or "stubble" in p_lower:
            classification = "agricultural_burning"
            confidence = 86.0
            alt_class = "wildfire"
            alt_conf = 14.0
            visual = [
                "Rectangular agricultural field parcel layout with localized crop residue scorch marks"
            ]
            contextual = [
                "Seasonal post-harvest stubble burning pattern in agricultural district"
            ]
            summary = "Crop residue combustion across cleared agricultural land parcel."

        elif "mine" in p_lower or "coal" in p_lower or "quarry" in p_lower:
            classification = "mining_related"
            confidence = 84.0
            alt_class = "industrial_fire"
            alt_conf = 16.0
            visual = [
                "Open-cast excavation terraces and heavy haulage tracks visible inside perimeter"
            ]
            contextual = [
                "Hotspot coincides with documented open-cast mining concession area"
            ]
            summary = "Thermal activity associated with open-cast mining operations."

        else:
            classification = "uncertain"
            confidence = 50.0
            alt_class = "wildfire"
            alt_conf = 30.0
            visual = ["Optical scene inconclusive or partially obscured"]
            contextual = ["Insufficient baseline correlation"]
            summary = "Optical and telemetry evidence insufficient to establish high-confidence origin."

        return AIInvestigationReport(
            classification=classification,
            confidence=confidence,
            alternative=AlternativeHypothesis(
                classification=alt_class,
                confidence=alt_conf
            ),
            visual_evidence=visual,
            contextual_evidence=contextual,
            uncertainties=["Analysis generated by offline mock provider"],
            image_quality=ImageQualityAssessment(score=90.0, cloud_cover="low", visibility="good"),
            needs_reinvestigation=False,
            reasoning_summary=summary,
            reasoning_details=[{"type": "mock_reasoning", "text": f"Mock analysis classified as {classification}"}],
            model_used=self.model_name,
            key_used="Key #Mock (offline)",
            prompt_version=PROMPT_VERSION,
            investigated_at=datetime.utcnow()
        )


def get_ai_provider() -> BaseAIProvider:
    """
    Factory function to instantiate the configured AI provider.
    """
    provider_type = getattr(settings, "AI_PROVIDER", "openrouter").lower()
    if provider_type == "mock":
        return MockAIProvider()
    return OpenRouterProvider()
