"""
Phantom Traders — Complete Discord Bot v2
==========================================
Roles:
  Rookie      → Free (everyone)
  Pro Trader  → Pro subscribers
  Elite       → Elite subscribers

Features:
  - Auto scanner (5min during market hours) → #option-plays, #elite-signals, #screener-drops
  - Pre-market briefing 9:00am ET → #premarket-movers
  - Gap up/down alerts at market open → #premarket-movers
  - Earnings calendar alerts → #earnings-watch
  - MACD reversal alerts → #elite-signals
  - RSI extreme + volume spike alerts → #pt-alerts
  - !call command (manual trade callouts) → #option-plays
  - !calls (view open calls), !closecall (close with result)
  - Win/loss leaderboard → #wins-and-losses
  - !alert (price alerts) → #pt-alerts
  - Welcome DM on new member join
  - Auto role assign from Stripe via FastAPI backend

Environment variables:
  DISCORD_BOT_TOKEN
  DISCORD_GUILD_ID
  FINNHUB_API_KEY        (default: d70j32pr01quoska263g)
  SCAN_INTERVAL_SECONDS  (default: 300)
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

BOT_TOKEN     = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_ID      = int(os.getenv("DISCORD_GUILD_ID", "0"))
FINNHUB_KEY   = os.getenv("FINNHUB_API_KEY", "d70j32pr01quoska263g")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

ET = pytz.timezone("America/New_York")

# ── ROLE NAMES ────────────────────────────────────────────────────────────────

ROLE_ROOKIE     = "Rookie"
ROLE_PRO        = "Pro Trader"
ROLE_ELITE      = "Elite"
ROLE_MOD        = "Moderator"

TIER_HIERARCHY  = [ROLE_ROOKIE, ROLE_PRO, ROLE_ELITE]

# ── CHANNEL NAMES ─────────────────────────────────────────────────────────────

CH_OPTION_PLAYS   = "option-plays"
CH_ELITE_SIGNALS  = "elite-signals"
CH_SCREENER       = "screener-drops"
CH_BOT_COMMANDS   = "pt-bot-commands"
CH_PREMARKET      = "premarket-movers"
CH_EARNINGS       = "earnings-watch"
CH_PT_ALERTS      = "pt-alerts"
CH_WINS           = "wins-and-losses"
CH_WELCOME        = "welcome"

# ── SCANNER WATCHLIST ─────────────────────────────────────────────────────────

WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "AMD",  "PLTR", "COIN", "SQ",   "SHOP",
    "JPM",  "GS",   "BAC",
    "SPY",  "QQQ",  "IWM",  "GLD",  "TLT",
    "LLY",  "ABBV", "JNJ",
    "XOM",  "CVX",
]

# ── SERVER STRUCTURE ──────────────────────────────────────────────────────────
# access: "free" | "pro" | "elite"

SERVER_STRUCTURE = [
    ("📢 WELCOME & INFO", [
        ("welcome",            "Welcome to Phantom Traders.",               "free",  True,  True),
        ("rules",              "Server rules and community guidelines.",     "free",  False, True),
        ("announcements",      "Platform updates and news.",                 "free",  True,  True),
        ("how-to-get-roles",   "How to earn Pro Trader and Elite roles.",    "free",  False, True),
    ]),
    ("📊 MARKET INTEL", [
        ("premarket-movers",   "Top pre-market gainers and losers.",         "pro",   False, False),
        ("earnings-watch",     "Upcoming earnings and post-earnings plays.", "pro",   False, False),
        ("macro-news",         "Fed, CPI, NFP, and macro events.",           "pro",   False, False),
        ("sector-rotation",    "Institutional sector momentum shifts.",      "pro",   False, False),
    ]),
    ("⚡ TRADE SIGNALS", [
        ("pt-alerts",          "Live price, RSI, and volume alerts.",        "pro",   False, True),
        ("option-plays",       "AI-scanned options setups + callouts.",      "pro",   False, True),
        ("momentum-setups",    "High-momentum breakouts.",                   "pro",   False, True),
        ("options-flow",       "Unusual options activity.",                  "pro",   False, True),
        ("swing-watchlist",    "Swing trade candidates.",                    "pro",   False, False),
    ]),
    ("👑 ELITE LOUNGE", [
        ("elite-signals",      "Priority high-conviction + MACD alerts.",   "elite", False, True),
        ("elite-discussion",   "Deep-dive analysis for Elite members.",      "elite", False, False),
        ("portfolio-reviews",  "Elite peer portfolio reviews.",              "elite", False, False),
    ]),
    ("💬 COMMUNITY", [
        ("general",            "General trading chat.",                      "free",  False, False),
        ("introductions",      "Introduce yourself.",                        "free",  False, False),
        ("wins-and-losses",    "Share your trades + leaderboard.",           "free",  False, False),
        ("portfolio-critique", "Post your portfolio for feedback.",          "free",  False, False),
        ("off-topic",          "Anything goes — keep it clean.",             "free",  False, False),
    ]),
    ("🎓 EDUCATION", [
        ("beginners-corner",   "New to trading? Ask anything here.",         "free",  False, False),
        ("technical-analysis", "Chart setups and indicator discussions.",    "free",  False, False),
        ("options-education",  "Options strategies and play breakdowns.",    "free",  False, False),
        ("tax-and-legal",      "Tax strategy — not financial advice.",       "free",  False, False),
    ]),
    ("🤖 PHANTOM TOOLS", [
        ("pt-bot-commands",    "Use bot commands here. Type !pthelp",        "free",  False, False),
        ("screener-drops",     "Auto-posted scanner results.",               "pro",   False, True),
        ("risk-score-alerts",  "Portfolio risk score alerts.",               "pro",   False, True),
    ]),
]

VOICE_CHANNELS = {
    "🎙 VOICE ROOMS": [
        ("Pre-Market",      "free"),
        ("Pro Trader Room", "pro"),
        ("Elite Room",      "elite"),
        ("After Hours",     "free"),
    ]
}

# ── IN-MEMORY STATE ───────────────────────────────────────────────────────────

alerted_today:    set[str]  = set()
last_scan_dt:     datetime | None = None
open_calls:       dict[int, dict] = {}   # call_id → call data
call_counter:     int = 0
price_alerts:     list[dict] = []        # {user_id, channel_id, ticker, target, direction}
premarket_done:   bool = False
market_open_done: bool = False
earnings_done:    bool = False

# ── INTENTS & BOT ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.guilds          = True
intents.members         = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return dtime(9, 30) <= now.time() <= dtime(16, 0)

def is_premarket() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return dtime(4, 0) <= now.time() < dtime(9, 30)

def is_trading_day() -> bool:
    return datetime.now(ET).weekday() < 5

def get_ch(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name=name)

def build_overwrites(guild, access, role_objects, is_readonly=False):
    ow   = {}
    send = not is_readonly

    if access == "free":
        ow[guild.default_role] = discord.PermissionOverwrite(
            read_messages=True, send_messages=send,
            add_reactions=True, read_message_history=True,
        )
    else:
        ow[guild.default_role] = discord.PermissionOverwrite(
            read_messages=False, send_messages=False,
        )
        allowed_roles = {
            "pro":   [ROLE_PRO, ROLE_ELITE, ROLE_MOD],
            "elite": [ROLE_ELITE, ROLE_MOD],
        }.get(access, [])
        for rname in allowed_roles:
            if rname in role_objects:
                ow[role_objects[rname]] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=send,
                    add_reactions=True, read_message_history=True,
                )

    if ROLE_MOD in role_objects:
        ow[role_objects[ROLE_MOD]] = discord.PermissionOverwrite(
            read_messages=True, send_messages=True,
            manage_messages=True, add_reactions=True, read_message_history=True,
        )
    return ow

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
        print(f"  [fetch_quote] {ticker}: {e}")
        return None

async def fetch_ticker_data(session: aiohttp.ClientSession, ticker: str) -> dict | None:
    base    = "https://finnhub.io/api/v1"
    h       = {"X-Finnhub-Token": FINNHUB_KEY}
    now     = int(datetime.now().timestamp())
    from_ts = now - 86400 * 90
    try:
        async with session.get(f"{base}/quote?symbol={ticker}", headers=h) as r:
            quote = await r.json()
        if not quote.get("c"):
            return None
        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=rsi&timeperiod=14",
            headers=h
        ) as r:
            rsi_raw = await r.json()
        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=macd",
            headers=h
        ) as r:
            macd_raw = await r.json()
        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=bbands",
            headers=h
        ) as r:
            bb_raw = await r.json()
        indicators = {
            "rsi":         (rsi_raw.get("rsi")      or [50])[-1],
            "macd":        (macd_raw.get("macd")    or [0])[-1],
            "macd_signal": (macd_raw.get("signal")  or [0])[-1],
            "macd_hist":   (macd_raw.get("histogram") or [0])[-1],
            "macd_hist_prev": (macd_raw.get("histogram") or [0, 0])[-2] if len(macd_raw.get("histogram") or []) >= 2 else 0,
            "bb_upper":    (bb_raw.get("upperband") or [0])[-1],
            "bb_lower":    (bb_raw.get("lowerband") or [0])[-1],
            "volume":      quote.get("v", 0),
            "avg_volume":  quote.get("v", 0),
        }
        return {"ticker": ticker, "quote": quote, "indicators": indicators}
    except Exception as e:
        print(f"  [scanner] fetch error {ticker}: {e}")
        return None

async def fetch_earnings(session: aiohttp.ClientSession) -> list:
    try:
        today = datetime.now(ET).strftime("%Y-%m-%d")
        week  = (datetime.now(ET) + timedelta(days=7)).strftime("%Y-%m-%d")
        async with session.get(
            f"https://finnhub.io/api/v1/calendar/earnings?from={today}&to={week}",
            headers={"X-Finnhub-Token": FINNHUB_KEY}
        ) as r:
            data = await r.json()
            earnings = data.get("earningsCalendar", [])
            # Filter to watchlist only
            return [e for e in earnings if e.get("symbol") in WATCHLIST]
    except Exception as e:
        print(f"  [earnings] fetch error: {e}")
        return []

# ── SCANNER SCORING ───────────────────────────────────────────────────────────

def score_setup(ticker: str, quote: dict, indicators: dict) -> dict | None:
    price     = quote.get("c", 0)
    prev      = quote.get("pc", 1)
    chg_pct   = ((price - prev) / prev * 100) if prev else 0
    rsi       = indicators.get("rsi", 50)
    macd      = indicators.get("macd", 0)
    macd_sig  = indicators.get("macd_signal", 0)
    bb_upper  = indicators.get("bb_upper", price * 1.05)
    bb_lower  = indicators.get("bb_lower", price * 0.95)
    vol       = indicators.get("volume", 0)
    avg_vol   = indicators.get("avg_volume", 1) or 1
    vol_ratio = vol / avg_vol

    score     = 0
    signals   = []
    direction = None

    if rsi < 32:
        score += 20; signals.append(f"RSI oversold ({rsi:.0f})")
        direction = "CALL"
    if price <= bb_lower * 1.005:
        score += 20; signals.append("At lower Bollinger Band — bounce zone")
        direction = "CALL"
    if macd > macd_sig and macd > 0:
        score += 15; signals.append("MACD bullish crossover above zero")
        if direction != "PUT": direction = "CALL"
    if vol_ratio > 2.0 and chg_pct > 1.0:
        score += 15; signals.append(f"Volume surge {vol_ratio:.1f}x avg on up move")
        if direction != "PUT": direction = "CALL"
    if rsi > 72:
        score += 20; signals.append(f"RSI overbought ({rsi:.0f})")
        direction = "PUT"
    if price >= bb_upper * 0.995:
        score += 20; signals.append("At upper Bollinger Band — fade zone")
        direction = "PUT"
    if macd < macd_sig and macd < 0:
        score += 15; signals.append("MACD bearish crossover below zero")
        if direction != "CALL": direction = "PUT"
    if vol_ratio > 2.0 and chg_pct < -1.0:
        score += 15; signals.append(f"Volume surge {vol_ratio:.1f}x avg on down move")
        if direction != "CALL": direction = "PUT"
    if len(signals) >= 3: score += 10
    if len(signals) < 2 or score < 45 or not direction:
        return None

    step   = 1 if price < 50 else (5 if price < 200 else 10)
    atm    = round(price / step) * step
    strike = atm + step if direction == "CALL" else atm - step
    confidence = "HIGH" if score >= 75 else ("MEDIUM" if score >= 55 else "LOW")

    return {
        "ticker": ticker, "price": price, "chg_pct": chg_pct,
        "direction": direction, "strike": strike, "signals": signals,
        "score": score, "confidence": confidence,
        "rsi": rsi, "vol_ratio": vol_ratio,
    }

# ── EMBED BUILDERS ────────────────────────────────────────────────────────────

def build_scanner_embed(setup: dict) -> discord.Embed:
    is_call  = setup["direction"] == "CALL"
    color    = discord.Color.from_str("#00C896") if is_call else discord.Color.from_str("#FF4D6A")
    arrow    = "📈" if is_call else "📉"
    conf_dot = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🟠"}[setup["confidence"]]
    embed = discord.Embed(
        title=f"{arrow}  {setup['ticker']} — {setup['direction']} SETUP",
        color=color, timestamp=datetime.now(ET)
    )
    embed.add_field(name="💰 Price",
                    value=f"**${setup['price']:.2f}**  ({setup['chg_pct']:+.2f}%)", inline=True)
    embed.add_field(name="🎯 Strike",
                    value=f"**${setup['strike']:.0f} {setup['direction']}**", inline=True)
    embed.add_field(name="📅 Expiry", value="~30 DTE — next monthly", inline=True)
    embed.add_field(name="📊 Indicators",
                    value=f"RSI: **{setup['rsi']:.0f}** | Vol: **{setup['vol_ratio']:.1f}x**", inline=True)
    embed.add_field(name=f"{conf_dot} Confidence",
                    value=f"**{setup['confidence']}** ({setup['score']}/100)", inline=True)
    embed.add_field(name="⚡ Signals",
                    value="\n".join(f"→ {s}" for s in setup["signals"]), inline=False)
    embed.set_footer(text="📚 Educational only — not financial advice.")
    return embed

def build_call_embed(call: dict, call_id: int) -> discord.Embed:
    is_call = call["direction"] == "CALL"
    color   = discord.Color.from_str("#00C896") if is_call else discord.Color.from_str("#FF4D6A")
    arrow   = "📈" if is_call else "📉"
    embed   = discord.Embed(
        title=f"{arrow} TRADE CALLOUT #{call_id} — {call['ticker']} {call['direction']}",
        color=color,
        timestamp=datetime.now(ET)
    )
    embed.add_field(name="💰 Entry Price",   value=f"**${call['entry']:.2f}**",         inline=True)
    embed.add_field(name="🎯 Strike",        value=f"**${call['strike']} {call['direction']}**", inline=True)
    embed.add_field(name="📅 Expiry",        value=f"**{call['expiry']}**",              inline=True)
    embed.add_field(name="🎯 Target Exit",   value=f"**${call['target']:.2f}**",         inline=True)
    embed.add_field(name="🛑 Stop Loss",     value=f"**${call['stop']:.2f}**",           inline=True)
    embed.add_field(name="👤 Called By",     value=f"**{call['caller']}**",              inline=True)
    if call.get("notes"):
        embed.add_field(name="📝 Notes", value=call["notes"], inline=False)
    embed.set_footer(text=f"Call ID: #{call_id} • Educational only — not financial advice.")
    return embed

# ── SCHEDULED TASKS ───────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def daily_scheduler():
    global premarket_done, market_open_done, earnings_done

    now = datetime.now(ET)
    if not is_trading_day():
        return

    # Reset daily flags at midnight
    if now.hour == 0 and now.minute == 0:
        premarket_done   = False
        market_open_done = False
        earnings_done    = False

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    # ── 9:00am ET — Pre-market briefing ──
    if now.hour == 9 and now.minute == 0 and not premarket_done:
        premarket_done = True
        await post_premarket_briefing(guild)

    # ── 9:30am ET — Market open gap alerts ──
    if now.hour == 9 and now.minute == 30 and not market_open_done:
        market_open_done = True
        await post_gap_alerts(guild)

    # ── 9:05am ET — Earnings calendar ──
    if now.hour == 9 and now.minute == 5 and not earnings_done:
        earnings_done = True
        await post_earnings_calendar(guild)


async def post_premarket_briefing(guild: discord.Guild):
    ch = get_ch(guild, CH_PREMARKET)
    if not ch:
        return

    top_movers = []
    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST[:10]:
            quote = await fetch_quote(session, ticker)
            if quote:
                prev    = quote.get("pc", 1)
                price   = quote.get("c", 0)
                chg_pct = ((price - prev) / prev * 100) if prev else 0
                top_movers.append((ticker, price, chg_pct))
            await asyncio.sleep(0.3)

    top_movers.sort(key=lambda x: abs(x[2]), reverse=True)

    embed = discord.Embed(
        title="🌅 Pre-Market Briefing — Phantom Traders",
        description=f"Good morning traders! Here's your pre-market snapshot for **{datetime.now(ET).strftime('%A, %B %d')}**.",
        color=discord.Color.from_str("#4D9FFF"),
        timestamp=datetime.now(ET)
    )
    gainers = [(t, p, c) for t, p, c in top_movers if c > 0][:5]
    losers  = [(t, p, c) for t, p, c in top_movers if c < 0][:5]

    if gainers:
        embed.add_field(
            name="📈 Pre-Market Gainers",
            value="\n".join(f"`{t}` — ${p:.2f} ({c:+.2f}%)" for t, p, c in gainers),
            inline=True
        )
    if losers:
        embed.add_field(
            name="📉 Pre-Market Losers",
            value="\n".join(f"`{t}` — ${p:.2f} ({c:+.2f}%)" for t, p, c in losers),
            inline=True
        )
    embed.add_field(
        name="⏰ Market Opens",
        value="NYSE/NASDAQ open at **9:30am ET**\nGap alerts posting at open.",
        inline=False
    )
    embed.set_footer(text="Phantom Traders • Educational only — not financial advice.")
    await ch.send(embed=embed)


async def post_gap_alerts(guild: discord.Guild):
    ch = get_ch(guild, CH_PREMARKET)
    if not ch:
        return

    gaps = []
    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST:
            quote = await fetch_quote(session, ticker)
            if quote:
                prev    = quote.get("pc", 1)
                price   = quote.get("c", 0)
                chg_pct = ((price - prev) / prev * 100) if prev else 0
                if abs(chg_pct) >= 2.0:
                    gaps.append((ticker, price, chg_pct))
            await asyncio.sleep(0.3)

    if not gaps:
        return

    gaps.sort(key=lambda x: abs(x[2]), reverse=True)
    embed = discord.Embed(
        title="⚡ Market Open — Gap Alerts",
        description="Tickers gapping 2%+ at the open:",
        color=discord.Color.from_str("#F5C842"),
        timestamp=datetime.now(ET)
    )
    for ticker, price, chg in gaps[:8]:
        arrow = "📈" if chg > 0 else "📉"
        embed.add_field(
            name=f"{arrow} {ticker}",
            value=f"${price:.2f} ({chg:+.2f}%)",
            inline=True
        )
    embed.set_footer(text="Phantom Traders • Educational only — not financial advice.")
    await ch.send(embed=embed)


async def post_earnings_calendar(guild: discord.Guild):
    ch = get_ch(guild, CH_EARNINGS)
    if not ch:
        return

    async with aiohttp.ClientSession() as session:
        earnings = await fetch_earnings(session)

    if not earnings:
        return

    embed = discord.Embed(
        title="📅 Earnings Watch — Next 7 Days",
        description="Watchlist tickers reporting earnings this week:",
        color=discord.Color.from_str("#9B59B6"),
        timestamp=datetime.now(ET)
    )
    for e in earnings[:10]:
        symbol = e.get("symbol", "?")
        date   = e.get("date", "?")
        when   = e.get("hour", "?")
        est    = e.get("epsEstimate")
        when_str = "Before Open 🌅" if when == "bmo" else "After Close 🌙" if when == "amc" else when
        eps_str  = f" | EPS Est: **${est:.2f}**" if est else ""
        embed.add_field(
            name=f"`{symbol}`",
            value=f"📆 {date} — {when_str}{eps_str}",
            inline=False
        )
    embed.set_footer(text="Phantom Traders • Always check IV before trading earnings.")
    await ch.send(embed=embed)


# ── MAIN SCANNER LOOP ─────────────────────────────────────────────────────────

@tasks.loop(seconds=SCAN_INTERVAL)
async def scanner_loop():
    global last_scan_dt

    if not is_market_open() and not is_premarket():
        return

    now = datetime.now(ET)
    if last_scan_dt and last_scan_dt.date() < now.date():
        alerted_today.clear()
    last_scan_dt = now

    print(f"[{now.strftime('%H:%M ET')}] Scanning {len(WATCHLIST)} tickers...")

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    ch_plays  = get_ch(guild, CH_OPTION_PLAYS)
    ch_elite  = get_ch(guild, CH_ELITE_SIGNALS)
    ch_screen = get_ch(guild, CH_SCREENER)
    ch_alerts = get_ch(guild, CH_PT_ALERTS)

    setups = []
    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST:
            data = await fetch_ticker_data(session, ticker)
            if data:
                setup = score_setup(ticker, data["quote"], data["indicators"])
                if setup:
                    setups.append(setup)

                # ── MACD Reversal Alert → #elite-signals ──
                ind = data["indicators"]
                hist      = ind.get("macd_hist", 0)
                hist_prev = ind.get("macd_hist_prev", 0)
                macd_key  = f"macd_{ticker}_{now.date()}"
                if macd_key not in alerted_today:
                    if hist_prev < 0 and hist > 0:
                        # Bullish MACD reversal
                        if ch_elite:
                            rev_embed = discord.Embed(
                                title=f"🔄 MACD Bullish Reversal — {ticker}",
                                description=f"MACD histogram crossed from negative to positive — momentum shifting **bullish**.",
                                color=discord.Color.from_str("#00C896"),
                                timestamp=now
                            )
                            rev_embed.add_field(name="💰 Price", value=f"**${data['quote'].get('c', 0):.2f}**", inline=True)
                            rev_embed.add_field(name="📊 MACD Hist", value=f"**{hist:.4f}** (was {hist_prev:.4f})", inline=True)
                            rev_embed.set_footer(text="Educational only — not financial advice.")
                            try:
                                await ch_elite.send(embed=rev_embed)
                                alerted_today.add(macd_key)
                            except discord.Forbidden:
                                pass
                    elif hist_prev > 0 and hist < 0:
                        # Bearish MACD reversal
                        if ch_elite:
                            rev_embed = discord.Embed(
                                title=f"🔄 MACD Bearish Reversal — {ticker}",
                                description=f"MACD histogram crossed from positive to negative — momentum shifting **bearish**.",
                                color=discord.Color.from_str("#FF4D6A"),
                                timestamp=now
                            )
                            rev_embed.add_field(name="💰 Price", value=f"**${data['quote'].get('c', 0):.2f}**", inline=True)
                            rev_embed.add_field(name="📊 MACD Hist", value=f"**{hist:.4f}** (was {hist_prev:.4f})", inline=True)
                            rev_embed.set_footer(text="Educational only — not financial advice.")
                            try:
                                await ch_elite.send(embed=rev_embed)
                                alerted_today.add(macd_key)
                            except discord.Forbidden:
                                pass

                # ── RSI Extreme Alert → #pt-alerts ──
                rsi     = ind.get("rsi", 50)
                rsi_key = f"rsi_{ticker}_{now.date()}"
                if rsi_key not in alerted_today and ch_alerts:
                    if rsi <= 25:
                        rsi_embed = discord.Embed(
                            title=f"🔴 RSI Extreme Oversold — {ticker}",
                            description=f"RSI hit **{rsi:.0f}** — heavily oversold territory. Potential bounce zone.",
                            color=discord.Color.from_str("#00C896"),
                            timestamp=now
                        )
                        rsi_embed.add_field(name="💰 Price", value=f"**${data['quote'].get('c', 0):.2f}**", inline=True)
                        rsi_embed.add_field(name="📊 RSI", value=f"**{rsi:.0f}**", inline=True)
                        rsi_embed.set_footer(text="Educational only — not financial advice.")
                        try:
                            await ch_alerts.send(embed=rsi_embed)
                            alerted_today.add(rsi_key)
                        except discord.Forbidden:
                            pass
                    elif rsi >= 78:
                        rsi_embed = discord.Embed(
                            title=f"🔴 RSI Extreme Overbought — {ticker}",
                            description=f"RSI hit **{rsi:.0f}** — heavily overbought territory. Potential pullback zone.",
                            color=discord.Color.from_str("#FF4D6A"),
                            timestamp=now
                        )
                        rsi_embed.add_field(name="💰 Price", value=f"**${data['quote'].get('c', 0):.2f}**", inline=True)
                        rsi_embed.add_field(name="📊 RSI", value=f"**{rsi:.0f}**", inline=True)
                        rsi_embed.set_footer(text="Educational only — not financial advice.")
                        try:
                            await ch_alerts.send(embed=rsi_embed)
                            alerted_today.add(rsi_key)
                        except discord.Forbidden:
                            pass

                # ── Volume Spike Alert → #pt-alerts ──
                vol_ratio = ind.get("volume", 0) / (ind.get("avg_volume", 1) or 1)
                vol_key   = f"vol_{ticker}_{now.date()}"
                if vol_ratio >= 3.0 and vol_key not in alerted_today and ch_alerts:
                    quote     = data["quote"]
                    price     = quote.get("c", 0)
                    prev      = quote.get("pc", 1)
                    chg_pct   = ((price - prev) / prev * 100) if prev else 0
                    vol_embed = discord.Embed(
                        title=f"⚡ Volume Spike — {ticker}",
                        description=f"Unusual volume detected — **{vol_ratio:.1f}x** above average.",
                        color=discord.Color.from_str("#F5C842"),
                        timestamp=now
                    )
                    vol_embed.add_field(name="💰 Price",  value=f"**${price:.2f}** ({chg_pct:+.2f}%)", inline=True)
                    vol_embed.add_field(name="📊 Volume", value=f"**{vol_ratio:.1f}x** avg",           inline=True)
                    vol_embed.set_footer(text="Educational only — not financial advice.")
                    try:
                        await ch_alerts.send(embed=vol_embed)
                        alerted_today.add(vol_key)
                    except discord.Forbidden:
                        pass

                # ── Price Alert Check ──
                await check_price_alerts(guild, ticker, data["quote"].get("c", 0))

            await asyncio.sleep(0.35)

    if not setups:
        print("  No setups above threshold.")
        return

    setups.sort(key=lambda x: x["score"], reverse=True)
    print(f"  Found {len(setups)} setup(s)")

    for setup in setups:
        key = f"{setup['ticker']}_{setup['direction']}_{now.date()}"
        if key in alerted_today:
            continue
        embed = build_scanner_embed(setup)
        if ch_plays:
            try:
                await ch_plays.send(embed=embed)
                alerted_today.add(key)
            except discord.Forbidden:
                pass
        if ch_elite and setup["confidence"] == "HIGH":
            try:
                e2 = embed.copy()
                e2.title = "👑 " + e2.title
                await ch_elite.send(content="@here — High-confidence setup", embed=e2)
            except discord.Forbidden:
                pass
        await asyncio.sleep(1)

    if ch_screen and setups:
        lines = []
        for s in setups[:5]:
            arrow = "📈" if s["direction"] == "CALL" else "📉"
            lines.append(f"{arrow} **{s['ticker']}** — {s['direction']} | Score: {s['score']}/100 | RSI: {s['rsi']:.0f}")
        summary = discord.Embed(
            title=f"🤖 Scanner Drop — {now.strftime('%b %d %I:%M %p ET')}",
            description="\n".join(lines),
            color=discord.Color.from_str("#4D9FFF"),
            timestamp=now,
        )
        summary.set_footer(text=f"Scanned {len(WATCHLIST)} tickers • Full details in #option-plays")
        try:
            await ch_screen.send(embed=summary)
        except discord.Forbidden:
            pass


# ── PRICE ALERT CHECKER ───────────────────────────────────────────────────────

async def check_price_alerts(guild: discord.Guild, ticker: str, current_price: float):
    triggered = []
    for alert in price_alerts:
        if alert["ticker"] != ticker:
            continue
        hit = (alert["direction"] == "above" and current_price >= alert["target"]) or \
              (alert["direction"] == "below" and current_price <= alert["target"])
        if hit:
            triggered.append(alert)
            ch = guild.get_channel(alert["channel_id"])
            if ch:
                embed = discord.Embed(
                    title=f"🔔 Price Alert Triggered — {ticker}",
                    description=f"<@{alert['user_id']}> — **{ticker}** hit your alert at **${current_price:.2f}**!",
                    color=discord.Color.from_str("#F5C842"),
                    timestamp=datetime.now(ET)
                )
                embed.add_field(name="🎯 Target",  value=f"${alert['target']:.2f}", inline=True)
                embed.add_field(name="💰 Current", value=f"${current_price:.2f}",  inline=True)
                embed.set_footer(text="Educational only — not financial advice.")
                try:
                    await ch.send(embed=embed)
                except discord.Forbidden:
                    pass
    for alert in triggered:
        price_alerts.remove(alert)


# ── ROLE MANAGEMENT ───────────────────────────────────────────────────────────

async def set_member_tier(member: discord.Member, new_tier: str, reason: str = "Subscription update") -> str:
    guild           = member.guild
    roles_to_remove = []
    role_to_add     = None

    for tier in TIER_HIERARCHY:
        role = discord.utils.get(guild.roles, name=tier)
        if role and role in member.roles:
            roles_to_remove.append(role)

    if new_tier and new_tier in TIER_HIERARCHY:
        role_to_add = discord.utils.get(guild.roles, name=new_tier)

    if roles_to_remove:
        await member.remove_roles(*roles_to_remove, reason=reason)
    if role_to_add:
        await member.add_roles(role_to_add, reason=reason)
        return f"✅ {member.display_name} → **{new_tier}**"
    return f"✅ {member.display_name} → roles cleared (Free/Rookie)"


# ── EVENTS ────────────────────────────────────────────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
    """Auto-assign Rookie role + send welcome DM"""
    guild = member.guild

    # Assign Rookie role
    rookie_role = discord.utils.get(guild.roles, name=ROLE_ROOKIE)
    if rookie_role:
        try:
            await member.add_roles(rookie_role, reason="Auto-assigned on join")
        except discord.Forbidden:
            pass

    # Welcome DM
    try:
        embed = discord.Embed(
            title="👻 Welcome to Phantom Traders!",
            description=(
                f"Hey **{member.display_name}** — welcome to the Phantom Traders community! 🎉\n\n"
                f"Here's how to get started:"
            ),
            color=discord.Color.from_str("#00C896"),
            timestamp=datetime.now(ET)
        )
        embed.add_field(
            name="📋 Step 1 — Read the Rules",
            value="Check out **#rules** to understand our community guidelines.",
            inline=False
        )
        embed.add_field(
            name="🎓 Step 2 — Start Learning",
            value="Head to **#beginners-corner** and **#education** to build your foundation.",
            inline=False
        )
        embed.add_field(
            name="⚡ Step 3 — Upgrade Your Access",
            value=(
                "Check **#how-to-get-roles** to unlock:\n"
                "• **Pro Trader** → Market Intel + Trade Signals + Scanner\n"
                "• **Elite** → Everything + Elite Lounge\n\n"
                "Visit **aiphantomtraders.com** to subscribe."
            ),
            inline=False
        )
        embed.add_field(
            name="🤖 Step 4 — Meet the Bot",
            value="Type `!pthelp` in **#pt-bot-commands** to see all available commands.",
            inline=False
        )
        embed.set_footer(text="Phantom Traders • Educational only — not financial advice.")
        await member.send(embed=embed)
    except discord.Forbidden:
        # DMs disabled — post in welcome channel instead
        ch = get_ch(guild, CH_WELCOME)
        if ch:
            try:
                await ch.send(
                    f"👋 Welcome to Phantom Traders, {member.mention}! "
                    f"Check out **#rules** and **#how-to-get-roles** to get started. "
                    f"Type `!pthelp` in **#pt-bot-commands** for bot commands."
                )
            except discord.Forbidden:
                pass


# ── COMMANDS ──────────────────────────────────────────────────────────────────

# ── Admin role commands ───────────────────────────────────────────────────────

@bot.command(name="promote")
@commands.has_permissions(administrator=True)
async def promote(ctx, member: discord.Member, *, tier: str):
    """!promote @user Pro Trader  or  !promote @user Elite"""
    tier = tier.title()
    if tier not in TIER_HIERARCHY:
        await ctx.reply(f"❌ Unknown tier `{tier}`. Use: Rookie, Pro Trader, Elite")
        return
    result = await set_member_tier(member, tier, reason=f"Promoted by {ctx.author}")
    await ctx.reply(result)


@bot.command(name="demote")
@commands.has_permissions(administrator=True)
async def demote(ctx, member: discord.Member, *, tier: str):
    """!demote @user Rookie"""
    tier = tier.title()
    if tier not in TIER_HIERARCHY:
        await ctx.reply(f"❌ Unknown tier `{tier}`. Use: Rookie, Pro Trader, Elite")
        return
    result = await set_member_tier(member, tier, reason=f"Demoted by {ctx.author}")
    await ctx.reply(result)


@bot.command(name="removeroles")
@commands.has_permissions(administrator=True)
async def remove_roles_cmd(ctx, member: discord.Member):
    """!removeroles @user"""
    result = await set_member_tier(member, "", reason=f"Roles cleared by {ctx.author}")
    await ctx.reply(result)


@bot.command(name="whois")
@commands.has_permissions(administrator=True)
async def whois(ctx, member: discord.Member):
    """!whois @user"""
    tier_roles = [r.name for r in member.roles if r.name in TIER_HIERARCHY]
    await ctx.reply(
        f"**{member.display_name}** — {', '.join(tier_roles) if tier_roles else 'No tier role (Free)'}"
    )


# ── Trade callouts ────────────────────────────────────────────────────────────

@bot.command(name="call")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def trade_call(ctx, ticker: str, direction: str, strike: str, expiry: str, target: str, stop: str, *, notes: str = ""):
    """
    Post a trade callout to #option-plays.
    Usage: !call TSLA CALL 250 04/18 265 235 Optional notes here
    """
    global call_counter

    direction = direction.upper()
    if direction not in ("CALL", "PUT"):
        await ctx.reply("❌ Direction must be CALL or PUT. Example: `!call TSLA CALL 250 04/18 265 235`")
        return

    try:
        strike_f = float(strike.replace("$", ""))
        target_f = float(target.replace("$", ""))
        stop_f   = float(stop.replace("$", ""))
    except ValueError:
        await ctx.reply("❌ Strike, target, and stop must be numbers. Example: `!call TSLA CALL 250 04/18 265 235`")
        return

    # Fetch live entry price
    async with aiohttp.ClientSession() as session:
        quote = await fetch_quote(session, ticker.upper())
    entry = quote.get("c", 0) if quote else 0.0

    call_counter += 1
    call_id = call_counter

    call_data = {
        "ticker":    ticker.upper(),
        "direction": direction,
        "strike":    strike_f,
        "expiry":    expiry,
        "entry":     entry,
        "target":    target_f,
        "stop":      stop_f,
        "notes":     notes,
        "caller":    str(ctx.author.display_name),
        "caller_id": ctx.author.id,
        "opened_at": datetime.now(ET).isoformat(),
        "status":    "open",
    }
    open_calls[call_id] = call_data

    guild = ctx.guild
    ch = get_ch(guild, CH_OPTION_PLAYS)
    embed = build_call_embed(call_data, call_id)

    if ch:
        await ch.send(embed=embed)
        if ctx.channel != ch:
            await ctx.reply(f"✅ Callout #{call_id} posted to {ch.mention}!")
    else:
        await ctx.reply(embed=embed)


@bot.command(name="calls")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def view_calls(ctx):
    """!calls — view all open trade callouts"""
    if not open_calls:
        await ctx.reply("📭 No open callouts right now.")
        return

    embed = discord.Embed(
        title=f"📋 Open Trade Callouts ({len(open_calls)})",
        color=discord.Color.from_str("#4D9FFF"),
        timestamp=datetime.now(ET)
    )
    for cid, c in list(open_calls.items())[:10]:
        arrow = "📈" if c["direction"] == "CALL" else "📉"
        embed.add_field(
            name=f"{arrow} #{cid} — {c['ticker']} {c['direction']}",
            value=(
                f"Strike: **${c['strike']}** | Exp: **{c['expiry']}**\n"
                f"Target: **${c['target']}** | Stop: **${c['stop']}**\n"
                f"By: {c['caller']}"
            ),
            inline=False
        )
    embed.set_footer(text="Use !closecall <id> W/L [exit_price] to close a call.")
    await ctx.reply(embed=embed)


@bot.command(name="closecall")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def close_call(ctx, call_id: int, result: str, exit_price: float = 0.0):
    """
    Close a trade callout.
    Usage: !closecall 1 W 270.50   or   !closecall 1 L 228.00
    """
    if call_id not in open_calls:
        await ctx.reply(f"❌ Call #{call_id} not found or already closed.")
        return

    result = result.upper()
    if result not in ("W", "L", "WIN", "LOSS", "BE", "BREAKEVEN"):
        await ctx.reply("❌ Result must be W (win), L (loss), or BE (breakeven).")
        return

    call = open_calls.pop(call_id)
    result_label = {"W": "WIN 🏆", "WIN": "WIN 🏆", "L": "LOSS 💔", "LOSS": "LOSS 💔", "BE": "BREAKEVEN 🤝", "BREAKEVEN": "BREAKEVEN 🤝"}[result]
    color = {"W": "#00C896", "WIN": "#00C896", "L": "#FF4D6A", "LOSS": "#FF4D6A", "BE": "#4D9FFF", "BREAKEVEN": "#4D9FFF"}[result]

    pnl_pct = ((exit_price - call["entry"]) / call["entry"] * 100) if exit_price and call["entry"] else 0
    if call["direction"] == "PUT":
        pnl_pct = -pnl_pct

    embed = discord.Embed(
        title=f"🔒 CALL CLOSED #{call_id} — {call['ticker']} {call['direction']} — {result_label}",
        color=discord.Color.from_str(color),
        timestamp=datetime.now(ET)
    )
    embed.add_field(name="📈 Entry",     value=f"${call['entry']:.2f}",  inline=True)
    embed.add_field(name="📉 Exit",      value=f"${exit_price:.2f}" if exit_price else "N/A", inline=True)
    embed.add_field(name="💹 P&L",       value=f"{pnl_pct:+.2f}%" if exit_price else "N/A",  inline=True)
    embed.add_field(name="🎯 Strike",    value=f"${call['strike']} {call['direction']}", inline=True)
    embed.add_field(name="📅 Expiry",    value=call["expiry"],           inline=True)
    embed.add_field(name="👤 Called By", value=call["caller"],           inline=True)
    embed.set_footer(text=f"Call ID: #{call_id} • Educational only — not financial advice.")

    # Post to wins-and-losses
    guild = ctx.guild
    ch_wins = get_ch(guild, CH_WINS)
    ch_plays = get_ch(guild, CH_OPTION_PLAYS)
    if ch_wins:
        await ch_wins.send(embed=embed)
    if ch_plays:
        await ch_plays.send(embed=embed)
    if ctx.channel not in [ch_wins, ch_plays]:
        await ctx.reply(f"✅ Call #{call_id} closed as {result_label}")


# ── Price alerts ──────────────────────────────────────────────────────────────

@bot.command(name="alert")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def set_alert(ctx, ticker: str, price: float):
    """
    Set a price alert. Bot will ping you when ticker hits the price.
    Usage: !alert NVDA 900
    """
    ticker = ticker.upper()

    async with aiohttp.ClientSession() as session:
        quote = await fetch_quote(session, ticker)

    if not quote:
        await ctx.reply(f"❌ Could not find ticker `{ticker}`.")
        return

    current = quote.get("c", 0)
    direction = "above" if price > current else "below"

    price_alerts.append({
        "user_id":    ctx.author.id,
        "channel_id": ctx.channel.id,
        "ticker":     ticker,
        "target":     price,
        "direction":  direction,
    })

    await ctx.reply(
        f"🔔 Alert set! I'll ping you when **{ticker}** goes **{direction}** **${price:.2f}**.\n"
        f"Current price: **${current:.2f}**"
    )


@bot.command(name="alerts")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def view_alerts(ctx):
    """!alerts — view your active price alerts"""
    my_alerts = [a for a in price_alerts if a["user_id"] == ctx.author.id]
    if not my_alerts:
        await ctx.reply("📭 You have no active alerts. Use `!alert TSLA 250` to set one.")
        return
    lines = [f"`{a['ticker']}` — {a['direction']} **${a['target']:.2f}**" for a in my_alerts]
    await ctx.reply("**Your Active Alerts:**\n" + "\n".join(lines))


@bot.command(name="cancelalert")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def cancel_alert(ctx, ticker: str):
    """!cancelalert TSLA — cancel your alert for a ticker"""
    ticker  = ticker.upper()
    before  = len(price_alerts)
    price_alerts[:] = [a for a in price_alerts if not (a["user_id"] == ctx.author.id and a["ticker"] == ticker)]
    removed = before - len(price_alerts)
    if removed:
        await ctx.reply(f"✅ Cancelled {removed} alert(s) for `{ticker}`.")
    else:
        await ctx.reply(f"❌ No alerts found for `{ticker}`.")


# ── Scanner commands ──────────────────────────────────────────────────────────

@bot.command(name="scan")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def manual_scan(ctx):
    """!scan — trigger a manual scan now"""
    await ctx.reply("🔍 Running manual scan — results in #option-plays shortly.")
    scanner_loop.restart()


@bot.command(name="status")
async def status(ctx):
    """!status — scanner status (anyone)"""
    now   = datetime.now(ET)
    state = ("🟢 MARKET OPEN" if is_market_open()
             else "🟡 PRE-MARKET" if is_premarket()
             else "🔴 MARKET CLOSED")
    last  = last_scan_dt.strftime("%I:%M %p ET") if last_scan_dt else "Never"
    await ctx.reply(
        f"**Phantom Traders Scanner**\n"
        f"Market: {state}\n"
        f"Last scan: {last}\n"
        f"Alerted today: {len(alerted_today)} tickers\n"
        f"Open callouts: {len(open_calls)}\n"
        f"Active price alerts: {len(price_alerts)}\n"
        f"Watchlist: {len(WATCHLIST)} stocks\n"
        f"Scan interval: every {SCAN_INTERVAL // 60} min"
    )


@bot.command(name="watchlist")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def show_watchlist(ctx):
    """!watchlist — view the scanner watchlist"""
    await ctx.reply("**Scanner Watchlist:**\n" + "  ".join(f"`{t}`" for t in WATCHLIST))


@bot.command(name="addwatch")
@commands.has_permissions(administrator=True)
async def add_watch(ctx, ticker: str):
    """!addwatch TSLA"""
    t = ticker.upper().strip()
    if t in WATCHLIST:
        await ctx.reply(f"`{t}` is already in the watchlist.")
    else:
        WATCHLIST.append(t)
        await ctx.reply(f"✅ Added `{t}` — watchlist now has {len(WATCHLIST)} tickers.")


@bot.command(name="removewatch")
@commands.has_permissions(administrator=True)
async def remove_watch(ctx, ticker: str):
    """!removewatch TSLA"""
    t = ticker.upper().strip()
    if t in WATCHLIST:
        WATCHLIST.remove(t)
        await ctx.reply(f"✅ Removed `{t}` — watchlist now has {len(WATCHLIST)} tickers.")
    else:
        await ctx.reply(f"`{t}` not found in watchlist.")


# ── Server setup ──────────────────────────────────────────────────────────────

@bot.command(name="setup_server")
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    """Scaffold all channels, roles, and permissions. Safe to re-run."""
    guild = ctx.guild
    await ctx.reply("🔧 Starting server setup... this takes about 60 seconds.")

    role_objects = {}
    role_configs = {
        ROLE_ROOKIE: discord.Color.from_str("#6E7F96"),
        ROLE_PRO:    discord.Color.from_str("#00C896"),
        ROLE_ELITE:  discord.Color.from_str("#F5C842"),
        ROLE_MOD:    discord.Color.from_str("#FF4D6A"),
    }
    existing_roles = {r.name: r for r in guild.roles}
    for rname, rcolor in role_configs.items():
        if rname in existing_roles:
            role_objects[rname] = existing_roles[rname]
        else:
            r = await guild.create_role(name=rname, color=rcolor, mentionable=True,
                                         reason="Phantom Traders setup")
            role_objects[rname] = r
            await asyncio.sleep(0.3)

    existing_cats  = {c.name: c for c in guild.categories}
    existing_chans = {c.name: c for c in guild.channels}
    created = 0
    skipped = 0

    for cat_name, channels in SERVER_STRUCTURE:
        if cat_name not in existing_cats:
            category = await guild.create_category(cat_name, reason="Phantom Traders setup")
            await asyncio.sleep(0.4)
        else:
            category = existing_cats[cat_name]

        for ch_name, topic, access, is_announce, is_readonly in channels:
            if ch_name in existing_chans:
                skipped += 1
                continue
            ow = build_overwrites(guild, access, role_objects, is_readonly)
            try:
                if is_announce:
                    await guild.create_text_channel(ch_name, category=category, topic=topic,
                                                     overwrites=ow, news=True,
                                                     reason="Phantom Traders setup")
                else:
                    await guild.create_text_channel(ch_name, category=category, topic=topic,
                                                     overwrites=ow, reason="Phantom Traders setup")
                created += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  Error creating #{ch_name}: {e}")

    for cat_name, voice_list in VOICE_CHANNELS.items():
        if cat_name not in existing_cats:
            category = await guild.create_category(cat_name, reason="Phantom Traders setup")
            await asyncio.sleep(0.4)
        else:
            category = existing_cats[cat_name]
        for vname, access in voice_list:
            if vname not in existing_chans:
                ow = build_overwrites(guild, access, role_objects, is_readonly=False)
                await guild.create_voice_channel(vname, category=category,
                                                  overwrites=ow, reason="Phantom Traders setup")
                created += 1
                await asyncio.sleep(0.5)
            else:
                skipped += 1

    await ctx.reply(
        f"✅ **Server setup complete!**\n"
        f"Created: {created} | Skipped: {skipped}\n\n"
        f"**Roles:** Rookie (grey) | Pro Trader (green) | Elite (gold) | Moderator (red)\n"
        f"**Free/Rookie** → Welcome, Community, Education\n"
        f"**Pro Trader** → + Market Intel, Trade Signals, Scanner\n"
        f"**Elite** → + Elite Lounge (everything)"
    )


# ── Help ──────────────────────────────────────────────────────────────────────

@bot.command(name="pthelp")
async def pt_help(ctx):
    """!pthelp — all commands"""
    embed = discord.Embed(
        title="👻 Phantom Traders Bot — Commands",
        color=discord.Color.from_str("#00C896")
    )
    embed.add_field(name="📣 Trade Callouts *(Pro/Elite)*", value=(
        "`!call TSLA CALL 250 04/18 265 235 [notes]` — post a callout\n"
        "`!calls` — view open callouts\n"
        "`!closecall <id> W/L [exit_price]` — close a callout"
    ), inline=False)
    embed.add_field(name="🔔 Price Alerts *(Pro/Elite)*", value=(
        "`!alert NVDA 900` — alert when NVDA hits $900\n"
        "`!alerts` — view your active alerts\n"
        "`!cancelalert NVDA` — cancel your NVDA alert"
    ), inline=False)
    embed.add_field(name="📊 Scanner *(Pro/Elite)*", value=(
        "`!scan` — trigger manual scan\n"
        "`!status` — scanner + bot status *(anyone)*\n"
        "`!watchlist` — view watchlist\n"
        "`!addwatch TSLA` / `!removewatch TSLA` *(Admin)*"
    ), inline=False)
    embed.add_field(name="👤 Roles *(Admin only)*", value=(
        "`!promote @user Pro Trader` / `!promote @user Elite`\n"
        "`!demote @user Rookie`\n"
        "`!removeroles @user` — back to Free\n"
        "`!whois @user` — check tier"
    ), inline=False)
    embed.add_field(name="🔧 Server *(Admin only)*", value=(
        "`!setup_server` — scaffold channels and roles"
    ), inline=False)
    embed.add_field(name="🏷️ Tier Access", value=(
        "**Rookie/Free** → Welcome, Community, Education\n"
        "**Pro Trader** → + Market Intel, Trade Signals, Scanner, Alerts\n"
        "**Elite** → + Elite Lounge + MACD Reversals"
    ), inline=False)
    embed.set_footer(text="Phantom Traders • Educational only — not financial advice.")
    await ctx.reply(embed=embed)


# ── Error handler ─────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ You need Administrator permission for that command.")
    elif isinstance(error, commands.MissingRole):
        await ctx.reply("❌ You don't have the required role for that command.")
    elif isinstance(error, commands.MissingAnyRole):
        await ctx.reply("❌ You need Pro Trader or Elite role for that command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply("❌ Member not found. Mention them with @username.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("❌ Invalid argument. Check `!pthelp` for usage.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"[error] {ctx.command}: {error}")


# ── On ready ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"\n✓ Phantom Traders Bot v2 online — {bot.user}")
    print(f"  Guild ID:      {GUILD_ID}")
    print(f"  Watchlist:     {len(WATCHLIST)} tickers")
    print(f"  Scan interval: {SCAN_INTERVAL}s")
    scanner_loop.start()
    daily_scheduler.start()


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set.")
        raise SystemExit(1)
    if not GUILD_ID:
        print("ERROR: DISCORD_GUILD_ID not set.")
        raise SystemExit(1)
    bot.run(BOT_TOKEN)
