"""
Phantom Bullseye Bot
=====================
Standalone high-conviction options alert bot for Phantom Traders.

Channels:
  #bullseye-drops  → Free/Rookie — ticker + direction + confidence % only
  #bullseye-alerts → Elite only  — full signal breakdown

Scan interval: every 15 minutes during market hours
Min confidence: 70%

Environment variables:
  BULLSEYE_BOT_TOKEN   — separate bot token
  DISCORD_GUILD_ID     — same guild ID as main bot
  FINNHUB_API_KEY      — same Finnhub key

Start command: python bullseye_bot.py
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

BOT_TOKEN     = os.getenv("BULLSEYE_BOT_TOKEN", "")
GUILD_ID      = int(os.getenv("DISCORD_GUILD_ID", "0"))
FINNHUB_KEY   = os.getenv("FINNHUB_API_KEY", "d70j32pr01quoska263g")
SCAN_INTERVAL = 900  # 15 minutes
MIN_CONFIDENCE = 70
SITE_URL      = "https://aiphantomtraders.com"
ET            = pytz.timezone("America/New_York")

NFA_NOTE = (
    "⚠️ Not financial advice. For educational purposes only. "
    "Always do your own research and trade at your own risk. "
    "NFA — Do your own due diligence."
)

# ── CHANNELS & ROLES ─────────────────────────────────────────────────────────

CH_BULLSEYE_DROPS  = "bullseye-drops"
CH_BULLSEYE_ALERTS = "bullseye-alerts"
ROLE_ELITE = "Elite"
ROLE_MOD   = "Moderator"

# ── WATCHLIST ─────────────────────────────────────────────────────────────────

WATCHLIST = [
    "SPY", "QQQ", "IWM", "TLT", "GLD", "TQQQ", "SQQQ", "XLF", "SMH",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "AMD", "PLTR", "COIN", "MSTR", "MARA", "HOOD", "SOFI",
    "SHOP", "CRM", "NFLX", "AVGO", "INTC", "MU", "BAC", "RIOT",
    "SQ", "PYPL", "UBER", "DIS", "F", "APP", "ARM", "SMCI", "CRWD",
]

# ── STATE ─────────────────────────────────────────────────────────────────────

alerted:      set[str]        = set()
last_scan_dt: datetime | None = None
scan_count:   int             = 0
total_alerts: int             = 0

# ── INTENTS & BOT ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.guilds          = True
intents.members         = True
intents.message_content = True

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

def get_ch(guild, name):
    return discord.utils.get(guild.text_channels, name=name)

def alert_key(ticker, direction, now):
    return f"{ticker}_{direction}_{now.date()}_{now.hour}"

def confidence_bar(score):
    filled = int(score / 10)
    return "🟢" * filled + "⬜" * (10 - filled)

def confidence_label(score):
    if score >= 90: return "🔥 EXTREME"
    if score >= 80: return "🟢 HIGH"
    if score >= 70: return "🟡 SOLID"
    return "🟠 MODERATE"

# ── FINNHUB FETCH ─────────────────────────────────────────────────────────────

async def fetch_quote(session, ticker):
    try:
        async with session.get(
            f"https://finnhub.io/api/v1/quote?symbol={ticker}",
            headers={"X-Finnhub-Token": FINNHUB_KEY}
        ) as r:
            data = await r.json()
            return data if data.get("c") else None
    except Exception as e:
        print(f"  [quote] {ticker}: {e}"); return None

async def fetch_indicators(session, ticker):
    base    = "https://finnhub.io/api/v1"
    h       = {"X-Finnhub-Token": FINNHUB_KEY}
    now     = int(datetime.now().timestamp())
    from_ts = now - 86400 * 60
    try:
        async with session.get(f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=rsi&timeperiod=14", headers=h) as r:
            rsi_raw = await r.json()
        async with session.get(f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=macd", headers=h) as r:
            macd_raw = await r.json()
        async with session.get(f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=bbands", headers=h) as r:
            bb_raw = await r.json()
        async with session.get(f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=atr&timeperiod=14", headers=h) as r:
            atr_raw = await r.json()

        hist     = macd_raw.get("histogram") or [0, 0]
        rsi_list = rsi_raw.get("rsi") or [50]
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
            "atr_prev":       atr_list[-5] if len(atr_list) >= 5 else (atr_list[-1] if atr_list else 0),
        }
    except Exception as e:
        print(f"  [indicators] {ticker}: {e}"); return None

# ── SCORING ENGINE ────────────────────────────────────────────────────────────

def score_bullseye(ticker, quote, ind):
    price     = quote.get("c", 0)
    prev      = quote.get("pc", 1)
    high      = quote.get("h", price)
    low       = quote.get("l", price)
    chg_pct   = ((price - prev) / prev * 100) if prev else 0
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

    bb_width      = (bb_upper - bb_lower) / bb_middle if bb_middle else 0
    atr_surge     = (atr / atr_prev) if atr_prev else 1
    rsi_momentum  = rsi - rsi_prev
    intraday_range = (high - low) / prev * 100 if prev else 0

    score    = 0
    signals  = []
    bull_pts = 0
    bear_pts = 0

    # RSI
    if rsi < 28:
        score += 25; bull_pts += 25; signals.append(f"RSI extreme oversold ({rsi:.0f}) — powerful bounce zone")
    elif rsi < 35:
        score += 15; bull_pts += 15; signals.append(f"RSI oversold ({rsi:.0f}) — bullish setup forming")
    elif rsi > 75:
        score += 25; bear_pts += 25; signals.append(f"RSI extreme overbought ({rsi:.0f}) — reversal zone")
    elif rsi > 68:
        score += 15; bear_pts += 15; signals.append(f"RSI overbought ({rsi:.0f}) — bearish pressure building")

    if abs(rsi_momentum) >= 5:
        if rsi_momentum > 0:
            score += 5; bull_pts += 5; signals.append(f"RSI rising fast (+{rsi_momentum:.1f}) — bullish momentum")
        else:
            score += 5; bear_pts += 5; signals.append(f"RSI falling fast ({rsi_momentum:.1f}) — bearish momentum")

    # MACD
    if hist_prev < 0 < macd_hist:
        score += 20; bull_pts += 20; signals.append("MACD histogram crossed negative → positive 🔄 Bullish reversal")
    elif hist_prev > 0 > macd_hist:
        score += 20; bear_pts += 20; signals.append("MACD histogram crossed positive → negative 🔄 Bearish reversal")
    elif macd > macd_sig and macd > 0:
        score += 12; bull_pts += 12; signals.append("MACD bullish crossover above zero")
    elif macd < macd_sig and macd < 0:
        score += 12; bear_pts += 12; signals.append("MACD bearish crossover below zero")
    elif macd > macd_sig:
        score += 6; bull_pts += 6; signals.append("MACD bullish crossover")
    elif macd < macd_sig:
        score += 6; bear_pts += 6; signals.append("MACD bearish crossover")

    # Bollinger Bands
    if price <= bb_lower * 1.002:
        score += 20; bull_pts += 20; signals.append("Price at lower BB — extreme oversold, bounce incoming")
    elif price >= bb_upper * 0.998:
        score += 20; bear_pts += 20; signals.append("Price at upper BB — extreme overbought, fade incoming")
    elif price < bb_lower * 1.01:
        score += 12; bull_pts += 12; signals.append("Price near lower BB — oversold territory")
    elif price > bb_upper * 0.99:
        score += 12; bear_pts += 12; signals.append("Price near upper BB — overbought territory")

    if bb_width < 0.05:
        score += 8; signals.append(f"🔥 BB SQUEEZE detected (width: {bb_width:.3f}) — big move imminent")

    # Price momentum
    if abs(chg_pct) >= 3.0:
        score += 15
        if chg_pct > 0: bull_pts += 15; signals.append(f"Strong move up +{chg_pct:.1f}%")
        else: bear_pts += 15; signals.append(f"Strong move down {chg_pct:.1f}%")
    elif abs(chg_pct) >= 1.5:
        score += 8
        if chg_pct > 0: bull_pts += 8; signals.append(f"Significant upside +{chg_pct:.1f}%")
        else: bear_pts += 8; signals.append(f"Significant downside {chg_pct:.1f}%")

    # ATR surge
    if atr_surge >= 1.5:
        score += 15; signals.append(f"🔥 Volatility SURGE — ATR {atr_surge:.1f}x above average")
    elif atr_surge >= 1.25:
        score += 8; signals.append(f"Volatility expanding — ATR {atr_surge:.1f}x above average")

    # Intraday range
    if intraday_range >= 3.0:
        score += 10; signals.append(f"Wide intraday range {intraday_range:.1f}% — high conviction move")
    elif intraday_range >= 1.5:
        score += 5; signals.append(f"Active intraday range {intraday_range:.1f}%")

    if len(signals) < 2 or score < 1: return None

    if bull_pts > bear_pts: direction = "CALL"
    elif bear_pts > bull_pts: direction = "PUT"
    else: return None

    # Confluence bonus
    if len(signals) >= 4: score += 10; signals.append(f"⚡ Multi-signal confluence ({len(signals)} factors aligned)")
    elif len(signals) >= 3: score += 5

    score = min(100, int(score / 115 * 100))
    if score < MIN_CONFIDENCE: return None

    step   = 1 if price < 20 else (2 if price < 50 else (5 if price < 200 else 10))
    atm    = round(price / step) * step
    strike_aggressive = atm + step if direction == "CALL" else atm - step
    strike_moderate   = atm

    now = datetime.now(ET)
    days_to_fri = (4 - now.weekday()) % 7 or 7
    expiry_weekly  = (now + timedelta(days=days_to_fri)).strftime("%m/%d")
    expiry_monthly = (now + timedelta(days=30)).strftime("%m/%d")

    return {
        "ticker": ticker, "price": price, "chg_pct": chg_pct,
        "direction": direction, "strike_aggressive": strike_aggressive,
        "strike_moderate": strike_moderate, "expiry_weekly": expiry_weekly,
        "expiry_monthly": expiry_monthly, "signals": signals, "score": score,
        "bull_pts": bull_pts, "bear_pts": bear_pts, "rsi": rsi,
        "atr_surge": atr_surge, "bb_width": bb_width, "intraday_range": intraday_range,
    }

# ── EMBEDS ────────────────────────────────────────────────────────────────────

def build_full_embed(signal, scan_num):
    is_call  = signal["direction"] == "CALL"
    color    = "#00C896" if is_call else "#FF4D6A"
    arrow    = "📈" if is_call else "📉"
    conf     = signal["score"]
    embed = discord.Embed(
        title=f"🎯 BULLSEYE #{scan_num} — {signal['ticker']} {signal['direction']}",
        description=f"{arrow} **{signal['ticker']}** — {signal['direction']} setup\n{confidence_bar(conf)} **{conf}%** {confidence_label(conf)}",
        color=discord.Color.from_str(color), timestamp=datetime.now(ET)
    )
    embed.add_field(name="💰 Price",      value=f"**${signal['price']:.2f}** ({signal['chg_pct']:+.2f}%)", inline=True)
    embed.add_field(name="🎯 Aggressive", value=f"**${signal['strike_aggressive']:.0f} {signal['direction']}**\nExp: {signal['expiry_weekly']} (weekly)", inline=True)
    embed.add_field(name="🛡️ Moderate",  value=f"**${signal['strike_moderate']:.0f} {signal['direction']}**\nExp: {signal['expiry_monthly']} (monthly)", inline=True)
    embed.add_field(name="📊 Snapshot",   value=f"RSI: **{signal['rsi']:.0f}** | ATR: **{signal['atr_surge']:.2f}x** | BB Width: **{signal['bb_width']:.3f}** | Range: **{signal['intraday_range']:.1f}%**", inline=False)
    embed.add_field(name=f"⚡ Signals ({len(signal['signals'])} factors)", value="\n".join(f"→ {s}" for s in signal["signals"]), inline=False)
    embed.add_field(name="⚠️ Risk Management", value="• Max **1-2%** portfolio per trade\n• Stop loss at **50% of premium**\n• Take partials at **50-75% gain**\n• Exit same day if thesis fails", inline=False)
    embed.set_footer(text=f"Phantom Bullseye • Scan #{scan_num} • {NFA_NOTE}")
    return embed

def build_summary_embed(signal, scan_num):
    is_call = signal["direction"] == "CALL"
    conf    = signal["score"]
    embed = discord.Embed(
        title=f"🎯 Bullseye Signal — {signal['ticker']} {signal['direction']}",
        description=(
            f"{'📈' if is_call else '📉'} **{signal['ticker']}** — {signal['direction']} setup detected\n"
            f"{confidence_bar(conf)} **{conf}%** {confidence_label(conf)}\n\n"
            f"💰 Price: **${signal['price']:.2f}** ({signal['chg_pct']:+.2f}%)\n\n"
            f"🔒 Full signal in **#bullseye-alerts** (Elite only)\n"
            f"Upgrade at **[{SITE_URL}]({SITE_URL})**"
        ),
        color=discord.Color.from_str("#00C896" if is_call else "#FF4D6A"),
        timestamp=datetime.now(ET)
    )
    embed.set_footer(text=NFA_NOTE)
    return embed

def build_scan_summary(signals, now, scan_num):
    calls = [s for s in signals if s["direction"] == "CALL"]
    puts  = [s for s in signals if s["direction"] == "PUT"]
    embed = discord.Embed(
        title=f"🎯 Bullseye Scan Complete — {now.strftime('%I:%M %p ET')}",
        description=f"Scanned **{len(WATCHLIST)} tickers** • Found **{len(signals)} signal(s)**",
        color=discord.Color.from_str("#F5C842"), timestamp=now
    )
    if calls: embed.add_field(name="📈 CALLs", value="\n".join(f"• **{s['ticker']}** — {s['score']}% {confidence_label(s['score'])}" for s in calls), inline=True)
    if puts:  embed.add_field(name="📉 PUTs",  value="\n".join(f"• **{s['ticker']}** — {s['score']}% {confidence_label(s['score'])}" for s in puts),  inline=True)
    if not signals: embed.add_field(name="📭 No Signals", value=f"No setups met the {MIN_CONFIDENCE}% threshold this scan.", inline=False)
    embed.set_footer(text=f"Next scan in 15 min • {NFA_NOTE}")
    return embed

# ── SCAN LOOP ─────────────────────────────────────────────────────────────────

@tasks.loop(seconds=SCAN_INTERVAL)
async def bullseye_scan():
    global last_scan_dt, scan_count, total_alerts
    if not is_market_open() and not is_premarket(): return
    now = datetime.now(ET)
    if last_scan_dt and last_scan_dt.date() < now.date(): alerted.clear()
    last_scan_dt = now
    scan_count  += 1
    print(f"[Bullseye #{scan_count}] {now.strftime('%H:%M ET')} — Scanning {len(WATCHLIST)} tickers...")
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    ch_drops  = get_ch(guild, CH_BULLSEYE_DROPS)
    ch_alerts = get_ch(guild, CH_BULLSEYE_ALERTS)
    signals   = []
    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST:
            try:
                quote = await fetch_quote(session, ticker)
                if not quote: await asyncio.sleep(0.4); continue
                ind = await fetch_indicators(session, ticker)
                if not ind: await asyncio.sleep(0.4); continue
                signal = score_bullseye(ticker, quote, ind)
                if signal: signals.append(signal)
            except Exception as e:
                print(f"  [Bullseye] {ticker}: {e}")
            await asyncio.sleep(0.5)

    if not signals:
        print(f"  [Bullseye #{scan_count}] No signals above {MIN_CONFIDENCE}%")
        if ch_drops:
            try: await ch_drops.send(embed=build_scan_summary(signals, now, scan_count))
            except discord.Forbidden: pass
        return

    signals.sort(key=lambda x: x["score"], reverse=True)
    print(f"  [Bullseye #{scan_count}] Found {len(signals)} signal(s)")

    for signal in signals:
        key = alert_key(signal["ticker"], signal["direction"], now)
        if key in alerted: continue
        alerted.add(key)
        total_alerts += 1
        if ch_alerts:
            ping = "@here — 🎯 Bullseye!" if signal["score"] >= 85 else ""
            try: await ch_alerts.send(content=ping or None, embed=build_full_embed(signal, scan_count))
            except discord.Forbidden: pass
        if ch_drops:
            try: await ch_drops.send(embed=build_summary_embed(signal, scan_count))
            except discord.Forbidden: pass
        await asyncio.sleep(1)

    if ch_drops:
        try: await ch_drops.send(embed=build_scan_summary(signals, now, scan_count))
        except discord.Forbidden: pass

# ── COMMANDS ──────────────────────────────────────────────────────────────────

@bot.command(name="scan")
@commands.has_permissions(administrator=True)
async def manual_scan(ctx):
    await ctx.reply("🎯 Running Bullseye scan now...")
    bullseye_scan.restart()

@bot.command(name="status")
async def status(ctx):
    now   = datetime.now(ET)
    state = "🟢 MARKET OPEN" if is_market_open() else "🟡 PRE-MARKET" if is_premarket() else "🔴 MARKET CLOSED"
    last  = last_scan_dt.strftime("%I:%M %p ET") if last_scan_dt else "Never"
    await ctx.reply(
        f"**🎯 Phantom Bullseye Bot**\n"
        f"Market: {state} | Last scan: {last}\n"
        f"Total scans: {scan_count} | Alerts fired: {total_alerts}\n"
        f"Watchlist: {len(WATCHLIST)} tickers | Min confidence: {MIN_CONFIDENCE}%\n"
        f"Scan interval: every 15 min"
    )

@bot.command(name="watchlist")
async def show_watchlist(ctx):
    await ctx.reply(f"**🎯 Bullseye Watchlist ({len(WATCHLIST)}):**\n" + "  ".join(f"`{t}`" for t in WATCHLIST))

@bot.command(name="bshelp")
async def bullseye_help(ctx):
    embed = discord.Embed(title="🎯 Phantom Bullseye Bot — Commands", color=discord.Color.from_str("#F5C842"))
    embed.add_field(name="Commands", value=(
        "`!bsscan` — manual scan *(Admin)*\n"
        "`!bsstatus` — bot status\n"
        "`!bswatchlist` — view watchlist\n"
        "`!bssetup` — post channel intros *(Admin)*\n"
        "`!bshelp` — this menu"
    ), inline=False)
    embed.add_field(name="📡 Channels", value=(
        "**#bullseye-drops** — Free — ticker + confidence\n"
        "**#bullseye-alerts** — Elite only — full breakdown"
    ), inline=False)
    embed.set_footer(text=NFA_NOTE)
    await ctx.reply(embed=embed)

@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup_channels(ctx):
    guild = ctx.guild
    ch_drops  = get_ch(guild, CH_BULLSEYE_DROPS)
    ch_alerts = get_ch(guild, CH_BULLSEYE_ALERTS)
    if ch_drops:
        e = discord.Embed(title="🎯 Welcome to Bullseye Drops",
                          description=(
                              "Signal summaries posted here every scan.\n\n"
                              "You'll see: ticker, direction, confidence score, price.\n\n"
                              f"🔒 Full breakdown in **#bullseye-alerts** (Elite only)\n"
                              f"Upgrade at **[{SITE_URL}]({SITE_URL})**"
                          ),
                          color=discord.Color.from_str("#F5C842"))
        e.set_footer(text=NFA_NOTE)
        try: await ch_drops.send(embed=e)
        except discord.Forbidden: pass
    if ch_alerts:
        e = discord.Embed(title="🎯 Welcome to Bullseye Alerts — Elite Access",
                          description=(
                              f"Full Bullseye signals posted here for **{MIN_CONFIDENCE}%+ confidence** setups.\n\n"
                              "Each alert includes: strike, expiry, all scoring factors, risk management.\n\n"
                              "⚠️ Bullseye plays are **intraday / 1-2 day** high-risk setups.\n"
                              "Max 1-2% portfolio per trade. Always use a stop loss."
                          ),
                          color=discord.Color.from_str("#00C896"))
        e.set_footer(text=NFA_NOTE)
        try: await ch_alerts.send(embed=e)
        except discord.Forbidden: pass
    await ctx.reply("✅ Bullseye channels set up!")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions): await ctx.reply("❌ Administrator permission required.")
    elif isinstance(error, commands.CommandNotFound): pass
    else: print(f"[error] {ctx.command}: {error}")

@bot.event
async def on_ready():
    print(f"\n✓ Phantom Bullseye Bot online — {bot.user}")
    print(f"  Guild: {GUILD_ID} | Watchlist: {len(WATCHLIST)} | Min conf: {MIN_CONFIDENCE}%")
    bullseye_scan.start()

if __name__ == "__main__":
    if not BOT_TOKEN: print("ERROR: BULLSEYE_BOT_TOKEN not set."); raise SystemExit(1)
    if not GUILD_ID:  print("ERROR: DISCORD_GUILD_ID not set.");  raise SystemExit(1)
    bot.run(BOT_TOKEN)
