"""
FIREX v2 Rate Limiter & Security Throttling Middleware (Stage 10 Hardening)
Implements sliding-window in-memory token bucket rate limiting per IP address.
Guards critical API surfaces against DDoS, runaway loops, and abusive scrapers.
"""
import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
from app.core.logging import logger

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        # client_ip -> list of epoch timestamps
        self._clients: Dict[str, List[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Skip rate limiting for static dashboard assets, css, js, and imagery crops
        path = request.url.path
        if path.startswith(("/console", "/crops", "/docs", "/redoc", "/openapi.json")):
            return await call_next(request)

        # Determine client identifier
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        window_start = now - 60.0

        # Periodic cleanup of expired clients every 5 minutes to prevent memory leak
        if now - self._last_cleanup > 300.0:
            self._cleanup(window_start)
            self._last_cleanup = now

        # Prune older requests for this IP
        records = [t for t in self._clients.get(client_ip, []) if t > window_start]
        if len(records) >= self.requests_per_minute:
            logger.warning(f"[RateLimit] Rate limit exceeded for {client_ip} on {path} ({len(records)} req/min)")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Rate limit exceeded: maximum {self.requests_per_minute} requests per minute. Retry shortly."
                },
                headers={"Retry-After": "30"}
            )

        records.append(now)
        self._clients[client_ip] = records

        # Proceed
        response = await call_next(request)
        remaining = max(0, self.requests_per_minute - len(records))
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    def _cleanup(self, cutoff: float):
        clean_dict = defaultdict(list)
        for ip, times in self._clients.items():
            valid = [t for t in times if t > cutoff]
            if valid:
                clean_dict[ip] = valid
        self._clients = clean_dict
