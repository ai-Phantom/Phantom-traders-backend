"""
database.py — Supabase client.
Uses service role key for backend operations (bypasses RLS).
"""

from supabase import create_client, Client
from app.config import get_settings

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        s = get_settings()
        _client = create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)
    return _client
