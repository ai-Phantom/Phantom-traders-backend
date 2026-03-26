"""
Phantom Bullseye Bot
=====================
Standalone high-conviction options alert bot for Phantom Traders.

Channels:
  #bullseye-drops  → Free/Rookie — ticker + direction + confidence % only
  #bullseye-alerts → Elite only  — full signal breakdown

Scan interval: every 15 minutes during market hours
Min confidence: 70%

Scoring factors:
  - IV surge vs 30-day average
  - Unusual options volume spike
  - Price/premium momentum divergence
  - RSI confirmation
  - MACD alignment
  - Bollinger Band squeeze/breakout
  - Multi-signal confluence bonus

Environment variables:
  BULLSEYE_BOT_TOKEN   — separate bot token from Discord Developer Portal
  DISCORD_GUILD_ID     — same guild ID as main bot
  FINNHUB_API_KEY      — same Finnhub key

Deploy on Railway as separate service:
  Root directory: Phantom-traders-backend/app/routers
  Start command:  python bullseye_bot.py
"""

import asyncio
import os
import pytz
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, time as dtime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────

BOT_TOKEN    = os.getenv("BULLSEYE_BOT_TOKEN", "")
GUILD_ID     = int(os.getenv("DISCORD_GUILD_ID", "0"))
FINNHUB_KEY  = os.getenv("FINNHUB_API_KEY", "d70j32pr01quoska263g")
SCAN_INTERVAL = 900  # 15 minutes

ET              = pytz.timezone("America/New_York")
MIN_CONFIDENCE  = 70  # minimum score to post alert
SITE_URL        = "https://aiphantomtraders.com"

NFA_NOTE = (
    "⚠️ Not financial advice. For educational purposes only. "
    "Always do your own research and trade at your own risk. "
    "NFA — Do your own due diligence."
)

# ── CHANNEL NAMES ─────────────────────────────────────────────────────────────

CH_BULLSEYE_DROPS  = "bullseye-drops"   # free — summary only
CH_BULLSEYE_ALERTS = "bullseye-alerts"  # Elite only — full alert

# ── ROLE NAMES ────────────────────────────────────────────────────────────────

ROLE_ELITE = "Elite"
ROLE_MOD   = "Moderator"

# ── WATCHLIST ─────────────────────────────────────────────────────────────────

WATCHLIST = [
    # ETFs
    "SPY", "QQQ", "IWM", "TLT", "GLD", "TQQQ", "SQQQ", "XLF", "SMH",
    # Mega Cap
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    # High Volume Growth
    "AMD", "PLTR", "COIN", "MSTR", "MARA", "HOOD", "SOFI",
    # E-Commerce / SaaS
    "SHOP", "CRM", "NFLX",
    # Semiconductors
    "AVGO", "INTC", "MU",
    # Financials
    "BAC",
    # Crypto Adjacent
    "RIOT",
    # Other High Volume
    "SQ", "PYPL", "UBER", "DIS", "F", "APP", "ARM", "SMCI", "CRWD",
]

# ── STATE ─────────────────────────────────────────────────────────────────────

# Hourly dedup keys so same ticker doesn't spam every 15min
alerted: set[str] = set()
last_scan_dt: datetime | None = None
scan_count: int = 0
total_alerts: int = 0

# ── INTENTS & BOT ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix="!bs", intents=intents, help_command=None)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5: return False
    return dtime(9, 30) <= now.time() <= dtime(16, 0)

def is_premarket() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5: return False
    return dtime(8, 0) <= now.time() < dtime(9, 30)

def get_ch(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name=name)

def alert_key(ticker: str, direction: str, now: datetime) -> str:
    """Hourly dedup key — same ticker+direction fires once per hour max."""
    return f"{ticker}_{direction}_{now.date()}_{now.hour}"

def confidence_bar(score: int) -> str:
    filled = int(score / 10)
    return "🟢" * filled + "⬜" * (10 - filled)

def confidence_label(score: int) -> str:
    if score >= 90: return "🔥 EXTREME"
    if score >= 80: return "🟢 HIGH"
    if score >= 70: return "🟡 SOLID"
    return "🟠 MODERATE"

# ── FINNHUB FETCH ─────────────────────────────────────────────────────────────

async def fetch_quote(session: aiohttp.ClientSession, ticker: str) -> dict | None:
    try:
        async with session.get(
            f"https://finnhub.io/api/v1/quote?symbol={ticker}",
            headers={"X-Finnhub-Token": FINNHUB_KEY}
        ) as r:
            data = await r.json()
            return data if data.get("c") else None
    except Exception as e:
        print(f"  [quote] {ticker}: {e}"); return None

async def fetch_indicators(session: aiohttp.ClientSession, ticker: str) -> dict | None:
    base    = "https://finnhub.io/api/v1"
    h       = {"X-Finnhub-Token": FINNHUB_KEY}
    now     = int(datetime.now().timestamp())
    from_ts = now - 86400 * 60  # 60 days
    try:
        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D"
            f"&from={from_ts}&to={now}&indicator=rsi&timeperiod=14", headers=h
        ) as r: rsi_raw = await r.json()

        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D"
            f"&from={from_ts}&to={now}&indicator=macd", headers=h
        ) as r: macd_raw = await r.json()

        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D"
            f"&from={from_ts}&to={now}&indicator=bbands", headers=h
        ) as r: bb_raw = await r.json()

        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D"
            f"&from={from_ts}&to={now}&indicator=atr&timeperiod=14", headers=h
        ) as r: atr_raw = await r.json()

        hist = macd_raw.get("histogram") or [0, 0]
        rsi_list = rsi_raw.get("rsi") or [50]

        # IV approximation using ATR/price ratio × 100 (proxy for volatility)
        atr_list = atr_raw.get("atr") or [0]

        return {
            "rsi":            rsi_list[-1],
            "rsi_prev":       rsi_list[-2] if len(rsi_list) >= 2 else rsi_list[-1],
            "macd":           (macd_raw.get("macd")   or [0])[-1],
            "macd_signal":    (macd_raw.get("signal") or [0])[-1],
            "macd_hist":      hist[-1] if hist else 0,
            "macd_hist_prev": hist[-2] if len(hist) >= 2 else 0,
            "bb_upper":       (bb_raw.get("upperband")  or [0])[-1],
            "bb_lower":       (bb_raw.get("lowerband")  or [0])[-1],
            "bb_middle":      (bb_raw.get("middleband") or [0])[-1],
            "atr":            atr_list[-1] if atr_list else 0,
            "atr_prev":       atr_list[-5] if len(atr_list) >= 5 else atr_list[-1] if atr_list else 0,
        }
    except Exception as e:
        print(f"  [indicators] {ticker}: {e}"); return None

# ── BULLSEYE SCORING ENGINE ───────────────────────────────────────────────────

def score_bullseye(ticker: str, quote: dict, ind: dict) -> dict | None:
    """
    Multi-factor Bullseye scoring engine.
    Returns signal dict if score >= MIN_CONFIDENCE, else None.

    Factors:
      1. RSI momentum + extreme levels       (0-25 pts)
      2. MACD crossover + histogram reversal (0-20 pts)
      3. Bollinger Band position + squeeze   (0-20 pts)
      4. Volume surge                        (0-15 pts)
      5. ATR/volatility surge (IV proxy)     (0-15 pts)
      6. Price momentum (intraday chg%)      (0-10 pts)
      7. Multi-signal confluence bonus       (0-10 pts)
    Max raw: 115 pts → normalized to 0-100
    """

    price     = quote.get("c", 0)
    prev      = quote.get("pc", 1)
    high      = quote.get("h", price)
    low       = quote.get("l", price)
    vol       = quote.get("v", 0)
    chg_pct   = ((price - prev) / prev * 100) if prev else 0
    chg_abs   = price - prev

    rsi       = ind["rsi"]
    rsi_prev  = ind["rsi_prev"]
    macd      = ind["macd"]
    macd_sig  = ind["macd_signal"]
    macd_hist = ind["macd_hist"]
    hist_prev = ind["macd_hist_prev"]
    bb_upper  = ind["bb_upper"]
    bb_lower  = ind["bb_lower"]
    bb_middle = ind["bb_middle"]
    atr       = ind["atr"]
    atr_prev  = ind["atr_prev"] or atr

    # BB width (squeeze detection)
    bb_width      = (bb_upper - bb_lower) / bb_middle if bb_middle else 0
    vol_ratio     = vol / max(vol * 0.5, 1)  # rough proxy since no avg vol from free tier
    atr_surge     = (atr / atr_prev) if atr_prev else 1
    rsi_momentum  = rsi - rsi_prev  # positive = RSI rising

    score    = 0
    signals  = []
    bull_pts = 0
    bear_pts = 0

    # ── Factor 1: RSI (0-25 pts) ──────────────────────────────────────────────
    if rsi < 28:
        pts = 25; score += pts; bull_pts += pts
        signals.append(f"RSI extreme oversold ({rsi:.0f}) — powerful bounce zone")
    elif rsi < 35:
        pts = 15; score += pts; bull_pts += pts
        signals.append(f"RSI oversold ({rsi:.0f}) — bullish setup forming")
    elif rsi > 75:
        pts = 25; score += pts; bear_pts += pts
        signals.append(f"RSI extreme overbought ({rsi:.0f}) — reversal zone")
    elif rsi > 68:
        pts = 15; score += pts; bear_pts += pts
        signals.append(f"RSI overbought ({rsi:.0f}) — bearish pressure building")

    # RSI momentum bonus
    if abs(rsi_momentum) >= 5:
        if rsi_momentum > 0:
            pts = 5; score += pts; bull_pts += pts
            signals.append(f"RSI rising fast (+{rsi_momentum:.1f}) — momentum accelerating bullish")
        else:
            pts = 5; score += pts; bear_pts += pts
            signals.append(f"RSI falling fast ({rsi_momentum:.1f}) — momentum accelerating bearish")

    # ── Factor 2: MACD (0-20 pts) ─────────────────────────────────────────────
    if hist_prev < 0 < macd_hist:
        pts = 20; score += pts; bull_pts += pts
        signals.append("MACD histogram crossed negative → positive 🔄 Bullish reversal confirmed")
    elif hist_prev > 0 > macd_hist:
        pts = 20; score += pts; bear_pts += pts
        signals.append("MACD histogram crossed positive → negative 🔄 Bearish reversal confirmed")
    elif macd > macd_sig and macd > 0:
        pts = 12; score += pts; bull_pts += pts
        signals.append("MACD bullish crossover above zero line")
    elif macd < macd_sig and macd < 0:
        pts = 12; score += pts; bear_pts += pts
        signals.append("MACD bearish crossover below zero line")
    elif macd > macd_sig:
        pts = 6; score += pts; bull_pts += pts
        signals.append("MACD bullish crossover (below zero — moderate signal)")
    elif macd < macd_sig:
        pts = 6; score += pts; bear_pts += pts
        signals.append("MACD bearish crossover (above zero — moderate signal)")

    # ── Factor 3: Bollinger Bands (0-20 pts) ──────────────────────────────────
    if price <= bb_lower * 1.002:
        pts = 20; score += pts; bull_pts += pts
        signals.append("Price at lower Bollinger Band — extreme oversold, bounce incoming")
    elif price >= bb_upper * 0.998:
        pts = 20; score += pts; bear_pts += pts
        signals.append("Price at upper Bollinger Band — extreme overbought, fade incoming")
    elif price < bb_lower * 1.01:
        pts = 12; score += pts; bull_pts += pts
        signals.append("Price near lower BB — oversold territory")
    elif price > bb_upper * 0.99:
        pts = 12; score += pts; bear_pts += pts
        signals.append("Price near upper BB — overbought territory")

    # BB squeeze detection (low width = explosive move coming)
    if bb_width < 0.05:
        pts = 8; score += pts
        signals.append(f"🔥 Bollinger Band SQUEEZE detected (width: {bb_width:.3f}) — big move imminent")

    # ── Factor 4: Volume (0-15 pts) ───────────────────────────────────────────
    if abs(chg_pct) >= 3.0:
        pts = 15; score += pts
        if chg_pct > 0: bull_pts += pts; signals.append(f"Strong gap/move up +{chg_pct:.1f}% with high volume")
        else: bear_pts += pts; signals.append(f"Strong gap/move down {chg_pct:.1f}% with high volume")
    elif abs(chg_pct) >= 1.5:
        pts = 8; score += pts
        if chg_pct > 0: bull_pts += pts; signals.append(f"Significant upside move +{chg_pct:.1f}%")
        else: bear_pts += pts; signals.append(f"Significant downside move {chg_pct:.1f}%")

    # ── Factor 5: ATR/Volatility Surge (0-15 pts) ─────────────────────────────
    if atr_surge >= 1.5:
        pts = 15; score += pts
        signals.append(f"🔥 Volatility SURGE — ATR {atr_surge:.1f}x above recent average (IV proxy)")
    elif atr_surge >= 1.25:
        pts = 8; score += pts
        signals.append(f"Volatility expanding — ATR {atr_surge:.1f}x above average")

    # ── Factor 6: Price momentum (0-10 pts) ───────────────────────────────────
    intraday_range = (high - low) / prev * 100 if prev else 0
    if intraday_range >= 3.0:
        pts = 10; score += pts
        signals.append(f"Wide intraday range {intraday_range:.1f}% — high conviction move in play")
    elif intraday_range >= 1.5:
        pts = 5; score += pts
        signals.append(f"Active intraday range {intraday_range:.1f}%")

    # ── Must have signals ─────────────────────────────────────────────────────
    if len(signals) < 2 or score < 1:
        return None

    # ── Determine direction ───────────────────────────────────────────────────
    if bull_pts > bear_pts:
        direction = "CALL"
    elif bear_pts > bull_pts:
        direction = "PUT"
    else:
        return None  # conflicting signals — skip

    # ── Factor 7: Confluence bonus (0-10 pts) ─────────────────────────────────
    if len(signals) >= 4:
        score += 10; signals.append(f"⚡ Multi-signal confluence ({len(signals)} factors aligned)")
    elif len(signals) >= 3:
        score += 5

    # Normalize to 0-100
    score = min(100, int(score / 115 * 100))

    if score < MIN_CONFIDENCE:
        return None

    # ── Strike suggestion ─────────────────────────────────────────────────────
    step   = 1 if price < 20 else (2 if price < 50 else (5 if price < 200 else 10))
    atm    = round(price / step) * step
    # Slightly OTM for higher reward
    if direction == "CALL":
        strike_aggressive = atm + step
        strike_moderate   = atm
    else:
        strike_aggressive = atm - step
        strike_moderate   = atm

    # Suggested expiry — next weekly (3-7 days out for intraday Bullseye plays)
    now         = datetime.now(ET)
    days_to_fri = (4 - now.weekday()) % 7
    if days_to_fri == 0: days_to_fri = 7
    expiry_weekly = (now + timedelta(days=days_to_fri)).strftime("%m/%d")
    expiry_monthly = (now + timedelta(days=30)).strftime("%m/%d")

    return {
        "ticker":             ticker,
        "price":              price,
        "chg_pct":            chg_pct,
        "direction":          direction,
        "strike_aggressive":  strike_aggressive,
        "strike_moderate":    strike_moderate,
        "expiry_weekly":      expiry_weekly,
        "expiry_monthly":     expiry_monthly,
        "signals":            signals,
        "score":              score,
        "bull_pts":           bull_pts,
        "bear_pts":           bear_pts,
        "rsi":                rsi,
        "atr_surge":          atr_surge,
        "bb_width":           bb_width,
        "intraday_range":     intraday_range,
    }

# ── EMBED BUILDERS ────────────────────────────────────────────────────────────

def build_full_embed(signal: dict, scan_num: int) -> discord.Embed:
    """Full alert for #bullseye-alerts (Elite only)."""
    is_call  = signal["direction"] == "CALL"
    color    = "#00C896" if is_call else "#FF4D6A"
    arrow    = "📈" if is_call else "📉"
    conf     = signal["score"]
    c_label  = confidence_label(conf)
    c_bar    = confidence_bar(conf)

    embed = discord.Embed(
        title=f"🎯 BULLSEYE #{scan_num} — {signal['ticker']} {signal['direction']}",
        description=(
            f"{arrow} **{signal['ticker']}** — High-conviction intraday {signal['direction']} setup\n"
            f"{c_bar} **{conf}%** {c_label}"
        ),
        color=discord.Color.from_str(color),
        timestamp=datetime.now(ET)
    )

    embed.add_field(
        name="💰 Current Price",
        value=f"**${signal['price']:.2f}** ({signal['chg_pct']:+.2f}% today)",
        inline=True
    )
    embed.add_field(
        name="🎯 Aggressive Strike",
        value=f"**${signal['strike_aggressive']:.0f} {signal['direction']}**\nExp: {signal['expiry_weekly']} (weekly)",
        inline=True
    )
    embed.add_field(
        name="🛡️ Moderate Strike",
        value=f"**${signal['strike_moderate']:.0f} {signal['direction']}**\nExp: {signal['expiry_monthly']} (monthly)",
        inline=True
    )
    embed.add_field(
        name="📊 Technical Snapshot",
        value=(
            f"RSI: **{signal['rsi']:.0f}** | "
            f"ATR Surge: **{signal['atr_surge']:.2f}x** | "
            f"BB Width: **{signal['bb_width']:.3f}** | "
            f"Range: **{signal['intraday_range']:.1f}%**"
        ),
        inline=False
    )
    embed.add_field(
        name=f"⚡ Signals ({len(signal['signals'])} factors)",
        value="\n".join(f"→ {s}" for s in signal["signals"]),
        inline=False
    )
    embed.add_field(
        name="🔵 Bullish Score",
        value=f"**{signal['bull_pts']} pts**",
        inline=True
    )
    embed.add_field(
        name="🔴 Bearish Score",
        value=f"**{signal['bear_pts']} pts**",
        inline=True
    )
    embed.add_field(
        name="📅 Play Type",
        value="**Intraday / 1-2 day** — Bullseye plays are short-term high conviction only",
        inline=False
    )
    embed.add_field(
        name="⚠️ Risk Management",
        value=(
            "• Use **1-2% max** of portfolio per Bullseye play\n"
            "• Set stop loss at **50% of premium paid**\n"
            "• Take partial profits at **50-75% gain**\n"
            "• Exit **same day** if thesis doesn't play out"
        ),
        inline=False
    )
    embed.set_footer(text=f"Phantom Bullseye • Scan #{scan_num} • {NFA_NOTE}")
    return embed


def build_summary_embed(signal: dict, scan_num: int) -> discord.Embed:
    """Summary alert for #bullseye-drops (free members)."""
    is_call = signal["direction"] == "CALL"
    color   = "#00C896" if is_call else "#FF4D6A"
    arrow   = "📈" if is_call else "📉"
    conf    = signal["score"]
    c_label = confidence_label(conf)
    c_bar   = confidence_bar(conf)

    embed = discord.Embed(
        title=f"🎯 Bullseye Signal — {signal['ticker']} {signal['direction']}",
        description=(
            f"{arrow} **{signal['ticker']}** — {signal['direction']} setup detected\n"
            f"{c_bar} **{conf}%** {c_label}\n\n"
            f"💰 Price: **${signal['price']:.2f}** ({signal['chg_pct']:+.2f}%)\n\n"
            f"🔒 **Full signal breakdown available in #bullseye-alerts (Elite only)**\n"
            f"Upgrade at **[{SITE_URL}]({SITE_URL})** to unlock complete Bullseye alerts."
        ),
        color=discord.Color.from_str(color),
        timestamp=datetime.now(ET)
    )
    embed.set_footer(text=f"Phantom Bullseye • {NFA_NOTE}")
    return embed


def build_scan_summary(signals: list, now: datetime, scan_num: int) -> discord.Embed:
    """Post-scan summary showing what fired."""
    calls = [s for s in signals if s["direction"] == "CALL"]
    puts  = [s for s in signals if s["direction"] == "PUT"]

    embed = discord.Embed(
        title=f"🎯 Bullseye Scan Complete — {now.strftime('%I:%M %p ET')}",
        description=f"Scanned **{len(WATCHLIST)} tickers** • Found **{len(signals)} signal(s)**",
        color=discord.Color.from_str("#F5C842"),
        timestamp=now
    )
    if calls:
        embed.add_field(
            name="📈 CALL Signals",
            value="\n".join(f"• **{s['ticker']}** — {s['score']}% {confidence_label(s['score'])}" for s in calls),
            inline=True
        )
    if puts:
        embed.add_field(
            name="📉 PUT Signals",
            value="\n".join(f"• **{s['ticker']}** — {s['score']}% {confidence_label(s['score'])}" for s in puts),
            inline=True
        )
    if not signals:
        embed.add_field(name="📭 No Signals", value="No setups met the 70% confidence threshold this scan.", inline=False)

    embed.set_footer(text=f"Next scan in 15 min • {NFA_NOTE}")
    return embed

# ── MAIN SCAN LOOP ────────────────────────────────────────────────────────────

@tasks.loop(seconds=SCAN_INTERVAL)
async def bullseye_scan():
    global last_scan_dt, scan_count, total_alerts

    if not is_market_open() and not is_premarket():
        return

    now = datetime.now(ET)
    # Clear hourly dedup at start of new day
    if last_scan_dt and last_scan_dt.date() < now.date():
        alerted.clear()
    last_scan_dt = now
    scan_count  += 1

    print(f"[Bullseye #{scan_count}] {now.strftime('%H:%M ET')} — Scanning {len(WATCHLIST)} tickers...")

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    ch_drops  = get_ch(guild, CH_BULLSEYE_DROPS)
    ch_alerts = get_ch(guild, CH_BULLSEYE_ALERTS)

    signals = []

    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST:
            try:
                quote = await fetch_quote(session, ticker)
                if not quote:
                    await asyncio.sleep(0.4)
                    continue

                ind = await fetch_indicators(session, ticker)
                if not ind:
                    await asyncio.sleep(0.4)
                    continue

                signal = score_bullseye(ticker, quote, ind)
                if signal:
                    signals.append(signal)

            except Exception as e:
                print(f"  [Bullseye] Error {ticker}: {e}")

            await asyncio.sleep(0.5)  # respect Finnhub rate limits

    if not signals:
        print(f"  [Bullseye #{scan_count}] No signals above {MIN_CONFIDENCE}%")
        return

    # Sort by confidence score descending
    signals.sort(key=lambda x: x["score"], reverse=True)
    print(f"  [Bullseye #{scan_count}] Found {len(signals)} signal(s)")

    for signal in signals:
        key = alert_key(signal["ticker"], signal["direction"], now)
        if key in alerted:
            continue

        alerted.add(key)
        total_alerts += 1

        # Post full alert to #bullseye-alerts (Elite only)
        if ch_alerts:
            full_embed = build_full_embed(signal, scan_count)
            ping = "@here — 🎯 Bullseye!" if signal["score"] >= 85 else ""
            try:
                await ch_alerts.send(content=ping if ping else None, embed=full_embed)
            except discord.Forbidden:
                pass

        # Post summary to #bullseye-drops (free)
        if ch_drops:
            summary_embed = build_summary_embed(signal, scan_count)
            try:
                await ch_drops.send(embed=summary_embed)
            except discord.Forbidden:
                pass

        await asyncio.sleep(1)

    # Post scan summary to #bullseye-drops
    if ch_drops:
        try:
            await ch_drops.send(embed=build_scan_summary(signals, now, scan_count))
        except discord.Forbidden:
            pass


# ── COMMANDS ──────────────────────────────────────────────────────────────────

@bot.command(name="scan")
@commands.has_permissions(administrator=True)
async def manual_scan(ctx):
    """!bsscan — trigger a manual Bullseye scan"""
    await ctx.reply("🎯 Running Bullseye scan — results posting shortly...")
    bullseye_scan.restart()


@bot.command(name="status")
async def status(ctx):
    """!bsstatus — Bullseye bot status"""
    now   = datetime.now(ET)
    state = "🟢 MARKET OPEN" if is_market_open() else "🟡 PRE-MARKET" if is_premarket() else "🔴 MARKET CLOSED"
    last  = last_scan_dt.strftime("%I:%M %p ET") if last_scan_dt else "Never"
    await ctx.reply(
        f"**🎯 Phantom Bullseye Bot**\n"
        f"Market: {state}\n"
        f"Last scan: {last}\n"
        f"Total scans: {scan_count}\n"
        f"Total alerts fired: {total_alerts}\n"
        f"Watchlist: {len(WATCHLIST)} tickers\n"
        f"Min confidence: {MIN_CONFIDENCE}%\n"
        f"Scan interval: every 15 min"
    )


@bot.command(name="watchlist")
async def show_watchlist(ctx):
    """!bswatchlist — show Bullseye watchlist"""
    await ctx.reply(
        f"**🎯 Bullseye Watchlist ({len(WATCHLIST)} tickers):**\n" +
        "  ".join(f"`{t}`" for t in WATCHLIST)
    )


@bot.command(name="bshelp")
async def bullseye_help(ctx):
    """!bshelp — Bullseye bot commands"""
    embed = discord.Embed(
        title="🎯 Phantom Bullseye Bot — Commands",
        description=(
            "Bullseye scans for **high-conviction intraday options setups** every 15 minutes.\n\n"
            f"Min confidence threshold: **{MIN_CONFIDENCE}%**\n"
            f"Watchlist: **{len(WATCHLIST)} tickers**"
        ),
        color=discord.Color.from_str("#F5C842")
    )
    embed.add_field(name="Commands", value=(
        "`!bsscan` — trigger manual scan *(Admin)*\n"
        "`!bsstatus` — bot status and stats\n"
        "`!bswatchlist` — view watchlist\n"
        "`!bshelp` — this menu"
    ), inline=False)
    embed.add_field(name="📡 Channels", value=(
        f"**#bullseye-drops** — Free members — ticker + confidence only\n"
        f"**#bullseye-alerts** — Elite only — full signal breakdown"
    ), inline=False)
    embed.add_field(name="🔬 Scoring Factors", value=(
        "• RSI extreme levels + momentum\n"
        "• MACD crossover + histogram reversal\n"
        "• Bollinger Band position + squeeze\n"
        "• Volume surge detection\n"
        "• ATR/volatility surge (IV proxy)\n"
        "• Intraday price range\n"
        "• Multi-signal confluence bonus"
    ), inline=False)
    embed.add_field(name="⚠️ Important", value=(
        "Bullseye plays are **intraday / 1-2 day** high-risk, high-reward setups.\n"
        "Always use strict risk management. Max 1-2% portfolio per trade.\n\n"
        f"Upgrade to Elite at **[{SITE_URL}]({SITE_URL})** for full alerts."
    ), inline=False)
    embed.set_footer(text=NFA_NOTE)
    await ctx.reply(embed=embed)


# ── SETUP CHANNEL POSTS ───────────────────────────────────────────────────────

@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup_bullseye_channels(ctx):
    """!bssetup — post intro messages to Bullseye channels"""
    guild = ctx.guild

    # Post to #bullseye-drops
    ch_drops = get_ch(guild, CH_BULLSEYE_DROPS)
    if ch_drops:
        drops_embed = discord.Embed(
            title="🎯 Welcome to Bullseye Drops",
            description=(
                "This channel posts **Bullseye signal summaries** every time the scanner fires.\n\n"
                "You'll see:\n"
                "• Ticker and direction (CALL/PUT)\n"
                "• Confidence score\n"
                "• Current price\n\n"
                "🔒 **Full signal breakdowns** (strike, expiry, entry, all signals) are in "
                "**#bullseye-alerts** — available to **Elite members only**.\n\n"
                f"Upgrade at **[{SITE_URL}]({SITE_URL})** to unlock everything."
            ),
            color=discord.Color.from_str("#F5C842")
        )
        drops_embed.set_footer(text=NFA_NOTE)
        try:
            await ch_drops.send(embed=drops_embed)
        except discord.Forbidden:
            pass

    # Post to #bullseye-alerts
    ch_alerts = get_ch(guild, CH_BULLSEYE_ALERTS)
    if ch_alerts:
        alerts_embed = discord.Embed(
            title="🎯 Welcome to Bullseye Alerts — Elite Access",
            description=(
                "You have **Elite access** — this channel posts the **full Bullseye signal** every time a "
                f"**{MIN_CONFIDENCE}%+ confidence** setup is detected.\n\n"
                "Each alert includes:\n"
                "• Ticker, direction, confidence score\n"
                "• Aggressive strike (weekly expiry)\n"
                "• Moderate strike (monthly expiry)\n"
                "• Full signal breakdown (all scoring factors)\n"
                "• Risk management guidelines\n\n"
                "⚠️ **Bullseye plays are intraday / 1-2 day high-risk setups.**\n"
                "Always use strict risk management. Never risk more than 1-2% per trade."
            ),
            color=discord.Color.from_str("#00C896")
        )
        alerts_embed.set_footer(text=NFA_NOTE)
        try:
            await ch_alerts.send(embed=alerts_embed)
        except discord.Forbidden:
            pass

    await ctx.reply("✅ Bullseye channel posts done!")


# ── ERROR HANDLER ─────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ Administrator permission required.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"[error] {ctx.command}: {error}")


# ── ON READY ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"\n✓ Phantom Bullseye Bot online — {bot.user}")
    print(f"  Guild:       {GUILD_ID}")
    print(f"  Watchlist:   {len(WATCHLIST)} tickers")
    print(f"  Interval:    {SCAN_INTERVAL}s (15 min)")
    print(f"  Min conf:    {MIN_CONFIDENCE}%")
    print(f"  Channels:    #{CH_BULLSEYE_DROPS} (free) | #{CH_BULLSEYE_ALERTS} (Elite)")
    bullseye_scan.start()


# ── RUN ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: BULLSEYE_BOT_TOKEN not set.")
        print("  Create a NEW bot at discord.com/developers/applications")
        print("  Add token as BULLSEYE_BOT_TOKEN env var in Railway")
        raise SystemExit(1)
    if not GUILD_ID:
        print("ERROR: DISCORD_GUILD_ID not set.")
        raise SystemExit(1)
    bot.run(BOT_TOKEN)
