"""
FIREX v2 Key Pool Manager
Thread-safe round-robin API key manager with automatic failover, per-key error
tracking and the spec 6.3 cooldown/quarantine policy.
"""
import logging
import threading
import time
from typing import List, Optional, Callable, Any, Tuple
from app.core.config import settings

logger = logging.getLogger(__name__)

# Spec 6.3 ("Multi-Key Rotation Pool & Fallback Architecture"):
#   "On HTTP 429 (Rate Limit), key is quarantined for 60 seconds.
#    On HTTP 401/403, quarantined for 1 hour."
# These are the authoritative durations; settings may override them for tests or
# deployment tuning (see _settings_seconds below).
COOLDOWN_SECONDS_RATE_LIMIT = 60.0
COOLDOWN_SECONDS_AUTH = 3600.0

# HTTP statuses that earn the one-hour credential/billing quarantine.
# 401/403 are the spec's list. 402 (Payment Required) sits in the provider's
# failover branch but not in the spec's list: an out-of-credit key is unusable
# until an operator tops it up, exactly like a revoked one, so it shares the
# one-hour bucket instead of the 60-second rate-limit one -- retrying a dead key
# at full rate is the failure mode the quarantine exists to prevent.
AUTH_FAILURE_STATUS_CODES = (401, 402, 403)


def _settings_seconds(name: str, default: float) -> float:
    """
    Reads an optional override from settings, falling back to ``default``.
    getattr keeps this module working whether or not config.py declares the
    field, and the float() guards a hand-edited non-numeric value.
    """
    try:
        return float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def cooldown_seconds_for_status(status_code: int) -> float:
    """
    Spec 6.3 quarantine duration, in seconds, for a failing HTTP status code.
    """
    if status_code in AUTH_FAILURE_STATUS_CODES:
        return _settings_seconds("AI_KEY_QUARANTINE_SECONDS", COOLDOWN_SECONDS_AUTH)
    return _settings_seconds("AI_KEY_COOLDOWN_SECONDS", COOLDOWN_SECONDS_RATE_LIMIT)


class KeyPoolManager:
    def __init__(self, api_keys: Optional[List[str]] = None):
        raw_keys = api_keys if api_keys is not None else settings.OPENROUTER_API_KEYS
        self.api_keys = [k.strip() for k in raw_keys if k and k.strip()]
        if not self.api_keys:
            logger.warning("[KeyPoolManager] No API keys configured in key pool.")

        self.current_idx = 0
        self.lock = threading.Lock()

        # Telemetry per key index. "calls" is the spec 6.3 total_requests counter,
        # "errors" its error_count, and "cooldown_until" its quarantine deadline
        # (a time.monotonic() stamp; 0.0 means the key has never been quarantined).
        self.stats = {
            i: {"calls": 0, "successes": 0, "failovers": 0, "errors": 0, "cooldown_until": 0.0}
            for i in range(len(self.api_keys))
        }

    @property
    def total_keys(self) -> int:
        return len(self.api_keys)

    def _is_usable_locked(self, idx: int, now: float) -> bool:
        cooldown_until = self.stats[idx].get("cooldown_until", 0.0)
        return not cooldown_until or cooldown_until <= now

    def _select_index_locked(self, now: float) -> Optional[int]:
        """
        The usable key that has been cooling down longest -- the smallest
        cooldown_until -- with ties broken by the shortest step forward from the
        current pointer, so keys that have never been quarantined (deadline 0.0)
        keep ordinary round-robin order. Keys whose cooldown is still in the future
        are skipped entirely. Returns None when every key is quarantined, which is
        how callers learn the pool is exhausted without spinning.
        """
        if not self.api_keys:
            return None

        best: Optional[Tuple[float, int, int]] = None
        for offset in range(len(self.api_keys)):
            candidate = (self.current_idx + offset) % len(self.api_keys)
            if not self._is_usable_locked(candidate, now):
                continue
            sort_key = (self.stats[candidate]["cooldown_until"], offset, candidate)
            if best is None or sort_key < best:
                best = sort_key
        return None if best is None else best[2]

    def get_current_key(self) -> str:
        with self.lock:
            idx = self._select_index_locked(time.monotonic())
            if idx is None:
                return ""
            self.current_idx = idx
            return self.api_keys[idx]

    def get_key_identifier(self, idx: Optional[int] = None) -> str:
        with self.lock:
            target_idx = self.current_idx if idx is None else idx
            if not self.api_keys or target_idx >= len(self.api_keys):
                return "No-Key"
            key = self.api_keys[target_idx]
            prefix = key[:14] if len(key) >= 14 else key
            return f"Key #{target_idx + 1} ({prefix}...)"

    def rotate_key(self) -> Tuple[int, str]:
        """
        Advances the key pointer to the next key in a thread-safe round-robin manner.
        Used for failures the spec does not quarantine (unexpected statuses, network
        errors); 429/401/402/403 go through quarantine_key instead.
        """
        with self.lock:
            if not self.api_keys:
                return 0, ""
            old_idx = self.current_idx
            self.current_idx = (self.current_idx + 1) % len(self.api_keys)
            self.stats[old_idx]["failovers"] += 1
            logger.info(
                f"[KeyRotator] Advanced from Key #{old_idx + 1} -> Key #{self.current_idx + 1}"
            )
            return self.current_idx, self.api_keys[self.current_idx]

    def record_success(self, idx: Optional[int] = None):
        with self.lock:
            target_idx = self.current_idx if idx is None else idx
            if target_idx in self.stats:
                self.stats[target_idx]["successes"] += 1

    def record_call(self, idx: Optional[int] = None):
        with self.lock:
            target_idx = self.current_idx if idx is None else idx
            if target_idx in self.stats:
                self.stats[target_idx]["calls"] += 1

    def record_error(self, idx: Optional[int] = None):
        """Counts a key error that does not (or does not yet) earn a quarantine."""
        with self.lock:
            target_idx = self.current_idx if idx is None else idx
            if target_idx in self.stats:
                self.stats[target_idx]["errors"] += 1

    def quarantine_key(self, status_code: int, idx: Optional[int] = None) -> Tuple[int, str]:
        """
        Spec 6.3: quarantine the current key for the duration its HTTP status
        earns, then fail over. Returns (index, key) of the newly selected key, or
        an empty key when every key in the pool is cooling down.
        """
        duration = cooldown_seconds_for_status(status_code)
        with self.lock:
            if not self.api_keys:
                return 0, ""
            target_idx = self.current_idx if idx is None else idx
            if target_idx in self.stats:
                self.stats[target_idx]["errors"] += 1
                self.stats[target_idx]["failovers"] += 1
                self.stats[target_idx]["cooldown_until"] = time.monotonic() + duration
            logger.warning(
                f"[KeyPool] Key #{target_idx + 1} returned HTTP {status_code}; "
                f"quarantined for {duration:.0f}s"
            )

            # Step past the quarantined key, then let the selector skip any others
            # that are still cooling. If none is usable the caller gets "" and
            # falls through to the deterministic fallback instead of looping.
            self.current_idx = (target_idx + 1) % len(self.api_keys)
            next_idx = self._select_index_locked(time.monotonic())
            if next_idx is None:
                return self.current_idx, ""
            self.current_idx = next_idx
            return next_idx, self.api_keys[next_idx]

    def cooldown_remaining_seconds(self, idx: Optional[int] = None) -> float:
        """Seconds until key ``idx`` (default: the current key) is usable again."""
        with self.lock:
            target_idx = self.current_idx if idx is None else idx
            if target_idx not in self.stats:
                return 0.0
            return max(0.0, self.stats[target_idx]["cooldown_until"] - time.monotonic())

    def advance_after_success(self):
        """
        Rotates to next key after successful call for fair round-robin load distribution.
        """
        with self.lock:
            if self.api_keys:
                self.current_idx = (self.current_idx + 1) % len(self.api_keys)

# Global singleton instance
key_pool = KeyPoolManager()
