"""
Phantom Traders — Complete Discord Bot
=======================================
Single file. Drop into your phantom-traders-backend repo and deploy.

Handles:
  - Role management  (Rookie / Pro Trader / Elite — assign, upgrade, downgrade)
  - Server setup     (!setup_server  — run once to scaffold all channels)
  - Options scanner  (auto-scans every 5 min during market hours, posts alerts)
  - Slash commands   (/scan /status /watchlist /addwatch)

Requirements (add to requirements.txt):
  discord.py>=2.3.0
  finnhub-python>=2.4.0
  aiohttp>=3.9.0
  pytz>=2024.1
  python-dotenv>=1.0.0

Environment variables (Railway → Variables tab):
  DISCORD_BOT_TOKEN      — your bot token from discord.com/developers
  DISCORD_GUILD_ID       — your server ID (right-click server → Copy Server ID)
  FINNHUB_API_KEY        — d70j32pr01quoska263g
  SCAN_INTERVAL_SECONDS  — optional, default 300 (every 5 minutes)
"""

import asyncio
import os
import pytz
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, time as dtime
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────

BOT_TOKEN      = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_ID       = int(os.getenv("DISCORD_GUILD_ID", "0"))
FINNHUB_KEY    = os.getenv("FINNHUB_API_KEY", "d70j32pr01quoska263g")
SCAN_INTERVAL  = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

ET = pytz.timezone("America/New_York")

# ── ROLE NAMES ────────────────────────────────────────────────────────────────

ROLE_ROOKIE     = "Rookie"
ROLE_PRO        = "Pro Trader"
ROLE_ELITE      = "Elite"
ROLE_MOD        = "Moderator"

TIER_HIERARCHY  = [ROLE_ROOKIE, ROLE_PRO, ROLE_ELITE]

# ── CHANNELS ──────────────────────────────────────────────────────────────────

CH_OPTION_PLAYS  = "option-plays"
CH_ELITE_SIGNALS = "elite-signals"
CH_SCREENER      = "screener-drops"
CH_BOT_COMMANDS  = "pt-bot-commands"

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

SERVER_STRUCTURE = [
    ("📢 WELCOME & INFO", [
        ("welcome",            "Welcome to Phantom Traders.",               "all",   True,  True),
        ("rules",              "Server rules and community guidelines.",     "all",   False, True),
        ("announcements",      "Platform updates and news.",                 "all",   True,  True),
        ("how-to-get-roles",   "How to earn Pro Trader and Elite roles.",    "all",   False, True),
    ]),
    ("📊 MARKET INTEL", [
        ("premarket-movers",   "Top pre-market gainers and losers.",         "all",   False, False),
        ("earnings-watch",     "Upcoming earnings and post-earnings plays.", "all",   False, False),
        ("macro-news",         "Fed, CPI, NFP, and macro events.",           "all",   False, False),
        ("sector-rotation",    "Institutional sector momentum shifts.",      "all",   False, False),
    ]),
    ("⚡ TRADE SIGNALS", [
        ("pt-alerts",          "Live Phantom Traders app alerts.",           "pro",   False, True),
        ("option-plays",       "AI-scanned options setups.",                 "pro",   False, True),
        ("momentum-setups",    "High-momentum breakouts.",                   "pro",   False, True),
        ("options-flow",       "Unusual options activity.",                  "pro",   False, True),
        ("swing-watchlist",    "Swing trade candidates.",                    "pro",   False, False),
    ]),
    ("👑 ELITE LOUNGE", [
        ("elite-signals",      "Priority high-conviction alerts.",           "elite", False, True),
        ("elite-discussion",   "Deep-dive analysis for Elite members.",      "elite", False, False),
        ("portfolio-reviews",  "Elite peer portfolio reviews.",              "elite", False, False),
    ]),
    ("💬 COMMUNITY", [
        ("general",            "General trading chat.",                      "all",   False, False),
        ("introductions",      "Introduce yourself.",                        "all",   False, False),
        ("wins-and-losses",    "Share your trades.",                         "all",   False, False),
        ("portfolio-critique", "Post your portfolio for feedback.",          "all",   False, False),
        ("off-topic",          "Anything goes — keep it clean.",             "all",   False, False),
    ]),
    ("🎓 EDUCATION", [
        ("beginners-corner",   "New to trading? Ask anything here.",        "all",   False, False),
        ("technical-analysis", "Chart setups and indicator discussions.",    "all",   False, False),
        ("options-education",  "Options strategies and play breakdowns.",    "all",   False, False),
        ("tax-and-legal",      "Tax strategy — not financial advice.",       "all",   False, False),
    ]),
    ("🤖 PHANTOM TOOLS", [
        ("pt-bot-commands",    "Use bot commands here. Type !help",          "all",   False, False),
        ("screener-drops",     "Auto-posted scanner results.",               "all",   False, True),
        ("risk-score-alerts",  "Portfolio risk score alerts.",               "pro",   False, True),
    ]),
]

VOICE_CHANNELS = {
    "🎙 VOICE ROOMS": [
        ("Pre-Market",        "all"),
        ("Options Room",      "pro"),
        ("Elite Room",        "elite"),
        ("After Hours",       "all"),
    ]
}

# ── INTENTS & BOT ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.guilds        = True
intents.members       = True
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
    return dtime(8, 0) <= now.time() < dtime(9, 30)

async def get_role(guild: discord.Guild, name: str) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=name)

async def get_channel(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name=name)

def build_overwrites(guild, access, role_objects, is_readonly=False):
    ow = {}
    send = not is_readonly

    if access == "all":
        ow[guild.default_role] = discord.PermissionOverwrite(
            read_messages=True,
            send_messages=send,
            add_reactions=True,
            read_message_history=True,
        )
    else:
        ow[guild.default_role] = discord.PermissionOverwrite(
            read_messages=False,
            send_messages=False,
        )
        allowed = {
            "pro":   [ROLE_PRO, ROLE_ELITE, ROLE_MOD],
            "elite": [ROLE_ELITE, ROLE_MOD],
        }.get(access, [])
        for rname in allowed:
            if rname in role_objects:
                ow[role_objects[rname]] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=send,
                    add_reactions=True,
                    read_message_history=True,
                )
        if ROLE_MOD in role_objects:
            ow[role_objects[ROLE_MOD]] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                add_reactions=True,
                read_message_history=True,
            )
    return ow

# ── ROLE MANAGEMENT ───────────────────────────────────────────────────────────

async def set_member_tier(member: discord.Member, new_tier: str, reason: str = "Subscription update") -> str:
    guild = member.guild
    roles_to_remove = []
    role_to_add = None

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

    return f"✅ {member.display_name} → roles cleared"


@bot.command(name="promote")
@commands.has_permissions(administrator=True)
async def promote(ctx, member: discord.Member, tier: str):
    tier = tier.title()
    if tier not in TIER_HIERARCHY:
        await ctx.reply(f"❌ Unknown tier `{tier}`. Use: Rookie, Pro Trader, Elite")
        return
    result = await set_member_tier(member, tier, reason=f"Manual promotion by {ctx.author}")
    await ctx.reply(result)


@bot.command(name="demote")
@commands.has_permissions(administrator=True)
async def demote(ctx, member: discord.Member, tier: str):
    tier = tier.title()
    if tier not in TIER_HIERARCHY:
        await ctx.reply(f"❌ Unknown tier `{tier}`. Use: Rookie, Pro Trader, Elite")
        return
    result = await set_member_tier(member, tier, reason=f"Manual demotion by {ctx.author}")
    await ctx.reply(result)


@bot.command(name="removeroles")
@commands.has_permissions(administrator=True)
async def remove_roles_cmd(ctx, member: discord.Member):
    result = await set_member_tier(member, "", reason=f"Roles cleared by {ctx.author}")
    await ctx.reply(result)


@bot.command(name="whois")
@commands.has_permissions(administrator=True)
async def whois(ctx, member: discord.Member):
    tier_roles = [r.name for r in member.roles if r.name in TIER_HIERARCHY]
    if tier_roles:
        await ctx.reply(f"**{member.display_name}** — {', '.join(tier_roles)}")
    else:
        await ctx.reply(f"**{member.display_name}** — no tier role assigned")


# ── SERVER SETUP ──────────────────────────────────────────────────────────────

@bot.command(name="setup_server")
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
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
                    await guild.create_text_channel(ch_name, category=category,
                                                     topic=topic, overwrites=ow,
                                                     news=True, reason="Phantom Traders setup")
                else:
                    await guild.create_text_channel(ch_name, category=category,
                                                     topic=topic, overwrites=ow,
                                                     reason="Phantom Traders setup")
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
        f"Created: {created} channels/roles\n"
        f"Skipped (already existed): {skipped}"
    )


# ── OPTIONS SCANNER ───────────────────────────────────────────────────────────

alerted_today: set[str] = set()
last_scan_dt: datetime | None = None


def score_setup(ticker: str, quote: dict, indicators: dict) -> dict | None:
    price    = quote.get("c", 0)
    prev     = quote.get("pc", 1)
    chg_pct  = ((price - prev) / prev * 100) if prev else 0

    rsi      = indicators.get("rsi", 50)
    macd     = indicators.get("macd", 0)
    macd_sig = indicators.get("macd_signal", 0)
    bb_upper = indicators.get("bb_upper", price * 1.05)
    bb_lower = indicators.get("bb_lower", price * 0.95)
    vol      = indicators.get("volume", 0)
    avg_vol  = indicators.get("avg_volume", 1) or 1
    vol_ratio = vol / avg_vol

    score   = 0
    signals = []
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

    step = 1 if price < 50 else (5 if price < 200 else 10)
    atm  = round(price / step) * step
    strike = atm + step if direction == "CALL" else atm - step

    confidence = "HIGH" if score >= 75 else ("MEDIUM" if score >= 55 else "LOW")

    return {
        "ticker":     ticker,
        "price":      price,
        "chg_pct":    chg_pct,
        "direction":  direction,
        "strike":     strike,
        "signals":    signals,
        "score":      score,
        "confidence": confidence,
        "rsi":        rsi,
        "vol_ratio":  vol_ratio,
    }


def build_alert_embed(setup: dict) -> discord.Embed:
    is_call = setup["direction"] == "CALL"
    color   = discord.Color.from_str("#00C896") if is_call else discord.Color.from_str("#FF4D6A")
    arrow   = "📈" if is_call else "📉"
    conf_dot = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🟠"}[setup["confidence"]]

    embed = discord.Embed(
        title=f"{arrow}  {setup['ticker']} — {setup['direction']} SETUP",
        color=color,
        timestamp=datetime.now(ET)
    )
    embed.add_field(name="💰 Current Price",
                    value=f"**${setup['price']:.2f}**  ({setup['chg_pct']:+.2f}% today)", inline=True)
    embed.add_field(name="🎯 Suggested Strike",
                    value=f"**${setup['strike']:.0f} {setup['direction']}**", inline=True)
    embed.add_field(name="📅 Expiry",
                    value="~30 DTE — check next monthly", inline=True)
    embed.add_field(name="📊 Indicators",
                    value=f"RSI: **{setup['rsi']:.0f}** | Vol: **{setup['vol_ratio']:.1f}x** avg", inline=True)
    embed.add_field(name=f"{conf_dot} Confidence",
                    value=f"**{setup['confidence']}** (Score: {setup['score']}/100)", inline=True)
    embed.add_field(name="⚡ Signals",
                    value="\n".join(f"→ {s}" for s in setup["signals"]), inline=False)
    embed.set_footer(text="📚 Educational only — not financial advice. Always manage your risk.")
    return embed


async def fetch_ticker_data(session: aiohttp.ClientSession, ticker: str) -> dict | None:
    base = "https://finnhub.io/api/v1"
    h    = {"X-Finnhub-Token": FINNHUB_KEY}
    now  = int(datetime.now().timestamp())
    from_ts = now - 86400 * 90

    try:
        async with session.get(f"{base}/quote?symbol={ticker}", headers=h) as r:
            quote = await r.json()
        if not quote.get("c"):
            return None

        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D"
            f"&from={from_ts}&to={now}&indicator=rsi&timeperiod=14", headers=h
        ) as r:
            rsi_raw = await r.json()

        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D"
            f"&from={from_ts}&to={now}&indicator=macd", headers=h
        ) as r:
            macd_raw = await r.json()

        async with session.get(
            f"{base}/indicator?symbol={ticker}&resolution=D"
            f"&from={from_ts}&to={now}&indicator=bbands", headers=h
        ) as r:
            bb_raw = await r.json()

        indicators = {
            "rsi":         (rsi_raw.get("rsi")       or [50])[-1],
            "macd":        (macd_raw.get("macd")     or [0])[-1],
            "macd_signal": (macd_raw.get("signal")   or [0])[-1],
            "bb_upper":    (bb_raw.get("upperband")  or [0])[-1],
            "bb_lower":    (bb_raw.get("lowerband")  or [0])[-1],
            "volume":      quote.get("v", 0),
            "avg_volume":  quote.get("v", 0),
        }
        return {"ticker": ticker, "quote": quote, "indicators": indicators}

    except Exception as e:
        print(f"  [scanner] fetch error {ticker}: {e}")
        return None


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

    ch_plays  = discord.utils.get(guild.text_channels, name=CH_OPTION_PLAYS)
    ch_elite  = discord.utils.get(guild.text_channels, name=CH_ELITE_SIGNALS)
    ch_screen = discord.utils.get(guild.text_channels, name=CH_SCREENER)

    setups = []

    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST:
            data = await fetch_ticker_data(session, ticker)
            if data:
                setup = score_setup(ticker, data["quote"], data["indicators"])
                if setup:
                    setups.append(setup)
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

        embed = build_alert_embed(setup)

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


# ── BOT COMMANDS ──────────────────────────────────────────────────────────────

@bot.command(name="scan")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def manual_scan(ctx):
    await ctx.reply("🔍 Running manual scan — results in #option-plays shortly.")
    scanner_loop.restart()


@bot.command(name="status")
async def status(ctx):
    now    = datetime.now(ET)
    state  = ("🟢 MARKET OPEN" if is_market_open()
              else "🟡 PRE-MARKET" if is_premarket()
              else "🔴 MARKET CLOSED")
    last   = last_scan_dt.strftime("%I:%M %p ET") if last_scan_dt else "Never"
    await ctx.reply(
        f"**Phantom Traders Scanner**\n"
        f"Market: {state}\n"
        f"Last scan: {last}\n"
        f"Alerted today: {len(alerted_today)} tickers\n"
        f"Watchlist: {len(WATCHLIST)} stocks\n"
        f"Scan interval: every {SCAN_INTERVAL // 60} min during market hours"
    )


@bot.command(name="watchlist")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def show_watchlist(ctx):
    await ctx.reply("**Scanner Watchlist:**\n" + "  ".join(f"`{t}`" for t in WATCHLIST))


@bot.command(name="addwatch")
@commands.has_permissions(administrator=True)
async def add_watch(ctx, ticker: str):
    t = ticker.upper().strip()
    if t in WATCHLIST:
        await ctx.reply(f"`{t}` is already in the watchlist.")
    else:
        WATCHLIST.append(t)
        await ctx.reply(f"✅ Added `{t}` — watchlist now has {len(WATCHLIST)} tickers.")


@bot.command(name="removewatch")
@commands.has_permissions(administrator=True)
async def remove_watch(ctx, ticker: str):
    t = ticker.upper().strip()
    if t in WATCHLIST:
        WATCHLIST.remove(t)
        await ctx.reply(f"✅ Removed `{t}` — watchlist now has {len(WATCHLIST)} tickers.")
    else:
        await ctx.reply(f"`{t}` not found in watchlist.")


@bot.command(name="pthelp")
async def pt_help(ctx):
    embed = discord.Embed(
        title="Phantom Traders Bot — Commands",
        color=discord.Color.from_str("#00C896")
    )
    embed.add_field(name="📊 Scanner", value=(
        "`!scan` — trigger manual scan *(Pro+)*\n"
        "`!status` — scanner status\n"
        "`!watchlist` — view watchlist *(Pro+)*\n"
        "`!addwatch TSLA` — add ticker *(Admin)*\n"
        "`!removewatch TSLA` — remove ticker *(Admin)*"
    ), inline=False)
    embed.add_field(name="👤 Roles *(Admin only)*", value=(
        "`!promote @user Pro Trader`\n"
        "`!demote @user Rookie`\n"
        "`!removeroles @user`\n"
        "`!whois @user`"
    ), inline=False)
    embed.add_field(name="🔧 Server *(Admin only)*", value=(
        "`!setup_server` — scaffold channels and roles"
    ), inline=False)
    embed.set_footer(text="Educational only — not financial advice.")
    await ctx.reply(embed=embed)


# ── ERROR HANDLER ─────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.reply("❌ You don't have the required role for that command.")
    elif isinstance(error, commands.MissingAnyRole):
        await ctx.reply("❌ You need Pro Trader or Elite role for that command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply("❌ Member not found. Mention them with @username.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ You need Administrator permission for that command.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"[error] {ctx.command}: {error}")


# ── ON READY ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"\n✓ Phantom Traders Bot online — {bot.user}")
    print(f"  Guild ID:  {GUILD_ID}")
    print(f"  Watchlist: {len(WATCHLIST)} tickers")
    print(f"  Scan interval: {SCAN_INTERVAL}s")
    print(f"  Finnhub key: {FINNHUB_KEY[:8]}...")
    scanner_loop.start()


# ── RUN ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set.")
        print("  export DISCORD_BOT_TOKEN='your_token_here'")
        print("  export DISCORD_GUILD_ID='your_server_id_here'")
        raise SystemExit(1)

    if not GUILD_ID:
        print("ERROR: DISCORD_GUILD_ID not set.")
        raise SystemExit(1)

    bot.run(BOT_TOKEN)
