"""
Phantom Traders — FastAPI Backend
Handles: auth, Stripe webhooks, subscriptions, Discord, email
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.routers import auth, stripe_webhooks, subscriptions, discord_sync
from app.routers.email_routes import router as email_router
from app.sentry_setup import init_sentry, SentryPerformanceMiddleware

# Init Sentry before anything else
init_sentry()

app = FastAPI(title="Phantom Traders API", version="1.0.0")

# Sentry performance + slow response tracking
app.add_middleware(SentryPerformanceMiddleware)

# Force CORS headers on every response
class ForceCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH, HEAD",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Max-Age": "86400",
                }
            )
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH, HEAD"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

app.add_middleware(ForceCORSMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

app.include_router(auth.router,             prefix="/auth",          tags=["Auth"])
app.include_router(stripe_webhooks.router,  prefix="/webhooks",      tags=["Webhooks"])
app.include_router(subscriptions.router,    prefix="/subscriptions", tags=["Subscriptions"])
app.include_router(discord_sync.router,     prefix="/discord",       tags=["Discord"])
app.include_router(email_router)

@app.get("/")
@app.head("/")
def root():
    return {"status": "Phantom Traders API online"}

@app.get("/health")
@app.head("/health")
def health():
    return {"status": "ok"}
