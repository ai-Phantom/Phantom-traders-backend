"""
Phantom Traders — Sentry Error Monitoring
Place in: Phantom-traders-backend/app/sentry_setup.py

Steps:
1. pip install sentry-sdk[fastapi]  (add to requirements.txt)
2. Add SENTRY_DSN to Render env vars
3. Import and call init_sentry() in main.py before app = FastAPI(...)

sentry.io → New Project → Python → FastAPI → copy DSN
"""

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
import os
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


def init_sentry():
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        print("⚠ SENTRY_DSN not set — error monitoring disabled")
        return

    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        # Capture 100% of errors, 10% of transactions (performance)
        traces_sample_rate=0.1,
        # Tag all events with environment
        environment=os.environ.get("ENVIRONMENT", "production"),
        # Don't send PII
        send_default_pii=False,
        # Filter out noise
        ignore_errors=[KeyboardInterrupt],
        before_send=_before_send,
    )
    print("✓ Sentry initialized")


def _before_send(event, hint):
    """Filter out noise before sending to Sentry."""
    # Don't report 401/403/404 errors
    if "exc_info" in hint:
        exc_type, exc_value, _ = hint["exc_info"]
        if hasattr(exc_value, "status_code"):
            if exc_value.status_code in (401, 403, 404, 422):
                return None
    return event


class SentryPerformanceMiddleware(BaseHTTPMiddleware):
    """Track slow API responses (>2s) and failed Stripe webhooks."""

    SLOW_THRESHOLD = 2.0  # seconds

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        # Report slow responses
        if duration > self.SLOW_THRESHOLD:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("slow_response", True)
                scope.set_extra("duration_seconds", round(duration, 3))
                scope.set_extra("path", request.url.path)
                scope.set_extra("method", request.method)
                sentry_sdk.capture_message(
                    f"Slow response: {request.method} {request.url.path} ({duration:.2f}s)",
                    level="warning"
                )

        # Report failed Stripe webhooks
        if "/webhooks/stripe" in request.url.path and response.status_code >= 400:
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("stripe_webhook_failed", True)
                scope.set_extra("status_code", response.status_code)
                sentry_sdk.capture_message(
                    f"Stripe webhook failed: {response.status_code}",
                    level="error"
                )

        return response


def capture_stripe_error(event_type: str, error: Exception, data: dict = None):
    """Manually capture Stripe webhook processing errors."""
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("stripe_event_type", event_type)
        scope.set_extra("event_data", str(data)[:500] if data else None)
        sentry_sdk.capture_exception(error)
