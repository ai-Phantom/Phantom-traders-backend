"""
config.py — All environment variables in one place.
Copy .env.example to .env and fill in your values.
On Render: set these as Environment Variables in the dashboard.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Supabase ──────────────────────────────────────────────────────────────
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # ── Stripe ────────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str
    STRIPE_PUBLISHABLE_KEY: str
    STRIPE_WEBHOOK_SECRET: str

    # ── Stripe Price IDs — Subscriptions ─────────────────────────────────────
    STRIPE_PRICE_PRO_MONTHLY:        str = "price_1TDqXBBGuYguz5hx15nQlnaL"
    STRIPE_PRICE_PRO_ANNUAL:         str = "price_1TDqYkBGuYguz5hxO9e4pIce"
    STRIPE_PRICE_ELITE_MONTHLY:      str = "price_1TDqZNBGuYguz5hx7gK232Yq"
    STRIPE_PRICE_ELITE_ANNUAL:       str = "price_1TDqbHBGuYguz5hxmehMYtQI"
    STRIPE_PRICE_DISCORD_MONTHLY:    str = "price_1TDqbqBGuYguz5hxzJTT61dK"
    STRIPE_PRICE_DISCORD_ANNUAL:     str = "price_1TDqd9BGuYguz5hxu4tUrZMg"

    # ── Stripe Price IDs — Courses ────────────────────────────────────────────
    STRIPE_PRICE_COURSE_FOUNDATIONS: str = "price_1TDqdwBGuYguz5hxM0wRmrp2"
    STRIPE_PRICE_COURSE_TECHNICAL:   str = "price_1TDqebBGuYguz5hx2sTcDHmn"
    STRIPE_PRICE_COURSE_PORTFOLIO:   str = "price_1TDqfMBGuYguz5hxPFB8QGAE"
    STRIPE_PRICE_COURSE_MOMENTUM:    str = "price_1TDqgwBGuYguz5hxz3uWlJRr"
    STRIPE_PRICE_COURSE_OPTIONS:     str = "price_1TDqhaBGuYguz5hxusiFUDTn"
    STRIPE_PRICE_COURSE_TAX:         str = "price_1TDqiHBGuYguz5hxL2R3Casn"
    STRIPE_PRICE_COURSE_RISK:        str = "price_1TDqirBGuYguz5hxAjPXd2dL"
    STRIPE_PRICE_COURSE_ALGO:        str = "price_1TDqjLBGuYguz5hxljUZFCi1"
    STRIPE_PRICE_COURSE_INSTITUTIONAL: str = "price_1TDqkQBGuYguz5hx8pJEJ6tD"

    # ── Stripe Price IDs — Bundles ────────────────────────────────────────────
    STRIPE_PRICE_BUNDLE_BEGINNER:    str = "price_1TE0VKBGuYguz5hx1iUpcCRq"  # $20.00 one-time ✓
    STRIPE_PRICE_BUNDLE_INTERMEDIATE: str = "price_1TDqm8BGuYguz5hx4W0u5ZZB"
    STRIPE_PRICE_BUNDLE_EXPERT:      str = "price_1TDqmoBGuYguz5hxwIIce6ze"

    # ── Discord ───────────────────────────────────────────────────────────────
    DISCORD_BOT_TOKEN: str
    DISCORD_GUILD_ID: str
    DISCORD_ROLE_ROOKIE: str
    DISCORD_ROLE_TRADER: str
    DISCORD_ROLE_PRO_TRADER: str
    DISCORD_ROLE_ELITE: str
    DISCORD_ROLE_OG_MEMBER: str

    # ── App ───────────────────────────────────────────────────────────────────
    APP_ENV: str = "production"
    FRONTEND_URL: str = "https://aiphantomtraders.com"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


# ── Price → Plan mapping (used by webhooks) ───────────────────────────────────
def get_price_to_plan_map(s: Settings) -> dict:
    return {
        s.STRIPE_PRICE_PRO_MONTHLY:         "pro",
        s.STRIPE_PRICE_PRO_ANNUAL:          "pro",
        s.STRIPE_PRICE_ELITE_MONTHLY:       "elite",
        s.STRIPE_PRICE_ELITE_ANNUAL:        "elite",
        s.STRIPE_PRICE_DISCORD_MONTHLY:     "discord",
        s.STRIPE_PRICE_DISCORD_ANNUAL:      "discord",
        s.STRIPE_PRICE_COURSE_FOUNDATIONS:  "course",
        s.STRIPE_PRICE_COURSE_TECHNICAL:    "course",
        s.STRIPE_PRICE_COURSE_PORTFOLIO:    "course",
        s.STRIPE_PRICE_COURSE_MOMENTUM:     "course",
        s.STRIPE_PRICE_COURSE_OPTIONS:      "course",
        s.STRIPE_PRICE_COURSE_TAX:          "course",
        s.STRIPE_PRICE_COURSE_RISK:         "course",
        s.STRIPE_PRICE_COURSE_ALGO:         "course",
        s.STRIPE_PRICE_COURSE_INSTITUTIONAL:"course",
        s.STRIPE_PRICE_BUNDLE_BEGINNER:     "bundle",
        s.STRIPE_PRICE_BUNDLE_INTERMEDIATE: "bundle",
        s.STRIPE_PRICE_BUNDLE_EXPERT:       "bundle",
    }


# ── Price → Course ID mapping (for unlocking specific courses) ────────────────
def get_price_to_course_map(s: Settings) -> dict:
    return {
        s.STRIPE_PRICE_COURSE_FOUNDATIONS:   "foundations",
        s.STRIPE_PRICE_COURSE_TECHNICAL:     "technical",
        s.STRIPE_PRICE_COURSE_PORTFOLIO:     "portfolio-build",
        s.STRIPE_PRICE_COURSE_MOMENTUM:      "momentum",
        s.STRIPE_PRICE_COURSE_OPTIONS:       "options",
        s.STRIPE_PRICE_COURSE_TAX:           "tax-course",
        s.STRIPE_PRICE_COURSE_RISK:          "risk-mgmt",
        s.STRIPE_PRICE_COURSE_ALGO:          "algo",
        s.STRIPE_PRICE_COURSE_INSTITUTIONAL: "institutional",
        s.STRIPE_PRICE_BUNDLE_BEGINNER:      ["foundations", "technical", "portfolio-build"],
        s.STRIPE_PRICE_BUNDLE_INTERMEDIATE:  ["momentum", "options", "tax-course"],
        s.STRIPE_PRICE_BUNDLE_EXPERT:        ["risk-mgmt", "algo", "institutional"],
    }
