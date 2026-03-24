"""
Phantom Traders — Email Service (Resend)
Place in: Phantom-traders-backend/app/routers/email_service.py
Requires: pip install resend
Set env var: RESEND_API_KEY=re_xxxx
"""

import resend
import os
from datetime import datetime

resend.api_key = os.environ.get("RESEND_API_KEY", "")

FROM_ADDRESS = "Phantom Traders <noreply@aiphantomtraders.com>"
REPLY_TO = "support@aiphantomtraders.com"

STYLES = """
  body { margin:0; padding:0; background:#0a0c0f; font-family:'Helvetica Neue',Arial,sans-serif; }
  .wrapper { max-width:580px; margin:0 auto; background:#0f1217; }
  .header { padding:32px 40px 24px; border-bottom:1px solid #1c2330; }
  .logo { font-size:18px; font-weight:700; letter-spacing:3px; color:#e8ecf0; font-family:monospace; }
  .logo span { color:#00e5a0; }
  .body { padding:36px 40px; }
  .footer { padding:24px 40px; border-top:1px solid #1c2330; }
  .footer p { font-size:11px; color:#4a5568; font-family:monospace; margin:4px 0; }
  h1 { font-size:28px; font-weight:800; color:#e8ecf0; letter-spacing:1px; margin:0 0 12px; }
  p { font-size:15px; color:#6b7a8d; line-height:1.7; margin:0 0 16px; }
  .highlight { color:#e8ecf0; }
  .green { color:#00e5a0; }
  .gold { color:#f5c842; }
  .btn { display:inline-block; background:#00e5a0; color:#000; font-weight:700;
         font-size:14px; padding:14px 32px; border-radius:8px; text-decoration:none;
         letter-spacing:.3px; margin:8px 0; }
  .btn-ghost { display:inline-block; border:1px solid #2d3748; color:#6b7a8d;
               font-size:13px; padding:10px 24px; border-radius:8px; text-decoration:none; }
  .stat-row { display:flex; gap:0; margin:24px 0; border:1px solid #1c2330; border-radius:12px; overflow:hidden; }
  .stat { flex:1; padding:16px; text-align:center; border-right:1px solid #1c2330; }
  .stat:last-child { border-right:none; }
  .stat-val { font-size:22px; font-weight:700; color:#00e5a0; font-family:monospace; }
  .stat-label { font-size:10px; color:#4a5568; text-transform:uppercase; letter-spacing:.8px; margin-top:4px; }
  .card { background:#151920; border:1px solid #1c2330; border-radius:12px; padding:20px 24px; margin:16px 0; }
  .divider { height:1px; background:#1c2330; margin:24px 0; }
  .badge { display:inline-block; font-size:10px; font-weight:700; font-family:monospace;
           padding:3px 10px; border-radius:100px; letter-spacing:.5px; }
  .badge-green { background:rgba(0,229,160,.12); color:#00e5a0; }
  .badge-gold { background:rgba(245,200,66,.12); color:#f5c842; }
"""

def _base_template(content: str, preheader: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phantom Traders</title>
<style>{STYLES}</style>
</head>
<body>
{'<div style="display:none;max-height:0;overflow:hidden;">'+preheader+'</div>' if preheader else ''}
<div class="wrapper">
  <div class="header">
    <div class="logo">PHANTOM <span>TRADERS</span></div>
  </div>
  {content}
  <div class="footer">
    <p>© {datetime.now().year} Phantom Traders LLC · Dallas, Texas</p>
    <p>You're receiving this because you have an account at <a href="https://aiphantomtraders.com" style="color:#4a5568;">aiphantomtraders.com</a></p>
    <p><a href="https://aiphantomtraders.com/unsubscribe" style="color:#4a5568;">Unsubscribe</a> · <a href="https://aiphantomtraders.com/#privacy" style="color:#4a5568;">Privacy Policy</a></p>
  </div>
</div>
</body>
</html>"""


def _send(to: str, subject: str, html: str) -> bool:
    """Unified send function using Resend SDK."""
    try:
        params: resend.Emails.SendParams = {
            "from": FROM_ADDRESS,
            "to": [to],
            "reply_to": REPLY_TO,
            "subject": subject,
            "html": html,
        }
        resend.Emails.send(params)
        return True
    except Exception as e:
        print(f"Resend error: {e}")
        return False


# ── 1. Welcome Email ──────────────────────────────────────────
def send_welcome_email(to_email: str, first_name: str) -> bool:
    content = f"""
    <div class="body">
      <h1>Welcome to Phantom Traders, {first_name}.</h1>
      <p class="highlight">Your institutional-grade portfolio dashboard is ready. Here's how to get the most out of it in the next 5 minutes:</p>
      <div class="card">
        <p style="margin:0 0 12px;font-size:13px;font-weight:700;color:#e8ecf0;">🚀 GET STARTED IN 3 STEPS</p>
        <p style="margin:0 0 8px;"><span class="green">01 &nbsp;</span><span class="highlight">Add your holdings</span> — enter your tickers, shares, and cost basis. Live prices load automatically.</p>
        <p style="margin:0 0 8px;"><span class="green">02 &nbsp;</span><span class="highlight">Check your risk score</span> — your AI-powered score updates on every price tick.</p>
        <p style="margin:0;"><span class="green">03 &nbsp;</span><span class="highlight">Set a price alert</span> — get notified the moment your target is hit.</p>
      </div>
      <div style="text-align:center;margin:32px 0;">
        <a href="https://aiphantomtraders.com/#demo" class="btn">Open Your Dashboard →</a>
      </div>
      <div class="divider"></div>
      <p style="font-size:13px;">You're on the <span class="badge badge-green">FREE PLAN</span> — upgrade to Pro for real-time data, AI risk scoring, and unlimited holdings.</p>
      <a href="https://aiphantomtraders.com/#pricing" class="btn-ghost">View Pro Plans →</a>
    </div>"""
    return _send(to_email, "Welcome to Phantom Traders — your dashboard is ready", _base_template(content, f"Your portfolio dashboard is live, {first_name}."))


# ── 2. Upgrade / Payment Confirmation ────────────────────────
def send_upgrade_email(to_email: str, first_name: str, plan: str, amount: str, billing: str = "monthly") -> bool:
    plan_cap = plan.capitalize()
    badge_class = "badge-gold" if plan == "elite" else "badge-green"
    features = {
        "pro":   ["Unlimited holdings", "Real-time Finnhub prices", "AI risk scoring", "Tax harvesting engine", "Email price alerts", "Stock screener + AI recs"],
        "elite": ["Everything in Pro", "Discord Community included", "Multi-portfolio management", "Advanced AI insights", "Priority support", "API access + webhooks"],
    }.get(plan, [])
    discord_block = """<div class="card"><p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#e8ecf0;">💬 JOIN THE DISCORD</p><p style="margin:0;font-size:13px;">Your Elite plan includes full Discord access — live signals, pre-market voice calls, and a community of serious traders.</p><br><a href="https://discord.gg/cU9ywjWh" class="btn-ghost">Join Discord Server →</a></div>""" if plan == "elite" else ""
    content = f"""
    <div class="body">
      <p style="font-size:12px;font-family:monospace;color:#00e5a0;letter-spacing:1px;margin-bottom:8px;">✦ PAYMENT CONFIRMED</p>
      <h1>You're now on {plan_cap}.</h1>
      <p class="highlight">Thank you, {first_name}. Your {plan_cap} plan is active and all features are unlocked.</p>
      <div class="stat-row">
        <div class="stat"><div class="stat-val">{plan_cap}</div><div class="stat-label">Plan</div></div>
        <div class="stat"><div class="stat-val">{amount}</div><div class="stat-label">Charged</div></div>
        <div class="stat"><div class="stat-val">{billing.capitalize()}</div><div class="stat-label">Billing</div></div>
      </div>
      <div class="card">
        <p style="margin:0 0 12px;font-size:13px;font-weight:700;color:#e8ecf0;"><span class="badge {badge_class}">{plan_cap.upper()}</span> &nbsp;WHAT'S NOW UNLOCKED</p>
        {''.join(f'<p style="margin:0 0 6px;font-size:13px;"><span class="green">✓</span> &nbsp;{f}</p>' for f in features)}
      </div>
      <div style="text-align:center;margin:32px 0;">
        <a href="https://aiphantomtraders.com/#demo" class="btn">Open Your Dashboard →</a>
      </div>
      {discord_block}
      <div class="divider"></div>
      <p style="font-size:13px;">To manage your subscription visit <a href="https://aiphantomtraders.com/#account" style="color:#00e5a0;">Account Settings</a>. Questions? Reply to this email.</p>
    </div>"""
    return _send(to_email, f"You're on {plan_cap} — welcome to the next level", _base_template(content, f"Your {plan_cap} plan is active. All features unlocked."))


# ── 3. Price Alert Triggered ──────────────────────────────────
def send_alert_email(to_email: str, first_name: str, symbol: str, condition: str, target: float, current_price: float) -> bool:
    direction = "above" if condition == "above" else "below"
    color = "#00e5a0" if condition == "above" else "#ff4d6a"
    arrow = "▲" if condition == "above" else "▼"
    move_pct = abs((current_price - target) / target * 100) if target else 0
    content = f"""
    <div class="body">
      <p style="font-size:12px;font-family:monospace;color:{color};letter-spacing:1px;margin-bottom:8px;">{arrow} PRICE ALERT TRIGGERED</p>
      <h1>{symbol} hit your target.</h1>
      <p class="highlight">{first_name}, your price alert for <strong>{symbol}</strong> just triggered.</p>
      <div class="stat-row">
        <div class="stat"><div class="stat-val" style="color:{color};">${current_price:.2f}</div><div class="stat-label">Current Price</div></div>
        <div class="stat"><div class="stat-val">${target:.2f}</div><div class="stat-label">Your Target</div></div>
        <div class="stat"><div class="stat-val" style="color:{color};">{arrow} {move_pct:.1f}%</div><div class="stat-label">vs Target</div></div>
      </div>
      <div class="card">
        <p style="margin:0;font-size:14px;color:#e8ecf0;"><strong>{symbol}</strong> is trading <strong style="color:{color};">{direction} your target of ${target:.2f}</strong> at <strong>${current_price:.2f}</strong>.</p>
      </div>
      <div style="text-align:center;margin:32px 0;">
        <a href="https://aiphantomtraders.com/#demo" class="btn">View in Dashboard →</a>
      </div>
      <div class="divider"></div>
      <p style="font-size:13px;">Set a new alert in your <a href="https://aiphantomtraders.com/#demo" style="color:#00e5a0;">Alerts dashboard</a>.</p>
    </div>"""
    return _send(to_email, f"🔔 {symbol} alert triggered — now ${current_price:.2f}", _base_template(content, f"{symbol} crossed your ${target:.2f} target. Now at ${current_price:.2f}."))


# ── 4. Weekly Digest ──────────────────────────────────────────
def send_weekly_digest(to_email: str, first_name: str, portfolio_value: float, week_change: float, week_change_pct: float, top_mover: dict = None) -> bool:
    change_color = "#00e5a0" if week_change >= 0 else "#ff4d6a"
    arrow = "▲" if week_change >= 0 else "▼"
    sign = "+" if week_change >= 0 else "-"
    top_mover_html = ""
    if top_mover:
        tm_color = "#00e5a0" if top_mover.get("change", 0) >= 0 else "#ff4d6a"
        top_mover_html = f"""<div class="card"><p style="margin:0 0 8px;font-size:11px;font-family:monospace;color:#4a5568;text-transform:uppercase;letter-spacing:.8px;">Top Mover This Week</p><p style="margin:0;font-size:16px;font-weight:700;color:#e8ecf0;">{top_mover.get('symbol')} &nbsp;<span style="color:{tm_color};">{sign}{abs(top_mover.get('change', 0)):.1f}%</span></p></div>"""
    content = f"""
    <div class="body">
      <p style="font-size:12px;font-family:monospace;color:#4a5568;letter-spacing:1px;margin-bottom:8px;">WEEKLY PORTFOLIO DIGEST</p>
      <h1>Your week in review, {first_name}.</h1>
      <div class="stat-row">
        <div class="stat"><div class="stat-val">${portfolio_value:,.0f}</div><div class="stat-label">Portfolio Value</div></div>
        <div class="stat"><div class="stat-val" style="color:{change_color};">{arrow} {sign}${abs(week_change):,.0f}</div><div class="stat-label">7-Day Change</div></div>
        <div class="stat"><div class="stat-val" style="color:{change_color};">{sign}{abs(week_change_pct):.1f}%</div><div class="stat-label">7-Day Return</div></div>
      </div>
      {top_mover_html}
      <div class="card">
        <p style="margin:0 0 10px;font-size:13px;font-weight:700;color:#e8ecf0;">📊 THIS WEEK IN MARKETS</p>
        <p style="margin:0 0 6px;font-size:13px;">Check your AI risk score — it updates with every price move and flags concentration risk before it costs you.</p>
        <p style="margin:0;font-size:13px;">Review your Tax Harvesting panel for any loss opportunities before the quarter ends.</p>
      </div>
      <div style="text-align:center;margin:32px 0;">
        <a href="https://aiphantomtraders.com/#demo" class="btn">Open Dashboard →</a>
      </div>
      <div class="divider"></div>
      <p style="font-size:12px;color:#4a5568;">⚠️ Not financial advice. Past performance is not indicative of future results.</p>
    </div>"""
    return _send(to_email, f"Your weekly portfolio digest — {arrow} {sign}{abs(week_change_pct):.1f}% this week", _base_template(content, f"Portfolio: ${portfolio_value:,.0f} · Week: {sign}{abs(week_change_pct):.1f}%"))
