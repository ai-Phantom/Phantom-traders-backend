"""
Phantom Traders — Discord Bot v3.1
====================================
Moderation v3.1:
  - External Discord invites → delete + strike + log
  - Non-approved links → delete + redirect prompt (NO strike)
  - Repeat spam → delete + strike + log
  - 3-strike system → auto-ban
  - Mod gets strike/dismiss buttons in #mod-log for every offence
  - NDA/NFA disclaimer on join, in rules, and on all embeds
"""

import asyncio
import os
import re
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
SITE_URL      = "https://aiphantomtraders.com"

ET = pytz.timezone("America/New_York")

NFA_NOTE = (
    "⚠️ Not financial advice. For educational purposes only. "
    "Always do your own research and trade at your own risk. "
    "NFA — Do your own due diligence."
)

NDA_NOTE = (
    "🔒 Non-Disclosure: All signals, strategies, scanners, and tools shared within "
    "Phantom Traders are proprietary and confidential. Do not share, redistribute, "
    "or replicate outside this community."
)

DISCLAIMER_FULL = f"{NFA_NOTE}\n\n{NDA_NOTE}"

# ── ROLE NAMES ────────────────────────────────────────────────────────────────

ROLE_ROOKIE = "Rookie"
ROLE_PRO    = "Pro Trader"
ROLE_ELITE  = "Elite"
ROLE_MOD    = "Moderator"

TIER_HIERARCHY = [ROLE_ROOKIE, ROLE_PRO, ROLE_ELITE]

# ── CHANNEL NAMES ─────────────────────────────────────────────────────────────

CH_WELCOME        = "welcome"
CH_RULES          = "rules"
CH_ANNOUNCEMENTS  = "announcements"
CH_HOW_TO_ROLES   = "how-to-get-roles"
CH_PREMARKET      = "premarket-movers"
CH_EARNINGS       = "earnings-watch"
CH_MACRO          = "macro-news"
CH_SECTOR         = "sector-rotation"
CH_PT_ALERTS      = "pt-alerts"
CH_OPTION_PLAYS   = "option-plays"
CH_MOMENTUM       = "momentum-setups"
CH_OPTIONS_FLOW   = "options-flow"
CH_SWING          = "swing-watchlist"
CH_ELITE_SIGNALS  = "elite-signals"
CH_ELITE_DISC     = "elite-discussion"
CH_PORTFOLIO_REV  = "portfolio-reviews"
CH_GENERAL        = "general"
CH_INTROS         = "introductions"
CH_WINS           = "wins-and-losses"
CH_CRITIQUE       = "portfolio-critique"
CH_OFF_TOPIC      = "off-topic"
CH_EDUCATION      = "education-portal"
CH_BOT_COMMANDS   = "pt-bot-commands"
CH_SCREENER       = "screener-drops"
CH_RISK_ALERTS    = "risk-score-alerts"
CH_TRADE_LOG      = "bot-trade-log"
CH_MOD_LOG        = "mod-log"

# ── MODERATION CONFIG ─────────────────────────────────────────────────────────

ALLOWED_DOMAINS = [
    "aiphantomtraders.com", "tradingview.com", "finviz.com",
    "finnhub.io", "finance.yahoo.com", "bloomberg.com",
    "marketwatch.com", "cnbc.com", "investopedia.com",
    "sec.gov", "barchart.com", "unusualwhales.com",
    "discord.com", "media.discordapp.net", "cdn.discordapp.com",
]

SPAM_REPEAT_LIMIT = 3  # same message X times = spam

# Strike tracker
user_strikes:  dict[int, int]  = {}
last_messages: dict[int, list] = {}

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
        ("welcome",           "Welcome to Phantom Traders — The Edge Every Trader Needs.", "free",  True,  True),
        ("rules",             "Community rules and guidelines.",                            "free",  False, True),
        ("announcements",     "Platform updates, news, and events.",                       "free",  True,  True),
        ("how-to-get-roles",  "How to unlock Pro Trader and Elite access.",                "free",  False, True),
    ]),
    ("📊 MARKET INTEL", [
        ("premarket-movers",  "Daily pre-market movers and gap alerts.",                   "pro",   False, True),
        ("earnings-watch",    "Upcoming earnings calendar and plays.",                     "pro",   False, True),
        ("macro-news",        "Fed, CPI, NFP, and macro market events.",                  "pro",   False, True),
        ("sector-rotation",   "Institutional sector momentum shifts.",                     "pro",   False, True),
    ]),
    ("⚡ TRADE SIGNALS", [
        ("pt-alerts",         "Live price, RSI, volume, and scanner alerts.",              "pro",   False, True),
        ("option-plays",      "AI-scanned options setups and callouts.",                   "pro",   False, True),
        ("momentum-setups",   "High-momentum breakout setups.",                            "pro",   False, True),
        ("options-flow",      "Unusual options activity and dark pool flow.",              "pro",   False, True),
        ("swing-watchlist",   "Swing trade candidates and setups.",                        "pro",   False, False),
    ]),
    ("👑 ELITE LOUNGE", [
        ("elite-signals",     "Priority high-conviction alerts and MACD reversals.",       "elite", False, True),
        ("elite-discussion",  "Deep-dive analysis for Elite members only.",                "elite", False, False),
        ("portfolio-reviews", "Elite peer portfolio reviews and critique.",                "elite", False, False),
    ]),
    ("💬 COMMUNITY", [
        ("general",           "General trading discussion.",                               "free",  False, False),
        ("introductions",     "Introduce yourself to the community.",                      "free",  False, False),
        ("wins-and-losses",   "Share your trades, wins, and lessons.",                     "free",  False, False),
        ("portfolio-critique","Post your portfolio for community feedback.",               "free",  False, False),
        ("off-topic",         "Off-topic chat — links allowed, keep it clean.",           "free",  False, False),
    ]),
    ("🎓 EDUCATION", [
        ("education-portal",  "All course material — visit aiphantomtraders.com.",        "free",  False, True),
    ]),
    ("🤖 PHANTOM TOOLS", [
        ("pt-bot-commands",   "Bot commands — type !pthelp to get started.",               "free",  False, False),
        ("screener-drops",    "Auto-posted scanner summaries.",                            "pro",   False, True),
        ("risk-score-alerts", "Portfolio risk score alerts.",                              "pro",   False, True),
        ("bot-trade-log",     "Callout log — W/L stats and performance history.",          "pro",   False, True),
    ]),
    ("🔒 MOD ONLY", [
        ("mod-log",           "Auto-moderation log — staff only.",                        "mod",   False, False),
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

alerted_today:    set[str]        = set()
last_scan_dt:     datetime | None = None
open_calls:       dict[int, dict] = {}
closed_calls:     list[dict]      = []
call_counter:     int             = 0
price_alerts:     list[dict]      = []
premarket_done:   bool            = False
market_open_done: bool            = False
earnings_done:    bool            = False

# ── INTENTS & BOT ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.guilds          = True
intents.members         = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5: return False
    return dtime(9, 30) <= now.time() <= dtime(16, 0)

def is_premarket() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5: return False
    return dtime(4, 0) <= now.time() < dtime(9, 30)

def is_trading_day() -> bool:
    return datetime.now(ET).weekday() < 5

def get_ch(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name=name)

def extract_urls(text: str) -> list[str]:
    return re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+|discord\.gg/[^\s<>"]+', text)

def is_allowed_url(url: str) -> bool:
    return any(domain in url for domain in ALLOWED_DOMAINS)

def is_discord_invite(text: str) -> bool:
    """Detect external Discord server invites."""
    invites = re.findall(r'discord\.gg/([^\s<>"]+)', text.lower())
    for inv in invites:
        if "cU9ywjWh" not in inv:  # allow your own server invite
            return True
    return False

def calc_stats() -> dict:
    if not closed_calls:
        return {"total": 0, "wins": 0, "losses": 0, "be": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    wins    = sum(1 for c in closed_calls if c["result"] in ("W", "WIN"))
    losses  = sum(1 for c in closed_calls if c["result"] in ("L", "LOSS"))
    be      = sum(1 for c in closed_calls if c["result"] in ("BE", "BREAKEVEN"))
    decided = wins + losses
    pnls    = [c.get("pnl_pct", 0) for c in closed_calls if c.get("pnl_pct") is not None]
    return {
        "total": len(closed_calls), "wins": wins, "losses": losses, "be": be,
        "win_rate": (wins / decided * 100) if decided else 0.0,
        "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0
    }

def build_overwrites(guild, access, role_objects, is_readonly=False):
    ow   = {}
    send = not is_readonly
    if access == "free":
        ow[guild.default_role] = discord.PermissionOverwrite(
            read_messages=True, send_messages=send,
            add_reactions=True, read_message_history=True,
        )
    elif access == "mod":
        ow[guild.default_role] = discord.PermissionOverwrite(read_messages=False, send_messages=False)
        if ROLE_MOD in role_objects:
            ow[role_objects[ROLE_MOD]] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                manage_messages=True, read_message_history=True,
            )
        return ow
    else:
        ow[guild.default_role] = discord.PermissionOverwrite(read_messages=False, send_messages=False)
        for rname in {"pro": [ROLE_PRO, ROLE_ELITE, ROLE_MOD], "elite": [ROLE_ELITE, ROLE_MOD]}.get(access, []):
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

# ── MOD LOG WITH STRIKE/DISMISS BUTTONS ──────────────────────────────────────

class StrikeView(discord.ui.View):
    def __init__(self, member: discord.Member, reason: str):
        super().__init__(timeout=86400)  # 24hr timeout
        self.member = member
        self.reason = reason

    @discord.ui.button(label="⚡ Add Strike", style=discord.ButtonStyle.danger)
    async def add_strike(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = self.member
        guild  = interaction.guild

        user_strikes[member.id] = user_strikes.get(member.id, 0) + 1
        strikes = user_strikes[member.id]

        # Update the mod log embed
        await interaction.response.edit_message(
            content=f"✅ **Strike added** by {interaction.user.mention} — {member.mention} now has **{strikes}/3** strikes.",
            view=None
        )

        if strikes >= 3:
            # Notify user then ban
            try:
                await member.send(
                    f"🚫 You have been **permanently banned** from Phantom Traders.\n"
                    f"Reason: {self.reason} (3rd strike)\n"
                    f"If you believe this is an error, contact us at {SITE_URL}."
                )
            except discord.Forbidden:
                pass
            try:
                await guild.ban(member, reason=f"3 strikes: {self.reason}", delete_message_days=1)
                ch_mod = get_ch(guild, CH_MOD_LOG)
                if ch_mod:
                    await ch_mod.send(f"🔨 **{member}** has been **banned** (3rd strike: {self.reason})")
            except discord.Forbidden:
                pass
        else:
            # Warn the user
            try:
                await member.send(
                    f"⚠️ **Warning {strikes}/3** from Phantom Traders.\n"
                    f"Reason: {self.reason}\n"
                    f"3 strikes results in a permanent ban. Please review **#rules** and our community standards.\n"
                    f"Visit {SITE_URL} for support."
                )
            except discord.Forbidden:
                pass

    @discord.ui.button(label="✅ Dismiss", style=discord.ButtonStyle.secondary)
    async def dismiss(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=f"✅ **Dismissed** by {interaction.user.mention} — no strike issued.",
            view=None
        )


async def log_offence(guild: discord.Guild, member: discord.Member, reason: str, message: discord.Message, offence_type: str):
    """Log offence to #mod-log with Strike/Dismiss buttons."""
    ch_mod = get_ch(guild, CH_MOD_LOG)
    if not ch_mod:
        return

    current_strikes = user_strikes.get(member.id, 0)
    color = "#FF4D6A" if current_strikes >= 2 else ("#F5C842" if current_strikes == 1 else "#4D9FFF")

    embed = discord.Embed(
        title=f"🚨 Moderation Alert — {offence_type}",
        color=discord.Color.from_str(color),
        timestamp=datetime.now(ET)
    )
    embed.add_field(name="👤 User",           value=f"{member.mention} (`{member}` | ID: {member.id})", inline=False)
    embed.add_field(name="📋 Offence",        value=reason,                                              inline=False)
    embed.add_field(name="📍 Channel",        value=f"#{message.channel.name}",                          inline=True)
    embed.add_field(name="⚡ Current Strikes", value=f"**{current_strikes}/3**",                          inline=True)
    embed.add_field(name="💬 Message",        value=f"```{message.content[:400]}```" if message.content else "*(no text)*", inline=False)
    embed.set_footer(text="Use the buttons below to add a strike or dismiss this offence.")

    view = StrikeView(member=member, reason=reason)
    try:
        await ch_mod.send(embed=embed, view=view)
    except discord.Forbidden:
        pass


# ── AUTO-MODERATION ───────────────────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    member   = message.author
    channel  = message.channel
    guild    = message.guild
    is_admin = channel.permissions_for(member).administrator
    has_mod  = discord.utils.get(member.roles, name=ROLE_MOD)

    if is_admin or has_mod:
        await bot.process_commands(message)
        return

    content = message.content
    deleted = False

    # ── Rule 1: External Discord invites → delete + log (strike/dismiss prompt) ──
    if not deleted and is_discord_invite(content):
        try:
            await message.delete()
            deleted = True
        except discord.Forbidden:
            pass
        await log_offence(guild, member, "Posted an external Discord server invite", message, "External Invite")

    # ── Rule 2: Non-approved URLs → delete + redirect (NO strike) ──
    if not deleted:
        urls = extract_urls(content)
        bad_urls = [u for u in urls if not is_allowed_url(u)]
        if bad_urls and channel.name != CH_OFF_TOPIC:
            try:
                await message.delete()
                deleted = True
            except discord.Forbidden:
                pass
            try:
                await channel.send(
                    f"Hey {member.mention} — external links aren't allowed in **#{channel.name}**. 😊\n"
                    f"If you'd like to share a link, please use **#off-topic**.\n"
                    f"Approved sources (TradingView, Yahoo Finance, Bloomberg, etc.) are always welcome in trading channels!",
                    delete_after=20
                )
            except discord.Forbidden:
                pass

    # ── Rule 3: Repeat message spam → delete + log (strike/dismiss prompt) ──
    if not deleted:
        uid = member.id
        if uid not in last_messages:
            last_messages[uid] = [content, 1]
        else:
            if last_messages[uid][0] == content:
                last_messages[uid][1] += 1
                if last_messages[uid][1] >= SPAM_REPEAT_LIMIT:
                    try:
                        await message.delete()
                        deleted = True
                    except discord.Forbidden:
                        pass
                    await log_offence(guild, member, f"Repeated the same message {SPAM_REPEAT_LIMIT}+ times", message, "Repeat Spam")
                    last_messages[uid] = [content, 0]
            else:
                last_messages[uid] = [content, 1]

    await bot.process_commands(message)


# ── CHANNEL POST BUILDERS ─────────────────────────────────────────────────────

async def post_welcome(ch: discord.TextChannel):
    embed = discord.Embed(
        title="👻 Welcome to Phantom Traders",
        description=(
            "## The Edge Every Trader Needs\n\n"
            "You've just joined one of the most powerful trading communities on the internet. "
            "Whether you're brand new to the markets or a seasoned pro — **you're in the right place.**\n\n"
            "Phantom Traders is built for one purpose: to give you the knowledge, tools, "
            "and community to trade with confidence."
        ),
        color=discord.Color.from_str("#00C896"),
    )
    embed.add_field(
        name="📊 Membership Tiers",
        value=(
            "🟢 **Rookie (Free)** — Community, education portal, introductions\n"
            "🔵 **Pro Trader** — Live signals, scanner alerts, market intel, pre-market briefings\n"
            "🟡 **Elite** — Everything in Pro + Elite Lounge, MACD reversals, priority signals"
        ),
        inline=False
    )
    embed.add_field(
        name="🚀 Get Started",
        value=(
            f"1️⃣ Read **#rules** — know the standards\n"
            f"2️⃣ Check **#how-to-get-roles** — unlock your tier\n"
            f"3️⃣ Visit **#education-portal** — start learning\n"
            f"4️⃣ Type `!pthelp` in **#pt-bot-commands** — explore the bot\n"
            f"5️⃣ Upgrade at **[{SITE_URL}]({SITE_URL})** — Pro Trader or Elite"
        ),
        inline=False
    )
    embed.add_field(
        name="🌐 Platform",
        value=f"[**{SITE_URL}**]({SITE_URL}) — AI-powered signals, courses, and tools.",
        inline=False
    )
    embed.set_footer(text=DISCLAIMER_FULL)
    await ch.send(embed=embed)


async def post_rules(ch: discord.TextChannel):
    embed = discord.Embed(
        title="📋 Phantom Traders — Community Rules",
        description=(
            "Phantom Traders is a professional trading community. "
            "These rules exist to protect the quality of the space for everyone. "
            "Violations are handled by our moderation bot and staff."
        ),
        color=discord.Color.from_str("#FF4D6A"),
    )
    rules = [
        ("1️⃣ Trading Content Only",
         "Keep all discussion relevant to markets, trading, and finance. Off-topic content goes in **#off-topic** only."),
        ("2️⃣ No External Server Invites",
         "Posting Discord invite links to other servers is an instant moderation offence. This is a zero-tolerance rule."),
        ("3️⃣ Approved Links Only in Trading Channels",
         "External links are only permitted in **#off-topic**. Approved financial sources (TradingView, Yahoo Finance, Bloomberg, SEC, etc.) are always welcome in trading channels."),
        ("4️⃣ No Spam",
         "Do not repeat the same message multiple times. Keep conversations meaningful and productive."),
        ("5️⃣ Respect Everyone",
         "No hate speech, personal attacks, harassment, or discrimination. This is a professional, inclusive environment."),
        ("6️⃣ No Solicitation",
         "Zero tolerance for 'DM me for signals', referral links, pump & dump promotions, or any form of unauthorized self-promotion."),
        ("7️⃣ NFA — Not Financial Advice",
         "All content shared here is for educational purposes only. Never present analysis as financial advice. Always encourage others to do their own research."),
        ("8️⃣ NDA — Non-Disclosure",
         "All signals, strategies, scanners, and tools within Phantom Traders are proprietary and confidential. Do not share or redistribute outside this community."),
        ("9️⃣ 3-Strike Policy",
         "**1st offence** → Mod reviews → Warning issued.\n**2nd offence** → Mod reviews → Final warning.\n**3rd offence** → Permanent ban.\nThe bot flags all offences and mods make the final call."),
    ]
    for name, value in rules:
        embed.add_field(name=name, value=value, inline=False)
    embed.add_field(
        name="✅ What We Love to See",
        value="Trade ideas, chart analysis, market discussion, questions, wins AND losses, and genuine community support.",
        inline=False
    )
    embed.set_footer(text=f"Phantom Traders • Rules enforced by PhantomBot • {SITE_URL}")
    await ch.send(embed=embed)


async def post_how_to_roles(ch: discord.TextChannel):
    embed = discord.Embed(
        title="🏷️ How to Unlock Your Role",
        description="Phantom Traders uses a tier system. Here's exactly how to level up:",
        color=discord.Color.from_str("#F5C842"),
    )
    embed.add_field(
        name="🟢 Rookie — Free",
        value=(
            "**Access:**\n"
            "• Community channels (general, wins/losses, introductions, off-topic)\n"
            "• Full education portal\n"
            "• `!status` and `!pthelp` bot commands\n\n"
            "**How:** Automatically assigned when you join! ✅"
        ),
        inline=False
    )
    embed.add_field(
        name="🔵 Pro Trader — Paid",
        value=(
            "**Access:**\n"
            "• Everything in Rookie\n"
            "• 📊 Market Intel — pre-market briefings, earnings, macro, sector rotation\n"
            "• ⚡ Trade Signals — scanner alerts, option plays, momentum, options flow\n"
            "• 🤖 Bot features — price alerts, RSI/volume alerts, trade callouts, screener drops\n\n"
            f"**How:** Subscribe at [{SITE_URL}]({SITE_URL}) → link your Discord → role auto-assigned! ✅"
        ),
        inline=False
    )
    embed.add_field(
        name="🟡 Elite — Premium",
        value=(
            "**Access:**\n"
            "• Everything in Pro Trader\n"
            "• 👑 Elite Lounge — exclusive high-conviction signals, deep-dive discussion, portfolio reviews\n"
            "• 🔄 MACD reversal alerts posted to #elite-signals\n"
            "• @here pings on HIGH-confidence scanner setups\n\n"
            f"**How:** Subscribe Elite at [{SITE_URL}]({SITE_URL}) → link your Discord → role auto-assigned! ✅"
        ),
        inline=False
    )
    embed.add_field(
        name="🔧 Role Not Showing? Already Subscribed?",
        value=(
            f"1. Ensure your Discord is linked at [{SITE_URL}]({SITE_URL})\n"
            "2. Type `!status` in **#pt-bot-commands**\n"
            "3. DM a **Moderator** for manual sync"
        ),
        inline=False
    )
    embed.set_footer(text=DISCLAIMER_FULL)
    await ch.send(embed=embed)


async def post_announcements(ch: discord.TextChannel):
    embed = discord.Embed(
        title="📢 Phantom Traders — Announcements",
        description=(
            "This channel is your source for all official Phantom Traders updates.\n\n"
            "• 🚀 New feature and bot releases\n"
            "• 📊 Scanner and signal updates\n"
            "• 🎓 New course launches\n"
            "• 🏆 Community events and competitions\n"
            "• 🔧 Maintenance and downtime notices\n\n"
            f"Stay up to date at **[{SITE_URL}]({SITE_URL})**"
        ),
        color=discord.Color.from_str("#4D9FFF"),
    )
    embed.set_footer(text=f"Phantom Traders • {SITE_URL}")
    await ch.send(embed=embed)


async def post_education_portal(ch: discord.TextChannel):
    header = discord.Embed(
        title="🎓 The Phantom Traders Education Portal",
        description=(
            "## Stop Gambling. Start Trading.\n\n"
            "Most traders lose money not because the markets are rigged — "
            "but because they were **never taught the right way to trade.**\n\n"
            "Phantom Traders courses are built different. No fluff, no theory overload. "
            "Just the exact frameworks, strategies, and setups that professional traders use every day.\n\n"
            "📚 **All courses are for learning and skill-building only.**\n"
            "Use the knowledge to develop your own edge — always do your own due diligence.\n\n"
            f"🌐 **Access all courses at [{SITE_URL}]({SITE_URL})**"
        ),
        color=discord.Color.from_str("#00C896"),
    )
    header.set_footer(text=DISCLAIMER_FULL)
    await ch.send(embed=header)
    await asyncio.sleep(1)

    courses = [
        {
            "emoji": "📈", "title": "Stock Trading Mastery",
            "hook": "Most stock traders lose because they trade on emotion, not edge. This course fixes that.",
            "desc": "Learn how to read price action, identify high-probability setups, and build a rules-based system that works in any market.",
            "topics": "• Price action & candlestick mastery\n• Support, resistance & trend trading\n• Moving averages & momentum\n• Risk management & position sizing\n• Building your personal trading plan",
            "color": "#4D9FFF",
        },
        {
            "emoji": "⚡", "title": "Options Trading Mastery",
            "hook": "Options are the most powerful instrument in the market — and the most misunderstood. Not anymore.",
            "desc": "Cut through the confusion and build a clear, practical framework for trading options profitably with defined risk.",
            "topics": "• Greeks decoded (Delta, Theta, IV, Vega)\n• Calls, puts, spreads & multi-leg strategies\n• Earnings plays & IV crush strategy\n• Iron condors, credit spreads & strangles\n• Scanning for high-probability setups",
            "color": "#00C896",
        },
        {
            "emoji": "🔮", "title": "Futures Trading Mastery",
            "hook": "No PDT rule. 23 hours a day. Built-in tax advantages. Futures are the pro's playground.",
            "desc": "Learn how to trade ES, NQ, CL, and GC with leverage, precision, and a professional risk framework.",
            "topics": "• Futures contracts, margin & leverage explained\n• ES, NQ, CL, GC setups & timing\n• 60/40 tax rule advantage\n• Overnight & pre-market strategy\n• Risk management for leveraged instruments",
            "color": "#9B59B6",
        },
        {
            "emoji": "💱", "title": "Forex Trading Mastery",
            "hook": "$7.5 trillion traded daily. Learn to navigate the world's largest market with precision.",
            "desc": "Master currency pairs using institutional-grade analysis, session timing, and proven price action strategies.",
            "topics": "• Major, minor & exotic pairs\n• Session timing & liquidity windows\n• Economic data & news trading\n• Fibonacci, ICT & Smart Money concepts\n• Risk-to-reward & trade management",
            "color": "#F5C842",
        },
        {
            "emoji": "₿", "title": "Crypto Trading Mastery",
            "hook": "Crypto never sleeps — and neither does opportunity. Learn to navigate the most volatile market on earth.",
            "desc": "From Bitcoin cycles to altcoins, DeFi, and on-chain data — build a framework for high-conviction crypto trades.",
            "topics": "• Bitcoin & altcoin market cycles\n• On-chain analysis & whale tracking\n• DeFi, NFTs & sector rotation\n• Exchange mechanics & liquidations\n• Risk management in volatile markets",
            "color": "#FF4D6A",
        },
    ]

    for course in courses:
        embed = discord.Embed(
            title=f"{course['emoji']} {course['title']}",
            description=f"*{course['hook']}*\n\n{course['desc']}",
            color=discord.Color.from_str(course["color"]),
        )
        embed.add_field(name="📚 What You'll Learn", value=course["topics"], inline=False)
        embed.add_field(
            name="🚀 Access This Course",
            value=(
                f"[**Start Learning Now → {SITE_URL}**]({SITE_URL})\n\n"
                f"*Use this knowledge to build your edge. Always do your own DD. {NFA_NOTE}*"
            ),
            inline=False
        )
        await ch.send(embed=embed)
        await asyncio.sleep(0.8)

    cta = discord.Embed(
        title="🔥 Ready to Get Serious About Trading?",
        description=(
            "The difference between traders who win consistently and those who don't "
            "comes down to **education, discipline, and the right tools.**\n\n"
            "Phantom Traders gives you all three.\n\n"
            f"**→ [{SITE_URL}]({SITE_URL})**\n\n"
            "✅ AI-powered trade signals\n"
            "✅ 5 professional trading courses\n"
            "✅ Live scanner & real-time alerts\n"
            "✅ Elite community of serious traders\n"
            "✅ Pro Trader & Elite Discord access\n\n"
            "📌 **Remember:** All content here is for learning purposes only. "
            "Use the tools to develop your own skills — always do your own due diligence before any trade."
        ),
        color=discord.Color.from_str("#F5C842"),
    )
    cta.set_footer(text=f"Phantom Traders • The Edge Every Trader Needs • {DISCLAIMER_FULL}")
    await ch.send(embed=cta)


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
        if not quote.get("c"): return None
        async with session.get(f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=rsi&timeperiod=14", headers=h) as r:
            rsi_raw = await r.json()
        async with session.get(f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=macd", headers=h) as r:
            macd_raw = await r.json()
        async with session.get(f"{base}/indicator?symbol={ticker}&resolution=D&from={from_ts}&to={now}&indicator=bbands", headers=h) as r:
            bb_raw = await r.json()
        hist_list = macd_raw.get("histogram") or [0, 0]
        return {
            "ticker": ticker, "quote": quote,
            "indicators": {
                "rsi":            (rsi_raw.get("rsi")      or [50])[-1],
                "macd":           (macd_raw.get("macd")    or [0])[-1],
                "macd_signal":    (macd_raw.get("signal")  or [0])[-1],
                "macd_hist":      hist_list[-1] if hist_list else 0,
                "macd_hist_prev": hist_list[-2] if len(hist_list) >= 2 else 0,
                "bb_upper":       (bb_raw.get("upperband") or [0])[-1],
                "bb_lower":       (bb_raw.get("lowerband") or [0])[-1],
                "volume":         quote.get("v", 0),
                "avg_volume":     quote.get("v", 0),
            }
        }
    except Exception as e:
        print(f"  [scanner] {ticker}: {e}")
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
            return [e for e in data.get("earningsCalendar", []) if e.get("symbol") in WATCHLIST]
    except Exception as e:
        print(f"  [earnings] {e}")
        return []

# ── SCANNER SCORING ───────────────────────────────────────────────────────────

def score_setup(ticker, quote, indicators):
    price     = quote.get("c", 0)
    prev      = quote.get("pc", 1)
    chg_pct   = ((price - prev) / prev * 100) if prev else 0
    rsi       = indicators.get("rsi", 50)
    macd      = indicators.get("macd", 0)
    macd_sig  = indicators.get("macd_signal", 0)
    bb_upper  = indicators.get("bb_upper", price * 1.05)
    bb_lower  = indicators.get("bb_lower", price * 0.95)
    vol_ratio = indicators.get("volume", 0) / (indicators.get("avg_volume", 1) or 1)
    score = 0; signals = []; direction = None

    if rsi < 32:                   score += 20; signals.append(f"RSI oversold ({rsi:.0f})");           direction = "CALL"
    if price <= bb_lower * 1.005:  score += 20; signals.append("At lower BB — bounce zone");           direction = "CALL"
    if macd > macd_sig and macd > 0: score += 15; signals.append("MACD bullish crossover above zero"); direction = direction or "CALL"
    if vol_ratio > 2.0 and chg_pct > 1.0: score += 15; signals.append(f"Volume surge {vol_ratio:.1f}x on up move"); direction = direction or "CALL"
    if rsi > 72:                   score += 20; signals.append(f"RSI overbought ({rsi:.0f})");         direction = "PUT"
    if price >= bb_upper * 0.995:  score += 20; signals.append("At upper BB — fade zone");             direction = "PUT"
    if macd < macd_sig and macd < 0: score += 15; signals.append("MACD bearish crossover below zero"); direction = direction or "PUT"
    if vol_ratio > 2.0 and chg_pct < -1.0: score += 15; signals.append(f"Volume surge {vol_ratio:.1f}x on down move"); direction = direction or "PUT"
    if len(signals) >= 3: score += 10
    if len(signals) < 2 or score < 45 or not direction: return None

    step   = 1 if price < 50 else (5 if price < 200 else 10)
    strike = round(price / step) * step + (step if direction == "CALL" else -step)
    conf   = "HIGH" if score >= 75 else ("MEDIUM" if score >= 55 else "LOW")
    return {"ticker": ticker, "price": price, "chg_pct": chg_pct, "direction": direction,
            "strike": strike, "signals": signals, "score": score, "confidence": conf,
            "rsi": rsi, "vol_ratio": vol_ratio}

# ── EMBED BUILDERS ────────────────────────────────────────────────────────────

def build_scanner_embed(setup):
    is_call  = setup["direction"] == "CALL"
    color    = "#00C896" if is_call else "#FF4D6A"
    conf_dot = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🟠"}[setup["confidence"]]
    embed    = discord.Embed(
        title=f"{'📈' if is_call else '📉'} {setup['ticker']} — {setup['direction']} SETUP",
        color=discord.Color.from_str(color), timestamp=datetime.now(ET)
    )
    embed.add_field(name="💰 Price",      value=f"**${setup['price']:.2f}** ({setup['chg_pct']:+.2f}%)", inline=True)
    embed.add_field(name="🎯 Strike",     value=f"**${setup['strike']:.0f} {setup['direction']}**",      inline=True)
    embed.add_field(name="📅 Expiry",     value="~30 DTE — next monthly",                                inline=True)
    embed.add_field(name="📊 Indicators", value=f"RSI: **{setup['rsi']:.0f}** | Vol: **{setup['vol_ratio']:.1f}x**", inline=True)
    embed.add_field(name=f"{conf_dot} Confidence", value=f"**{setup['confidence']}** ({setup['score']}/100)", inline=True)
    embed.add_field(name="⚡ Signals",    value="\n".join(f"→ {s}" for s in setup["signals"]), inline=False)
    embed.set_footer(text=NFA_NOTE)
    return embed

def build_call_embed(call, call_id):
    is_call = call["direction"] == "CALL"
    embed   = discord.Embed(
        title=f"{'📈' if is_call else '📉'} TRADE CALLOUT #{call_id} — {call['ticker']} {call['direction']}",
        color=discord.Color.from_str("#00C896" if is_call else "#FF4D6A"), timestamp=datetime.now(ET)
    )
    embed.add_field(name="💰 Entry",  value=f"**${call['entry']:.2f}**",               inline=True)
    embed.add_field(name="🎯 Strike", value=f"**${call['strike']} {call['direction']}**", inline=True)
    embed.add_field(name="📅 Expiry", value=f"**{call['expiry']}**",                   inline=True)
    embed.add_field(name="🎯 Target", value=f"**${call['target']:.2f}**",              inline=True)
    embed.add_field(name="🛑 Stop",   value=f"**${call['stop']:.2f}**",                inline=True)
    embed.add_field(name="👤 Caller", value=f"**{call['caller']}**",                   inline=True)
    if call.get("notes"):
        embed.add_field(name="📝 Notes", value=call["notes"], inline=False)
    embed.set_footer(text=f"Call #{call_id} | {NFA_NOTE}")
    return embed

def build_close_embed(call, call_id, result_label, color, exit_price, pnl_pct):
    embed = discord.Embed(
        title=f"🔒 CLOSED #{call_id} — {call['ticker']} {call['direction']} — {result_label}",
        color=discord.Color.from_str(color), timestamp=datetime.now(ET)
    )
    embed.add_field(name="📈 Entry",  value=f"${call['entry']:.2f}",                    inline=True)
    embed.add_field(name="📉 Exit",   value=f"${exit_price:.2f}" if exit_price else "N/A", inline=True)
    embed.add_field(name="💹 P&L",    value=f"{pnl_pct:+.2f}%" if exit_price else "N/A",  inline=True)
    embed.add_field(name="🎯 Strike", value=f"${call['strike']} {call['direction']}",   inline=True)
    embed.add_field(name="📅 Expiry", value=call["expiry"],                             inline=True)
    embed.add_field(name="👤 Caller", value=call["caller"],                             inline=True)
    embed.set_footer(text=f"Call #{call_id} | {NFA_NOTE}")
    return embed

def build_stats_embed():
    stats = calc_stats()
    color = "#00C896" if stats["win_rate"] >= 50 else "#FF4D6A"
    embed = discord.Embed(title="📊 Callout Performance — Phantom Traders",
                          color=discord.Color.from_str(color), timestamp=datetime.now(ET))
    embed.add_field(name="📋 Total",    value=f"**{stats['total']}**",          inline=True)
    embed.add_field(name="🏆 Wins",     value=f"**{stats['wins']}**",           inline=True)
    embed.add_field(name="💔 Losses",   value=f"**{stats['losses']}**",         inline=True)
    embed.add_field(name="🤝 BE",       value=f"**{stats['be']}**",             inline=True)
    embed.add_field(name="📈 Win Rate", value=f"**{stats['win_rate']:.1f}%**",  inline=True)
    embed.add_field(name="💹 Avg P&L",  value=f"**{stats['avg_pnl']:+.2f}%**", inline=True)
    if open_calls:
        embed.add_field(name="📭 Open Calls",
                        value="\n".join(f"#{cid} {c['ticker']} {c['direction']} ${c['strike']} {c['expiry']}"
                                        for cid, c in list(open_calls.items())[:5]), inline=False)
    if closed_calls:
        icon_map = {"W":"🏆","WIN":"🏆","L":"💔","LOSS":"💔","BE":"🤝","BREAKEVEN":"🤝"}
        lines = [f"{icon_map.get(c['result'],'❓')} #{c['call_id']} {c['ticker']} {c['direction']} — {c.get('pnl_pct',0):+.2f}%"
                 for c in closed_calls[-5:][::-1] if c.get("pnl_pct") is not None]
        if lines: embed.add_field(name="🕐 Recent", value="\n".join(lines), inline=False)
    embed.set_footer(text=NFA_NOTE)
    return embed

# ── SCHEDULED TASKS ───────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def daily_scheduler():
    global premarket_done, market_open_done, earnings_done
    now = datetime.now(ET)
    if not is_trading_day(): return
    if now.hour == 0 and now.minute == 0:
        premarket_done = market_open_done = earnings_done = False
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    if now.hour == 9 and now.minute == 0 and not premarket_done:
        premarket_done = True; await post_premarket_briefing(guild)
    if now.hour == 9 and now.minute == 30 and not market_open_done:
        market_open_done = True; await post_gap_alerts(guild)
    if now.hour == 9 and now.minute == 5 and not earnings_done:
        earnings_done = True; await post_earnings_calendar(guild)

async def post_premarket_briefing(guild):
    ch = get_ch(guild, CH_PREMARKET)
    if not ch: return
    movers = []
    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST[:12]:
            q = await fetch_quote(session, ticker)
            if q:
                prev = q.get("pc",1); price = q.get("c",0)
                movers.append((ticker, price, ((price-prev)/prev*100) if prev else 0))
            await asyncio.sleep(0.3)
    movers.sort(key=lambda x: abs(x[2]), reverse=True)
    embed = discord.Embed(title="🌅 Pre-Market Briefing — Phantom Traders",
                          description=f"Good morning traders! **{datetime.now(ET).strftime('%A, %B %d')}**",
                          color=discord.Color.from_str("#4D9FFF"), timestamp=datetime.now(ET))
    gainers = [(t,p,c) for t,p,c in movers if c>0][:5]
    losers  = [(t,p,c) for t,p,c in movers if c<0][:5]
    if gainers: embed.add_field(name="📈 Gainers", value="\n".join(f"`{t}` ${p:.2f} ({c:+.2f}%)" for t,p,c in gainers), inline=True)
    if losers:  embed.add_field(name="📉 Losers",  value="\n".join(f"`{t}` ${p:.2f} ({c:+.2f}%)" for t,p,c in losers),  inline=True)
    embed.add_field(name="⏰ Opens", value="NYSE/NASDAQ open **9:30am ET** — gap alerts incoming.", inline=False)
    embed.set_footer(text=NFA_NOTE)
    await ch.send(embed=embed)

async def post_gap_alerts(guild):
    ch = get_ch(guild, CH_PREMARKET)
    if not ch: return
    gaps = []
    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST:
            q = await fetch_quote(session, ticker)
            if q:
                prev = q.get("pc",1); price = q.get("c",0)
                chg  = ((price-prev)/prev*100) if prev else 0
                if abs(chg) >= 2.0: gaps.append((ticker, price, chg))
            await asyncio.sleep(0.3)
    if not gaps: return
    gaps.sort(key=lambda x: abs(x[2]), reverse=True)
    embed = discord.Embed(title="⚡ Market Open — Gap Alerts",
                          description="Tickers gapping 2%+ at open:",
                          color=discord.Color.from_str("#F5C842"), timestamp=datetime.now(ET))
    for t,p,c in gaps[:8]:
        embed.add_field(name=f"{'📈' if c>0 else '📉'} {t}", value=f"${p:.2f} ({c:+.2f}%)", inline=True)
    embed.set_footer(text=NFA_NOTE)
    await ch.send(embed=embed)

async def post_earnings_calendar(guild):
    ch = get_ch(guild, CH_EARNINGS)
    if not ch: return
    async with aiohttp.ClientSession() as session:
        earnings = await fetch_earnings(session)
    if not earnings: return
    embed = discord.Embed(title="📅 Earnings Watch — Next 7 Days",
                          description="Watchlist tickers reporting this week:",
                          color=discord.Color.from_str("#9B59B6"), timestamp=datetime.now(ET))
    for e in earnings[:10]:
        sym  = e.get("symbol","?"); date = e.get("date","?")
        when = e.get("hour","?");   est  = e.get("epsEstimate")
        when_str = "Before Open 🌅" if when=="bmo" else "After Close 🌙" if when=="amc" else when
        embed.add_field(name=f"`{sym}`",
                        value=f"📆 {date} — {when_str}{f' | EPS Est: **${est:.2f}**' if est else ''}",
                        inline=False)
    embed.set_footer(text="Always check IV before trading earnings. " + NFA_NOTE)
    await ch.send(embed=embed)

# ── MAIN SCANNER LOOP ─────────────────────────────────────────────────────────

@tasks.loop(seconds=SCAN_INTERVAL)
async def scanner_loop():
    global last_scan_dt
    if not is_market_open() and not is_premarket(): return
    now = datetime.now(ET)
    if last_scan_dt and last_scan_dt.date() < now.date(): alerted_today.clear()
    last_scan_dt = now
    print(f"[{now.strftime('%H:%M ET')}] Scanning {len(WATCHLIST)} tickers...")
    guild = bot.get_guild(GUILD_ID)
    if not guild: return

    ch_plays  = get_ch(guild, CH_OPTION_PLAYS)
    ch_elite  = get_ch(guild, CH_ELITE_SIGNALS)
    ch_screen = get_ch(guild, CH_SCREENER)
    ch_alerts = get_ch(guild, CH_PT_ALERTS)

    setups = []
    async with aiohttp.ClientSession() as session:
        for ticker in WATCHLIST:
            data = await fetch_ticker_data(session, ticker)
            if not data: await asyncio.sleep(0.35); continue
            setup = score_setup(ticker, data["quote"], data["indicators"])
            if setup: setups.append(setup)
            ind       = data["indicators"]
            hist      = ind.get("macd_hist", 0)
            hist_prev = ind.get("macd_hist_prev", 0)
            rsi       = ind.get("rsi", 50)
            vol_ratio = ind.get("volume", 0) / (ind.get("avg_volume", 1) or 1)
            price     = data["quote"].get("c", 0)
            prev      = data["quote"].get("pc", 1)
            chg_pct   = ((price-prev)/prev*100) if prev else 0

            # MACD reversal → #elite-signals
            macd_key = f"macd_{ticker}_{now.date()}"
            if macd_key not in alerted_today and ch_elite:
                if hist_prev < 0 < hist or hist_prev > 0 > hist:
                    bull = hist_prev < 0 < hist
                    rev  = discord.Embed(
                        title=f"🔄 MACD {'Bullish' if bull else 'Bearish'} Reversal — {ticker}",
                        description=f"MACD histogram crossed {'negative → positive (**bullish**)' if bull else 'positive → negative (**bearish**)'}.",
                        color=discord.Color.from_str("#00C896" if bull else "#FF4D6A"), timestamp=now)
                    rev.add_field(name="💰 Price",     value=f"**${price:.2f}**",                     inline=True)
                    rev.add_field(name="📊 MACD Hist", value=f"**{hist:.4f}** (was {hist_prev:.4f})", inline=True)
                    rev.set_footer(text=NFA_NOTE)
                    try: await ch_elite.send(embed=rev); alerted_today.add(macd_key)
                    except discord.Forbidden: pass

            # RSI extreme → #pt-alerts
            rsi_key = f"rsi_{ticker}_{now.date()}"
            if rsi_key not in alerted_today and ch_alerts and (rsi <= 25 or rsi >= 78):
                bull = rsi <= 25
                e = discord.Embed(
                    title=f"🔴 RSI Extreme {'Oversold' if bull else 'Overbought'} — {ticker}",
                    description=f"RSI hit **{rsi:.0f}** — {'heavily oversold, potential bounce' if bull else 'heavily overbought, potential pullback'}.",
                    color=discord.Color.from_str("#00C896" if bull else "#FF4D6A"), timestamp=now)
                e.add_field(name="💰 Price", value=f"**${price:.2f}**", inline=True)
                e.add_field(name="📊 RSI",   value=f"**{rsi:.0f}**",    inline=True)
                e.set_footer(text=NFA_NOTE)
                try: await ch_alerts.send(embed=e); alerted_today.add(rsi_key)
                except discord.Forbidden: pass

            # Volume spike → #pt-alerts
            vol_key = f"vol_{ticker}_{now.date()}"
            if vol_ratio >= 3.0 and vol_key not in alerted_today and ch_alerts:
                e = discord.Embed(title=f"⚡ Volume Spike — {ticker}",
                                  description=f"**{vol_ratio:.1f}x** above average volume detected.",
                                  color=discord.Color.from_str("#F5C842"), timestamp=now)
                e.add_field(name="💰 Price",  value=f"**${price:.2f}** ({chg_pct:+.2f}%)", inline=True)
                e.add_field(name="📊 Volume", value=f"**{vol_ratio:.1f}x** avg",            inline=True)
                e.set_footer(text=NFA_NOTE)
                try: await ch_alerts.send(embed=e); alerted_today.add(vol_key)
                except discord.Forbidden: pass

            await check_price_alerts(guild, ticker, price)
            await asyncio.sleep(0.35)

    if not setups: print("  No setups."); return
    setups.sort(key=lambda x: x["score"], reverse=True)
    for setup in setups:
        key = f"{setup['ticker']}_{setup['direction']}_{now.date()}"
        if key in alerted_today: continue
        embed = build_scanner_embed(setup)
        if ch_plays:
            try: await ch_plays.send(embed=embed); alerted_today.add(key)
            except discord.Forbidden: pass
        if ch_elite and setup["confidence"] == "HIGH":
            try:
                e2 = embed.copy(); e2.title = "👑 " + e2.title
                await ch_elite.send(content="@here — High-confidence setup", embed=e2)
            except discord.Forbidden: pass
        await asyncio.sleep(1)

    if ch_screen and setups:
        lines = [f"{'📈' if s['direction']=='CALL' else '📉'} **{s['ticker']}** — {s['direction']} | {s['score']}/100 | RSI {s['rsi']:.0f}"
                 for s in setups[:5]]
        summary = discord.Embed(title=f"🤖 Scanner Drop — {now.strftime('%b %d %I:%M %p ET')}",
                                description="\n".join(lines),
                                color=discord.Color.from_str("#4D9FFF"), timestamp=now)
        summary.set_footer(text=f"Scanned {len(WATCHLIST)} tickers • Full details in #option-plays | {NFA_NOTE}")
        try: await ch_screen.send(embed=summary)
        except discord.Forbidden: pass

# ── PRICE ALERT CHECKER ───────────────────────────────────────────────────────

async def check_price_alerts(guild, ticker, current_price):
    triggered = []
    for alert in price_alerts:
        if alert["ticker"] != ticker: continue
        hit = (alert["direction"] == "above" and current_price >= alert["target"]) or \
              (alert["direction"] == "below" and current_price <= alert["target"])
        if hit:
            triggered.append(alert)
            ch = guild.get_channel(alert["channel_id"])
            if ch:
                e = discord.Embed(title=f"🔔 Price Alert — {ticker}",
                                  description=f"<@{alert['user_id']}> **{ticker}** hit **${current_price:.2f}**!",
                                  color=discord.Color.from_str("#F5C842"), timestamp=datetime.now(ET))
                e.add_field(name="🎯 Target",  value=f"${alert['target']:.2f}", inline=True)
                e.add_field(name="💰 Current", value=f"${current_price:.2f}",   inline=True)
                e.set_footer(text=NFA_NOTE)
                try: await ch.send(embed=e)
                except discord.Forbidden: pass
    for a in triggered: price_alerts.remove(a)

# ── ROLE MANAGEMENT ───────────────────────────────────────────────────────────

async def set_member_tier(member, new_tier, reason="Subscription update"):
    roles_to_remove = [r for r in [discord.utils.get(member.guild.roles, name=t) for t in TIER_HIERARCHY] if r and r in member.roles]
    role_to_add     = discord.utils.get(member.guild.roles, name=new_tier) if new_tier in TIER_HIERARCHY else None
    if roles_to_remove: await member.remove_roles(*roles_to_remove, reason=reason)
    if role_to_add:     await member.add_roles(role_to_add, reason=reason); return f"✅ {member.display_name} → **{new_tier}**"
    return f"✅ {member.display_name} → roles cleared (Free/Rookie)"

# ── ON MEMBER JOIN ────────────────────────────────────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
    guild  = member.guild
    rookie = discord.utils.get(guild.roles, name=ROLE_ROOKIE)
    if rookie:
        try: await member.add_roles(rookie, reason="Auto-assigned on join")
        except discord.Forbidden: pass
    try:
        embed = discord.Embed(
            title="👻 Welcome to Phantom Traders!",
            description=f"Hey **{member.display_name}** — The Edge Every Trader Needs starts here! 🎉",
            color=discord.Color.from_str("#00C896"), timestamp=datetime.now(ET)
        )
        embed.add_field(name="📋 Step 1 — Rules",      value="Read **#rules** — know the standards and the NDA/NFA policy.", inline=False)
        embed.add_field(name="🎓 Step 2 — Learn",      value="Visit **#education-portal** — 5 professional trading courses.", inline=False)
        embed.add_field(name="⚡ Step 3 — Upgrade",    value=f"Subscribe at **[{SITE_URL}]({SITE_URL})** → Pro Trader or Elite → role auto-assigned.", inline=False)
        embed.add_field(name="🤖 Step 4 — Explore",   value="Type `!pthelp` in **#pt-bot-commands** to explore all bot features.", inline=False)
        embed.add_field(
            name="⚠️ Important Disclaimer",
            value=(
                f"**NFA:** All content is educational only. Always do your own due diligence before any trade.\n"
                f"**NDA:** All signals, strategies, and tools are proprietary. Do not redistribute outside this server."
            ),
            inline=False
        )
        embed.set_footer(text=DISCLAIMER_FULL)
        await member.send(embed=embed)
    except discord.Forbidden:
        ch = get_ch(guild, CH_WELCOME)
        if ch:
            try:
                await ch.send(
                    f"👋 Welcome {member.mention}! Check **#rules**, **#education-portal**, and type `!pthelp` to get started. "
                    f"All content is NFA — educational only. Do your own DD always."
                )
            except discord.Forbidden: pass

# ── COMMANDS ──────────────────────────────────────────────────────────────────

@bot.command(name="setup_posts")
@commands.has_permissions(administrator=True)
async def setup_posts(ctx):
    guild = ctx.guild
    await ctx.reply("📝 Posting channel content... ~30 seconds.")
    tasks_map = [
        (CH_WELCOME,      post_welcome),
        (CH_RULES,        post_rules),
        (CH_HOW_TO_ROLES, post_how_to_roles),
        (CH_ANNOUNCEMENTS,post_announcements),
        (CH_EDUCATION,    post_education_portal),
    ]
    posted = 0
    for ch_name, fn in tasks_map:
        ch = get_ch(guild, ch_name)
        if ch:
            try: await fn(ch); posted += 1; await asyncio.sleep(1)
            except Exception as e: print(f"  Error posting #{ch_name}: {e}")
        else:
            print(f"  #{ch_name} not found — run !setup_server first")
    await ctx.reply(f"✅ Posted to {posted}/{len(tasks_map)} channels!")

@bot.command(name="setup_server")
@commands.has_permissions(administrator=True)
async def setup_server(ctx):
    guild = ctx.guild
    await ctx.reply("🔧 Setting up server... ~60 seconds.")
    role_objects = {}
    role_configs = {
        ROLE_ROOKIE: discord.Color.from_str("#6E7F96"),
        ROLE_PRO:    discord.Color.from_str("#00C896"),
        ROLE_ELITE:  discord.Color.from_str("#F5C842"),
        ROLE_MOD:    discord.Color.from_str("#FF4D6A"),
    }
    existing_roles = {r.name: r for r in guild.roles}
    for rname, rcolor in role_configs.items():
        if rname in existing_roles: role_objects[rname] = existing_roles[rname]
        else:
            r = await guild.create_role(name=rname, color=rcolor, mentionable=True, reason="PT setup")
            role_objects[rname] = r; await asyncio.sleep(0.3)

    existing_cats  = {c.name: c for c in guild.categories}
    existing_chans = {c.name: c for c in guild.channels}
    created = skipped = 0

    for cat_name, channels in SERVER_STRUCTURE:
        category = existing_cats.get(cat_name) or await guild.create_category(cat_name, reason="PT setup")
        await asyncio.sleep(0.4)
        for ch_name, topic, access, is_announce, is_readonly in channels:
            if ch_name in existing_chans: skipped += 1; continue
            ow = build_overwrites(guild, access, role_objects, is_readonly)
            try:
                if is_announce:
                    await guild.create_text_channel(ch_name, category=category, topic=topic, overwrites=ow, news=True, reason="PT setup")
                else:
                    await guild.create_text_channel(ch_name, category=category, topic=topic, overwrites=ow, reason="PT setup")
                created += 1; await asyncio.sleep(0.5)
            except Exception as e: print(f"  Error #{ch_name}: {e}")

    for cat_name, voice_list in VOICE_CHANNELS.items():
        category = existing_cats.get(cat_name) or await guild.create_category(cat_name, reason="PT setup")
        await asyncio.sleep(0.4)
        for vname, access in voice_list:
            if vname not in existing_chans:
                ow = build_overwrites(guild, access, role_objects)
                await guild.create_voice_channel(vname, category=category, overwrites=ow, reason="PT setup")
                created += 1; await asyncio.sleep(0.5)
            else: skipped += 1

    await ctx.reply(
        f"✅ **Server setup complete!**\n"
        f"Created: {created} | Skipped: {skipped}\n\n"
        f"Now run `!setup_posts` to populate all channel content!\n\n"
        f"**Rookie** → Community + Education\n"
        f"**Pro Trader** → + Market Intel + Signals + Scanner\n"
        f"**Elite** → + Elite Lounge + MACD Reversals\n"
        f"**Moderator** → + #mod-log (staff only)"
    )

@bot.command(name="promote")
@commands.has_permissions(administrator=True)
async def promote(ctx, member: discord.Member, *, tier: str):
    tier = tier.title()
    if tier not in TIER_HIERARCHY: await ctx.reply("❌ Use: Rookie, Pro Trader, Elite"); return
    await ctx.reply(await set_member_tier(member, tier, reason=f"Promoted by {ctx.author}"))

@bot.command(name="demote")
@commands.has_permissions(administrator=True)
async def demote(ctx, member: discord.Member, *, tier: str):
    tier = tier.title()
    if tier not in TIER_HIERARCHY: await ctx.reply("❌ Use: Rookie, Pro Trader, Elite"); return
    await ctx.reply(await set_member_tier(member, tier, reason=f"Demoted by {ctx.author}"))

@bot.command(name="removeroles")
@commands.has_permissions(administrator=True)
async def remove_roles_cmd(ctx, member: discord.Member):
    await ctx.reply(await set_member_tier(member, "", reason=f"Cleared by {ctx.author}"))

@bot.command(name="whois")
@commands.has_permissions(administrator=True)
async def whois(ctx, member: discord.Member):
    roles = [r.name for r in member.roles if r.name in TIER_HIERARCHY]
    await ctx.reply(f"**{member.display_name}** — {', '.join(roles) if roles else 'Free/Rookie'}")

@bot.command(name="strikes")
@commands.has_permissions(administrator=True)
async def check_strikes(ctx, member: discord.Member):
    count = user_strikes.get(member.id, 0)
    await ctx.reply(f"**{member.display_name}** — **{count}/3** strikes.")

@bot.command(name="clearstrikes")
@commands.has_permissions(administrator=True)
async def clear_strikes(ctx, member: discord.Member):
    user_strikes[member.id] = 0
    await ctx.reply(f"✅ Strikes cleared for **{member.display_name}**.")

@bot.command(name="call")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def trade_call(ctx, ticker: str, direction: str, strike: str, expiry: str, target: str, stop: str, *, notes: str = ""):
    """!call TSLA CALL 250 04/18 265 235 [notes]"""
    global call_counter
    direction = direction.upper()
    if direction not in ("CALL","PUT"): await ctx.reply("❌ Direction must be CALL or PUT."); return
    try:
        strike_f = float(strike.replace("$","")); target_f = float(target.replace("$","")); stop_f = float(stop.replace("$",""))
    except ValueError:
        await ctx.reply("❌ Strike, target, stop must be numbers."); return
    async with aiohttp.ClientSession() as session:
        quote = await fetch_quote(session, ticker.upper())
    entry = quote.get("c", 0.0) if quote else 0.0
    call_counter += 1; call_id = call_counter
    call_data = {"ticker": ticker.upper(), "direction": direction, "strike": strike_f,
                 "expiry": expiry, "entry": entry, "target": target_f, "stop": stop_f,
                 "notes": notes, "caller": str(ctx.author.display_name),
                 "caller_id": ctx.author.id, "opened_at": datetime.now(ET).isoformat()}
    open_calls[call_id] = call_data
    embed    = build_call_embed(call_data, call_id)
    ch_plays = get_ch(ctx.guild, CH_OPTION_PLAYS)
    ch_log   = get_ch(ctx.guild, CH_TRADE_LOG)
    if ch_plays: await ch_plays.send(embed=embed)
    else: await ctx.reply(embed=embed)
    if ch_log:
        log = discord.Embed(title=f"📋 New Call #{call_id} — {ticker.upper()} {direction}",
                            color=discord.Color.from_str("#4D9FFF"), timestamp=datetime.now(ET))
        log.add_field(name="Entry",   value=f"${entry:.2f}",    inline=True)
        log.add_field(name="Target",  value=f"${target_f:.2f}", inline=True)
        log.add_field(name="Stop",    value=f"${stop_f:.2f}",   inline=True)
        log.add_field(name="Details", value=f"${strike_f} {direction} exp {expiry}", inline=False)
        log.add_field(name="Status",  value="🟡 OPEN", inline=True)
        log.set_footer(text=NFA_NOTE)
        await ch_log.send(embed=log)
    if ctx.channel != ch_plays:
        await ctx.reply(f"✅ Callout #{call_id} posted!")

@bot.command(name="calls")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def view_calls(ctx):
    if not open_calls: await ctx.reply("📭 No open callouts."); return
    embed = discord.Embed(title=f"📋 Open Callouts ({len(open_calls)})",
                          color=discord.Color.from_str("#4D9FFF"), timestamp=datetime.now(ET))
    for cid, c in list(open_calls.items())[:10]:
        embed.add_field(
            name=f"{'📈' if c['direction']=='CALL' else '📉'} #{cid} {c['ticker']} {c['direction']}",
            value=f"Strike **${c['strike']}** | Exp **{c['expiry']}** | Target **${c['target']}** | Stop **${c['stop']}**\nBy: {c['caller']}",
            inline=False)
    embed.set_footer(text=f"!closecall <id> W/L [exit] | {NFA_NOTE}")
    await ctx.reply(embed=embed)

@bot.command(name="closecall")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def close_call(ctx, call_id: int, result: str, exit_price: float = 0.0):
    if call_id not in open_calls: await ctx.reply(f"❌ Call #{call_id} not found."); return
    result = result.upper()
    if result not in ("W","L","WIN","LOSS","BE","BREAKEVEN"): await ctx.reply("❌ Use W, L, or BE."); return
    call = open_calls.pop(call_id)
    labels = {"W":"WIN 🏆","WIN":"WIN 🏆","L":"LOSS 💔","LOSS":"LOSS 💔","BE":"BREAKEVEN 🤝","BREAKEVEN":"BREAKEVEN 🤝"}
    colors = {"W":"#00C896","WIN":"#00C896","L":"#FF4D6A","LOSS":"#FF4D6A","BE":"#4D9FFF","BREAKEVEN":"#4D9FFF"}
    pnl_pct = 0.0
    if exit_price and call["entry"]:
        pnl_pct = (exit_price - call["entry"]) / call["entry"] * 100
        if call["direction"] == "PUT": pnl_pct = -pnl_pct
    closed_calls.append({"call_id": call_id, "ticker": call["ticker"], "direction": call["direction"],
                         "result": result, "pnl_pct": pnl_pct if exit_price else None, "caller": call["caller"]})
    embed    = build_close_embed(call, call_id, labels[result], colors[result], exit_price, pnl_pct)
    ch_wins  = get_ch(ctx.guild, CH_WINS)
    ch_plays = get_ch(ctx.guild, CH_OPTION_PLAYS)
    ch_log   = get_ch(ctx.guild, CH_TRADE_LOG)
    if ch_wins:  await ch_wins.send(embed=embed)
    if ch_plays: await ch_plays.send(embed=embed)
    if ch_log:   await ch_log.send(embed=embed); await ch_log.send(embed=build_stats_embed())
    if ctx.channel not in [ch_wins, ch_plays, ch_log]:
        await ctx.reply(f"✅ Call #{call_id} closed as {labels[result]}")

@bot.command(name="stats")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def show_stats(ctx):
    await ctx.reply(embed=build_stats_embed())

@bot.command(name="alert")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def set_alert(ctx, ticker: str, price: float):
    ticker = ticker.upper()
    async with aiohttp.ClientSession() as session:
        quote = await fetch_quote(session, ticker)
    if not quote: await ctx.reply(f"❌ Ticker `{ticker}` not found."); return
    current   = quote.get("c", 0)
    direction = "above" if price > current else "below"
    price_alerts.append({"user_id": ctx.author.id, "channel_id": ctx.channel.id,
                         "ticker": ticker, "target": price, "direction": direction})
    await ctx.reply(f"🔔 Alert set — I'll ping you when **{ticker}** goes **{direction} ${price:.2f}**\nCurrent: **${current:.2f}**\n\n*{NFA_NOTE}*")

@bot.command(name="alerts")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def view_alerts(ctx):
    my = [a for a in price_alerts if a["user_id"] == ctx.author.id]
    if not my: await ctx.reply("📭 No active alerts. Use `!alert TSLA 250`."); return
    await ctx.reply("**Your Alerts:**\n" + "\n".join(f"`{a['ticker']}` {a['direction']} **${a['target']:.2f}**" for a in my))

@bot.command(name="cancelalert")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def cancel_alert(ctx, ticker: str):
    ticker = ticker.upper()
    before = len(price_alerts)
    price_alerts[:] = [a for a in price_alerts if not (a["user_id"]==ctx.author.id and a["ticker"]==ticker)]
    removed = before - len(price_alerts)
    await ctx.reply(f"✅ Cancelled {removed} alert(s) for `{ticker}`." if removed else f"❌ No alerts for `{ticker}`.")

@bot.command(name="scan")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def manual_scan(ctx):
    await ctx.reply("🔍 Running manual scan — results in #option-plays shortly.")
    scanner_loop.restart()

@bot.command(name="status")
async def status(ctx):
    now   = datetime.now(ET)
    state = "🟢 MARKET OPEN" if is_market_open() else "🟡 PRE-MARKET" if is_premarket() else "🔴 MARKET CLOSED"
    last  = last_scan_dt.strftime("%I:%M %p ET") if last_scan_dt else "Never"
    stats = calc_stats()
    await ctx.reply(
        f"**👻 Phantom Traders Bot v3.1**\n"
        f"Market: {state}\n"
        f"Last scan: {last}\n"
        f"Open callouts: {len(open_calls)} | Active alerts: {len(price_alerts)}\n"
        f"Win rate: **{stats['win_rate']:.1f}%** ({stats['wins']}W/{stats['losses']}L)\n"
        f"Watchlist: {len(WATCHLIST)} tickers"
    )

@bot.command(name="watchlist")
@commands.has_any_role(ROLE_PRO, ROLE_ELITE, ROLE_MOD)
async def show_watchlist(ctx):
    await ctx.reply("**Scanner Watchlist:**\n" + "  ".join(f"`{t}`" for t in WATCHLIST))

@bot.command(name="addwatch")
@commands.has_permissions(administrator=True)
async def add_watch(ctx, ticker: str):
    t = ticker.upper().strip()
    if t in WATCHLIST: await ctx.reply(f"`{t}` already in watchlist.")
    else: WATCHLIST.append(t); await ctx.reply(f"✅ Added `{t}` — {len(WATCHLIST)} tickers total.")

@bot.command(name="removewatch")
@commands.has_permissions(administrator=True)
async def remove_watch(ctx, ticker: str):
    t = ticker.upper().strip()
    if t in WATCHLIST: WATCHLIST.remove(t); await ctx.reply(f"✅ Removed `{t}`.")
    else: await ctx.reply(f"❌ `{t}` not in watchlist.")

@bot.command(name="pthelp")
async def pt_help(ctx):
    embed = discord.Embed(title="👻 Phantom Traders Bot v3.1 — Commands",
                          color=discord.Color.from_str("#00C896"))
    embed.add_field(name="📣 Callouts *(Pro Trader/Elite)*", value=(
        "`!call TSLA CALL 250 04/18 265 235 [notes]`\n"
        "`!calls` — open callouts\n"
        "`!closecall <id> W/L [exit]` — close a call\n"
        "`!stats` — W/L performance"
    ), inline=False)
    embed.add_field(name="🔔 Price Alerts *(Pro Trader/Elite)*", value=(
        "`!alert NVDA 900` | `!alerts` | `!cancelalert NVDA`"
    ), inline=False)
    embed.add_field(name="📊 Scanner *(Pro Trader/Elite)*", value=(
        "`!scan` | `!status` *(anyone)* | `!watchlist`\n"
        "`!addwatch TSLA` / `!removewatch TSLA` *(Admin)*"
    ), inline=False)
    embed.add_field(name="👤 Roles *(Admin)*", value=(
        "`!promote @user Pro Trader` / `!promote @user Elite`\n"
        "`!demote @user Rookie` | `!removeroles @user` | `!whois @user`"
    ), inline=False)
    embed.add_field(name="🔨 Moderation *(Admin)*", value=(
        "`!strikes @user` — check strike count\n"
        "`!clearstrikes @user` — reset strikes"
    ), inline=False)
    embed.add_field(name="🔧 Setup *(Admin)*", value=(
        "`!setup_server` — create all channels & roles\n"
        "`!setup_posts` — post content to info & education channels"
    ), inline=False)
    embed.add_field(name="🏷️ Tiers", value=(
        "**Rookie** → Community + Education\n"
        "**Pro Trader** → + Market Intel + Signals + Scanner + Alerts\n"
        "**Elite** → + Elite Lounge + MACD Reversals"
    ), inline=False)
    embed.set_footer(text=DISCLAIMER_FULL)
    await ctx.reply(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions): await ctx.reply("❌ Administrator permission required.")
    elif isinstance(error, commands.MissingRole): await ctx.reply("❌ Missing required role.")
    elif isinstance(error, commands.MissingAnyRole): await ctx.reply("❌ Need Pro Trader or Elite role.")
    elif isinstance(error, commands.MemberNotFound): await ctx.reply("❌ Member not found.")
    elif isinstance(error, commands.BadArgument): await ctx.reply("❌ Invalid argument. Check `!pthelp`.")
    elif isinstance(error, commands.CommandNotFound): pass
    else: print(f"[error] {ctx.command}: {error}")

@bot.event
async def on_ready():
    print(f"\n✓ Phantom Traders Bot v3.1 online — {bot.user}")
    print(f"  Guild: {GUILD_ID} | Watchlist: {len(WATCHLIST)} | Interval: {SCAN_INTERVAL}s")
    scanner_loop.start()
    daily_scheduler.start()

if __name__ == "__main__":
    if not BOT_TOKEN: print("ERROR: DISCORD_BOT_TOKEN not set."); raise SystemExit(1)
    if not GUILD_ID:  print("ERROR: DISCORD_GUILD_ID not set.");  raise SystemExit(1)
    bot.run(BOT_TOKEN)
