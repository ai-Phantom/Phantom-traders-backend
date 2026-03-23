"""
Phantom Traders — FastAPI Backend
Handles: auth helpers, Stripe webhooks, subscription sync, Discord role assignment
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, stripe_webhooks, subscriptions, discord_sync

app = FastAPI(title="Phantom Traders API", version="1.0.0")

# Allow requests from your site
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://aiphantomtraders.com",
        "https://www.aiphantomtraders.com",
        "https://phantom-site.pages.dev",
        "https://phantom-traders.pages.dev",
        "http://localhost:3000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
