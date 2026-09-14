"""
FIREX v2 Key Pool Manager
Thread-safe round-robin API key manager with automatic failover.
"""
import logging
import threading
from typing import List, Optional, Callable, Any, Tuple
from app.core.config import settings

logger = logging.getLogger(__name__)

class KeyPoolManager:
    def __init__(self, api_keys: Optional[List[str]] = None):
        raw_keys = api_keys if api_keys is not None else settings.OPENROUTER_API_KEYS
        self.api_keys = [k.strip() for k in raw_keys if k and k.strip()]
        if not self.api_keys:
            logger.warning("[KeyPoolManager] No API keys configured in key pool.")
        
        self.current_idx = 0
        self.lock = threading.Lock()
        
        # Telemetry per key index
        self.stats = {
            i: {"calls": 0, "successes": 0, "failovers": 0}
            for i in range(len(self.api_keys))
        }

    @property
    def total_keys(self) -> int:
        return len(self.api_keys)

    def get_current_key(self) -> str:
        with self.lock:
            if not self.api_keys:
                return ""
            return self.api_keys[self.current_idx]

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

    def advance_after_success(self):
        """
        Rotates to next key after successful call for fair round-robin load distribution.
        """
        with self.lock:
            if self.api_keys:
                self.current_idx = (self.current_idx + 1) % len(self.api_keys)

# Global singleton instance
key_pool = KeyPoolManager()
