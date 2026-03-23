-- ═══════════════════════════════════════════════════════════════════
-- Phantom Traders — Supabase Database Schema
-- Run this in: supabase.com → your project → SQL Editor → New Query
-- ═══════════════════════════════════════════════════════════════════

-- ── User profiles (extends Supabase auth.users) ───────────────────
CREATE TABLE IF NOT EXISTS public.user_profiles (
  id                    UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email                 TEXT NOT NULL,
  full_name             TEXT DEFAULT '',
  avatar_url            TEXT,

  -- Subscription
  plan                  TEXT DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'elite')),
  subscription_status   TEXT DEFAULT 'inactive'
                        CHECK (subscription_status IN ('active','inactive','cancelled','past_due','trialing')),
  subscription_end_date TIMESTAMPTZ,
  cancel_at_period_end  BOOLEAN DEFAULT FALSE,

  -- Stripe
  stripe_customer_id    TEXT UNIQUE,

  -- Discord
  discord_user_id       TEXT UNIQUE,
  discord_role_synced   BOOLEAN DEFAULT FALSE,

  -- Timestamps
  created_at            TIMESTAMPTZ DEFAULT NOW(),
  updated_at            TIMESTAMPTZ DEFAULT NOW()
);

-- ── Row Level Security ────────────────────────────────────────────
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

-- Users can only read/update their own profile
CREATE POLICY "Users can view own profile"
  ON public.user_profiles FOR SELECT
  USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
  ON public.user_profiles FOR UPDATE
  USING (auth.uid() = id);

-- Service role (backend) can do everything
CREATE POLICY "Service role full access"
  ON public.user_profiles FOR ALL
  USING (auth.role() = 'service_role');

-- ── Auto-update updated_at ────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_user_profiles_updated_at
  BEFORE UPDATE ON public.user_profiles
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── Course purchases ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.course_purchases (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID REFERENCES public.user_profiles(id) ON DELETE CASCADE,
  course_id     TEXT NOT NULL,           -- e.g. 'foundations', 'technical'
  price_paid    INTEGER DEFAULT 0,       -- cents
  stripe_payment_intent TEXT,
  purchased_at  TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.course_purchases ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own purchases"
  ON public.course_purchases FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role full access"
  ON public.course_purchases FOR ALL
  USING (auth.role() = 'service_role');

-- ── Useful views ──────────────────────────────────────────────────

-- Active subscribers
CREATE OR REPLACE VIEW public.active_subscribers AS
SELECT id, email, plan, subscription_end_date, discord_user_id
FROM public.user_profiles
WHERE subscription_status = 'active'
  AND plan != 'free';

-- Discord sync queue (users with Discord linked but roles not synced)
CREATE OR REPLACE VIEW public.discord_sync_pending AS
SELECT id, discord_user_id, plan
FROM public.user_profiles
WHERE discord_user_id IS NOT NULL
  AND discord_role_synced = FALSE;
