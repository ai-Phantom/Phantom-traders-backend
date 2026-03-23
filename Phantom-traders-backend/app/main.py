"""
Phantom Traders — FastAPI Backend
Handles: auth helpers, Stripe webhooks, subscription sync, Discord role assignment
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, stripe_webhooks, subscriptions, discord_sync

app = FastAPI(title="Phantom Traders API", version="1.0.0")

# Allow all origins — fixes CORS for all Cloudflare domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Handle OPTIONS preflight explicitly
from fastapi import Request
from fastapi.responses import Response

@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str, request: Request):
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "3600",
        }
    )

app.include_router(auth.router,             prefix="/auth",         tags=["Auth"])
app.include_router(stripe_webhooks.router,  prefix="/webhooks",     tags=["Webhooks"])
app.include_router(subscriptions.router,    prefix="/subscriptions",tags=["Subscriptions"])
app.include_router(discord_sync.router,     prefix="/discord",      tags=["Discord"])

@app.get("/")
def root():
    return {"status": "Phantom Traders API online"}

@app.get("/health")
def health():
    return {"status": "ok"}
