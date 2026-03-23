# Phantom Traders — Backend API

Full production backend: auth, payments, subscriptions, Discord role sync.

---

## File Structure

```
phantom-backend/
├── app/
│   ├── main.py              # FastAPI app, CORS, routes
│   ├── config.py            # All env vars in one place
│   ├── database.py          # Supabase client
│   ├── models/
│   │   └── user.py          # Pydantic request/response models
│   └── routers/
│       ├── auth.py          # Signup, login, profile
│       ├── subscriptions.py # Stripe checkout + portal
│       ├── stripe_webhooks.py # Stripe event handling
│       └── discord_sync.py  # Discord role assignment
├── supabase_schema.sql      # Run this in Supabase SQL editor
├── requirements.txt
├── render.yaml              # Render deployment config
└── .env.example             # Copy to .env and fill in values
```

---

## Deployment — Step by Step

### Step 1 — Supabase Setup

1. Go to **supabase.com** → New Project → name it `phantom-traders`
2. Wait for it to provision (~2 min)
3. Go to **SQL Editor** → New Query → paste contents of `supabase_schema.sql` → Run
4. Go to **Settings → API** and copy:
   - Project URL → `SUPABASE_URL`
   - anon/public key → `SUPABASE_ANON_KEY`
   - service_role key → `SUPABASE_SERVICE_ROLE_KEY`
5. Go to **Authentication → Settings**:
   - Set Site URL to `https://aiphantomtraders.com`
   - Add redirect URL: `https://aiphantomtraders.com`
   - Enable Email provider (should be on by default)

### Step 2 — Stripe Setup

1. Go to **dashboard.stripe.com** → Create account
2. Go to **Products → Add Product** and create 4 products:

| Name | Price | Billing |
|---|---|---|
| Pro Trader Monthly | $20.00 | Monthly recurring |
| Pro Trader Annual | $168.00 | Annual recurring |
| Elite Monthly | $50.00 | Monthly recurring |
| Elite Annual | $420.00 | Annual recurring |

3. For each product, copy the **Price ID** (starts with `price_`)
4. Go to **Developers → API Keys** and copy:
   - Publishable key → `STRIPE_PUBLISHABLE_KEY`
   - Secret key → `STRIPE_SECRET_KEY`
5. Go to **Developers → Webhooks → Add endpoint**:
   - URL: `https://your-render-url.onrender.com/webhooks/stripe`
   - Events to listen for:
     - `checkout.session.completed`
     - `customer.subscription.updated`
     - `customer.subscription.deleted`
     - `invoice.payment_failed`
     - `invoice.payment_succeeded`
   - Copy the **Signing secret** → `STRIPE_WEBHOOK_SECRET`

### Step 3 — Discord Role IDs

1. In Discord → User Settings → Advanced → enable **Developer Mode**
2. In your server → Server Settings → Roles
3. Right-click each role → **Copy Role ID**:
   - Rookie, Trader, Pro Trader, Elite, OG Member

### Step 4 — Deploy to Render

1. Push all files to a GitHub repo called `phantom-traders-backend`
2. Go to **render.com** → New → Web Service → connect your repo
3. Render auto-detects the `render.yaml` config
4. Go to **Environment** tab and add all variables from `.env.example`
5. Click **Deploy**
6. Copy your Render URL (e.g. `https://phantom-traders-api.onrender.com`)
7. Go back to Stripe and update the webhook URL to your Render URL

### Step 5 — Update Stripe Webhook URL

After deploy, update the Stripe webhook endpoint URL to your live Render URL:
`https://phantom-traders-api.onrender.com/webhooks/stripe`

---

## API Endpoints

### Auth
```
POST /auth/signup        Create account
POST /auth/login         Login
GET  /auth/me            Get current user profile
POST /auth/logout        Logout
```

### Subscriptions
```
POST /subscriptions/checkout     Create Stripe checkout session → returns checkout_url
POST /subscriptions/portal       Get billing portal URL
GET  /subscriptions/status/{id}  Get user's plan + status
```

### Discord
```
POST /discord/link           Link Discord account + assign role
POST /discord/sync/{user_id} Force re-sync Discord role
GET  /discord/status/{id}    Check if Discord is linked
```

### Webhooks (called by Stripe, not your frontend)
```
POST /webhooks/stripe    Stripe event handler
```

---

## How the Payment Flow Works

```
1. User clicks "Start Pro Trial" on your site
2. Frontend calls POST /subscriptions/checkout with user_id + price_id
3. Backend creates Stripe Checkout session → returns checkout_url
4. Frontend redirects user to checkout_url (Stripe-hosted page)
5. User enters card on Stripe's secure page
6. Stripe calls your webhook POST /webhooks/stripe
7. Backend updates user's plan in Supabase
8. Backend assigns Discord role automatically
9. User lands back on your site with active subscription
```

---

## Testing Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in env file
cp .env.example .env

# Run the server
uvicorn app.main:app --reload --port 8000

# API docs available at:
# http://localhost:8000/docs
```

For local Stripe webhooks, install Stripe CLI:
```bash
stripe listen --forward-to localhost:8000/webhooks/stripe
```
This gives you a local webhook secret to use during testing.
