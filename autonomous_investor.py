#!/usr/bin/env python3
"""
Long-Term Hold Bot v5.0
Features:
- Fundamentals-Scored Buy & Hold Strategy (no leveraged/inverse ETFs, no daily rotation)
- Broad Market Baseline + Individual Stocks (NVDA, AAPL, TSLA, AMD, META, AMZN, GOOGL, MSFT) + Crypto sleeve
- Per-Asset Trailing Stops (only mechanism that ever exits a position)
- Performance vs S&P 500 Tracking
- Paper Trading Comparison
"""

import json
import math
import os
import subprocess
import smtplib
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
import ssl
import re
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict

# =============================================================================
# CONFIGURATION
# =============================================================================

CONFIG_DIR = Path.home() / ".autonomous_investor"
CONFIG_DIR.mkdir(exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "config.json"
BRAIN_FILE = CONFIG_DIR / "brain.json"
PORTFOLIO_FILE = CONFIG_DIR / "portfolio.json"
LOG_FILE = CONFIG_DIR / "activity.log"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# =============================================================================
# ENHANCED ASSET DEFINITIONS WITH SECTORS
# =============================================================================

ASSETS = {
    # No broad-market anchor by design — this bot only holds discovered growth
    # candidates + crypto, not an index fund. Individual stocks are not a fixed
    # list here — they're discovered dynamically from a small/mid-cap growth
    # screen (see discover_stock_universe) and stored in brain["discovered_universe"],
    # merged with this dict at runtime.
    # === CRYPTO ===
    "CRYPTO": {
        "name": "Bitcoin ETF",
        "ticker": "IBIT",
        "sector": "crypto",
        "base_return": 15.0,
        "volatility": 60.0,
        "leverage": 1,
        "trailing_stop_pct": 12.0
    },
}

# Sector limits (max % of portfolio)
SECTOR_LIMITS = {
    "individual_growth": 0.60,  # 6 holdings max @ 10% each — see calculate_target_allocation
    "crypto": 0.15
}

# Correlation matrix (simplified). Left empty — the discovered-stock universe
# changes over time, so a hardcoded pair table doesn't stay meaningful. Any pair
# not listed here falls back to a moderate default in check_correlation_risk.
CORRELATIONS = {}


# =============================================================================
# LOGGING
# =============================================================================

def log(message: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{level}] {message}"
    print(entry)
    with open(LOG_FILE, 'a') as f:
        f.write(entry + "\n")


# =============================================================================
# DATA PERSISTENCE
# =============================================================================

KEYCHAIN_SERVICE = "autonomous_investor"
KEYCHAIN_SECRET_KEYS = ("alpaca_api_key", "alpaca_api_secret", "email_password")

def _keychain_get(account: str) -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def load_config() -> dict:
    config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    for key in KEYCHAIN_SECRET_KEYS:
        value = _keychain_get(key)
        if value:
            config[key] = value
    return config

def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

DEFAULT_ALLOCATION = {
    "CRYPTO": 0.05,
}

def initialize_learning_state(brain: dict):
    """Ensure brain['learning'] exists with all required sub-keys."""
    defaults = {
        "open_positions": {},
        "closed_trades": [],
        "stop_loss_events": [],
        "learned_stop_adjustments": {},
        "total_cycles": 0,
        "last_cycle": None,
    }
    if "learning" not in brain:
        brain["learning"] = defaults
    else:
        for key, val in defaults.items():
            if key not in brain["learning"]:
                brain["learning"][key] = val

def load_brain() -> dict:
    if BRAIN_FILE.exists():
        with open(BRAIN_FILE) as f:
            brain = json.load(f)
        # Migrate: if base_allocation has old keys, reset to new defaults
        current_keys = set(brain.get("base_allocation", {}).keys())
        expected_keys = set(ASSETS.keys())
        if current_keys != expected_keys:
            log("Migrating brain allocation to new asset universe", "INFO")
            brain["base_allocation"] = DEFAULT_ALLOCATION.copy()
            brain["trailing_stops"] = {}
        initialize_learning_state(brain)
        return brain
    brain = {
        "base_allocation": DEFAULT_ALLOCATION.copy(),
        "performance_history": [],
        "spy_benchmark": [],
        "trailing_stops": {},
        "total_trades": 0,
        "dca_schedule": {}
    }
    initialize_learning_state(brain)
    return brain

def save_brain(brain: dict):
    with open(BRAIN_FILE, 'w') as f:
        json.dump(brain, f, indent=2)

# =============================================================================
# SELF-LEARNING: TRADE OUTCOME TRACKING
# =============================================================================

def track_trade_outcomes(client, brain: dict):
    """Track position entries/exits and calculate trade outcomes."""
    learning = brain["learning"]
    open_pos = learning["open_positions"]
    today = datetime.now().isoformat()[:10]

    try:
        positions = client.get_positions()
    except Exception:
        return

    live_symbols = {}
    for pos in positions:
        symbol = pos["symbol"]
        live_symbols[symbol] = {
            "qty": float(pos["qty"]),
            "current_price": float(pos["current_price"]),
            "avg_entry_price": float(pos["avg_entry_price"]),
        }

    # Detect new positions
    for symbol, info in live_symbols.items():
        if symbol not in open_pos:
            open_pos[symbol] = {
                "entry_price": info["avg_entry_price"],
                "entry_date": today,
                "qty": info["qty"],
            }

    # Detect closed positions
    closed_symbols = [s for s in list(open_pos.keys()) if s not in live_symbols]
    for symbol in closed_symbols:
        entry = open_pos.pop(symbol)
        entry_price = entry["entry_price"]
        # Use last known price from Alpaca or estimate
        try:
            exit_price = client.get_last_price(symbol)
        except Exception:
            exit_price = entry_price

        if entry_price > 0:
            return_pct = ((exit_price - entry_price) / entry_price) * 100
        else:
            return_pct = 0.0

        entry_date = entry.get("entry_date", today)
        try:
            holding_days = (datetime.fromisoformat(today) - datetime.fromisoformat(entry_date)).days
        except Exception:
            holding_days = 0

        learning["closed_trades"].append({
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return_pct": return_pct,
            "entry_date": entry_date,
            "exit_date": today,
            "holding_days": holding_days,
        })

    # 90-day rolling window on closed_trades
    cutoff = (datetime.now() - timedelta(days=60)).isoformat()[:10]
    learning["closed_trades"] = [
        t for t in learning["closed_trades"]
        if t.get("exit_date", "") >= cutoff
    ]


def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {"snapshots": [], "trades": [], "initial_value": 100000}

def save_portfolio(portfolio: dict):
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(portfolio, f, indent=2)


# =============================================================================
# ALPACA CLIENT
# =============================================================================

class AlpacaClient:
    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        self.data_url = "https://data.alpaca.markets"

    def _request(self, method: str, endpoint: str, data: dict = None, use_data_api: bool = False) -> dict:
        base = self.data_url if use_data_api else self.base_url
        url = f"{base}{endpoint}"
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json"
        }
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            log(f"Alpaca API error: {e.code} - {error_body}", "ERROR")
            raise

    def get_account(self) -> dict:
        return self._request("GET", "/v2/account")

    def get_positions(self) -> list:
        return self._request("GET", "/v2/positions")

    def get_last_price(self, symbol: str) -> float:
        try:
            data = self._request("GET", f"/v2/stocks/{symbol}/trades/latest", use_data_api=True)
            return data.get("trade", {}).get("p", 0)
        except:
            return 0

    def submit_order(self, symbol: str, qty: float = None, side: str = "buy",
                     order_type: str = "market", notional: float = None) -> dict:
        order = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "time_in_force": "day"
        }
        if notional:
            order["notional"] = round(notional, 2)
        else:
            order["qty"] = str(qty)
        log(f"Submitting order: {side} {symbol} - qty={qty}, notional={notional}")
        return self._request("POST", "/v2/orders", order)

    def get_orders(self, status: str = "open") -> list:
        return self._request("GET", f"/v2/orders?status={status}")

    def cancel_all_orders(self):
        return self._request("DELETE", "/v2/orders")

    def is_market_open(self) -> bool:
        try:
            clock = self._request("GET", "/v2/clock")
            return clock.get("is_open", False)
        except:
            return False


# =============================================================================
# MARKET DATA
# =============================================================================

def fetch_yahoo_history(symbol: str, days: int = 10, interval: str = "1h") -> list:
    """Fetch price history with retry logic. Supports intervals: 1m, 5m, 15m, 1h, 1d."""
    import time as _time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            end = int(datetime.now().timestamp())
            start = int((datetime.now() - timedelta(days=days)).timestamp())
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={start}&period2={end}&interval={interval}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15, context=ssl_context) as response:
                data = json.loads(response.read().decode())
            result = data['chart']['result'][0]
            timestamps = result['timestamp']
            quotes = result['indicators']['quote'][0]
            history = []
            for i, ts in enumerate(timestamps):
                if quotes['close'][i]:
                    entry = {
                        'date': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M'),
                        'close': quotes['close'][i]
                    }
                    if quotes.get('high') and quotes['high'][i]:
                        entry['high'] = quotes['high'][i]
                    if quotes.get('low') and quotes['low'][i]:
                        entry['low'] = quotes['low'][i]
                    if quotes.get('volume') and quotes['volume'][i]:
                        entry['volume'] = quotes['volume'][i]
                    history.append(entry)
            if history:
                return history
            # Empty history — retry
            if attempt < max_retries - 1:
                log(f"Empty data for {symbol}, retrying ({attempt + 1}/{max_retries})...", "WARNING")
                _time.sleep(2 ** attempt)
        except Exception as e:
            if attempt < max_retries - 1:
                log(f"Fetch failed for {symbol} (attempt {attempt + 1}): {e}, retrying...", "WARNING")
                _time.sleep(2 ** attempt)
            else:
                log(f"All {max_retries} attempts failed for {symbol} ({interval}): {e}", "WARNING")
    return []

_yahoo_session = {"opener": None, "crumb": None}

def _get_yahoo_session():
    """Yahoo's quoteSummary (fundamentals) endpoint requires a session cookie + crumb,
    unlike the chart endpoint used for price history. Session is reused for the process."""
    if _yahoo_session["opener"] is not None:
        return _yahoo_session["opener"], _yahoo_session["crumb"]
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj),
                                          urllib.request.HTTPSHandler(context=ssl_context))
    opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
    try:
        opener.open("https://fc.yahoo.com", timeout=15).read()
    except Exception:
        pass
    try:
        crumb = opener.open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15).read().decode()
    except Exception as e:
        log(f"Could not get Yahoo fundamentals crumb: {e}", "WARNING")
        crumb = None
    _yahoo_session["opener"] = opener
    _yahoo_session["crumb"] = crumb
    return opener, crumb

def fetch_fundamentals(ticker: str) -> dict:
    """Pull basic fundamentals (analyst target, growth, margins) for long-term stock scoring.
    Returns {} on failure — callers should treat that as neutral, not fatal."""
    opener, crumb = _get_yahoo_session()
    if not crumb:
        return {}
    modules = "financialData,defaultKeyStatistics"
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
           f"?modules={modules}&crumb={urllib.parse.quote(crumb)}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with opener.open(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        result = data["quoteSummary"]["result"][0]
        fd = result.get("financialData", {})
        ks = result.get("defaultKeyStatistics", {})

        def raw(d, key):
            v = d.get(key)
            return v.get("raw") if isinstance(v, dict) else v

        return {
            "current_price": raw(fd, "currentPrice"),
            "target_mean_price": raw(fd, "targetMeanPrice"),
            "recommendation_mean": raw(fd, "recommendationMean"),  # 1=strong buy .. 5=strong sell
            "revenue_growth": raw(fd, "revenueGrowth"),
            "earnings_growth": raw(fd, "earningsGrowth"),
            "profit_margins": raw(fd, "profitMargins"),
            "beta": raw(ks, "beta"),
        }
    except Exception as e:
        log(f"Fundamentals fetch failed for {ticker}: {e}", "WARNING")
        return {}

def fetch_insider_sentiment(ticker: str) -> dict:
    """Net insider buy/sell activity from recent SEC filings (via Yahoo). Only counts
    open-market Purchase/Sale transactions — stock grants/awards/option exercises are
    compensation, not a discretionary vote of confidence, so they're excluded.
    A genuinely independent source from analyst estimates and price action: this reflects
    what people inside the company are actually doing with their own money."""
    opener, crumb = _get_yahoo_session()
    if not crumb:
        return {}
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
           f"?modules=insiderTransactions&crumb={urllib.parse.quote(crumb)}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with opener.open(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        txns = data["quoteSummary"]["result"][0].get("insiderTransactions", {}).get("transactions", [])
    except Exception as e:
        log(f"Insider transactions fetch failed for {ticker}: {e}", "WARNING")
        return {}

    buy_shares = sell_shares = 0
    for t in txns:
        text = t.get("transactionText", "").lower()
        shares = (t.get("shares") or {}).get("raw", 0) or 0
        if "purchase" in text:
            buy_shares += shares
        elif "sale" in text:
            sell_shares += shares
    return {"buy_shares": buy_shares, "sell_shares": sell_shares, "net_shares": buy_shares - sell_shares}

def check_price_trend(ticker: str) -> dict:
    """Is the stock in a confirmed long-term uptrend (price above its 200-day average)?
    Pulled from raw price history, independent of Yahoo's fundamentals/analyst data
    entirely — a technical corroboration rather than another opinion-based source."""
    hist = fetch_yahoo_history(ticker, 380, "1d")  # ~380 calendar days to reliably get 200+ trading days
    if not hist or len(hist) < 200:
        return {"available": False, "uptrend": False}
    sma200 = sum(h["close"] for h in hist[-200:]) / 200
    price = hist[-1]["close"]
    return {"available": True, "uptrend": price > sma200, "price": price, "sma200": sma200}

def passes_rigorous_screen(brain: dict, ticker: str) -> dict:
    """A candidate must independently pass three unrelated data sources — fundamentals,
    price trend, and insider activity — not just rank well on one composite score.
    Any single source can veto; this is deliberately a high, narrow bar so the bot only
    holds names with corroborating evidence across data it can't game against itself."""
    fund = get_cached_fundamentals(brain, ticker)
    score = calculate_fundamental_score(fund)
    price, target = fund.get("current_price"), fund.get("target_mean_price")
    upside = (target - price) / price if price and target and price > 0 else None
    rec = fund.get("recommendation_mean")
    rev_g = fund.get("revenue_growth")

    fundamentals_pass = bool(
        fund and score > 1.0
        and upside is not None and upside > 0.15
        and rec is not None and rec <= 2.5
        and rev_g is not None and rev_g > 0
    )

    trend = check_price_trend(ticker)
    trend_pass = trend.get("uptrend", False)

    insider = fetch_insider_sentiment(ticker)
    net_shares = insider.get("net_shares", 0)
    # No data at all shouldn't disqualify a small/thinly-covered name; only fail on
    # actual net selling (buys don't outweigh sells, and there was real selling).
    insider_pass = not (net_shares < 0 and insider.get("sell_shares", 0) > 0)

    return {
        "ticker": ticker,
        "score": score,
        "fundamentals_pass": fundamentals_pass,
        "trend_pass": trend_pass,
        "insider_pass": insider_pass,
        "qualifies": fundamentals_pass and trend_pass and insider_pass,
    }

def calculate_fundamental_score(fund: dict) -> float:
    """Composite long-term-upside score from analyst target, growth, and profitability.
    Positive = bullish long-term outlook. This is a simple heuristic, not a valuation
    model — it's meant to rank candidates, not screen the whole market.

    Growth/upside ratios are clipped before weighting. Small-cap growth % is routinely
    off a tiny base (e.g. revenue $1M -> $27M reads as +2600%) — left uncapped, one
    such artifact swamps every other input and the score stops reflecting quality."""
    if not fund:
        return 0.0

    def clip(v, lo, hi):
        return max(lo, min(hi, v))

    score = 0.0
    price, target = fund.get("current_price"), fund.get("target_mean_price")
    if price and target and price > 0:
        upside = clip((target - price) / price, -1.0, 2.0)
        score += upside
    rec = fund.get("recommendation_mean")             # 1=strong buy .. 5=strong sell
    if rec is not None:
        score += (3.0 - rec) / 2.0 * 0.3              # scaled to +/-0.3
    rev_g = fund.get("revenue_growth")
    if rev_g is not None:
        score += clip(rev_g, -1.0, 1.0) * 0.5
    earn_g = fund.get("earnings_growth")
    if earn_g is not None:
        score += clip(earn_g, -1.0, 1.0) * 0.5
    margins = fund.get("profit_margins")
    if margins is not None:
        score += clip(margins, -1.0, 1.0) * 0.3
    return score

def get_cached_fundamentals(brain: dict, ticker: str, max_age_days: int = 7) -> dict:
    """Fundamentals change slowly — cache in brain.json so we don't hit Yahoo's
    crumb-gated endpoint on every 15-minute cron cycle."""
    cache = brain.setdefault("fundamentals_cache", {})
    entry = cache.get(ticker)
    if entry:
        age_days = (datetime.now() - datetime.fromisoformat(entry["fetched_at"])).days
        if age_days < max_age_days:
            return entry["data"]
    data = fetch_fundamentals(ticker)
    if data:
        cache[ticker] = {"data": data, "fetched_at": datetime.now().isoformat()}
        return data
    return entry["data"] if entry else {}

def fetch_screener_candidates(screen_ids: list, count_per_screen: int = 25, min_market_cap: float = 300_000_000) -> list:
    """Pull candidate tickers from Yahoo's predefined screeners (e.g. 'aggressive_small_caps').
    Applies a minimum market cap floor to filter out pre-revenue/illiquid micro-caps that
    'aggressive growth' shouldn't be conflated with (binary-outcome biotechs, penny miners, etc)."""
    opener, crumb = _get_yahoo_session()
    if not crumb:
        return []
    tickers = []
    for scr_id in screen_ids:
        url = (f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
               f"?scrIds={scr_id}&count={count_per_screen}&crumb={urllib.parse.quote(crumb)}")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            data = json.loads(opener.open(req, timeout=15).read().decode())
            quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
            for q in quotes:
                symbol = q.get("symbol")
                mkt_cap = q.get("marketCap", 0) or 0
                if symbol and mkt_cap >= min_market_cap:
                    tickers.append(symbol)
        except Exception as e:
            log(f"Screener fetch failed for {scr_id}: {e}", "WARNING")
    return list(dict.fromkeys(tickers))  # dedupe, preserve order

def discover_stock_universe(brain: dict, held_tickers: set = None, max_holdings: int = 6, refresh_days: int = 30) -> dict:
    """Screen aggressive small/mid-cap growth stocks and admit only names that pass a
    rigorous, multi-source test — NOT a top-N ranking. Qualification is a bar, not a
    quota: on any given scan, 0 to max_holdings names may qualify. Fewer qualifiers
    means more of the portfolio stays in cash, by design (see calculate_target_allocation).

    Rescanning is gated to every `refresh_days` — screening + scoring dozens of candidates
    across three data sources is slow and none of them change meaningfully day to day.
    Currently-held names are always kept in the returned universe (even if they no longer
    qualify) so check_fundamentals_exits can keep tracking them for a deliberate,
    deterioration-based exit instead of orphaning them.
    """
    disc = brain.setdefault("discovered_universe", {})
    last_scan = brain.get("universe_last_scanned")
    if last_scan:
        age_days = (datetime.now() - datetime.fromisoformat(last_scan)).days
        if age_days < refresh_days:
            return disc

    log("Scanning aggressive small/mid-cap growth screens for candidates...")
    candidates = fetch_screener_candidates(["aggressive_small_caps", "small_cap_gainers"], count_per_screen=25)

    # Cheap fundamentals-only pre-filter first, so the expensive multi-source screen
    # (adds a full price-history fetch + insider-filing fetch per name) only runs on
    # candidates that already show basic promise, not every screener result.
    prefiltered = []
    for ticker in candidates:
        fund = get_cached_fundamentals(brain, ticker)
        if fund and calculate_fundamental_score(fund) > 0.3 and (fund.get("revenue_growth") or 0) > 0:
            prefiltered.append(ticker)

    qualified = {}
    results_log = []
    for ticker in prefiltered:
        result = passes_rigorous_screen(brain, ticker)
        results_log.append(result)
        if result["qualifies"]:
            qualified[ticker] = result["score"]
        if len(qualified) >= max_holdings:
            break

    # Keep names actually held AND previously targeted by this strategy in the running
    # even if they no longer qualify, so check_fundamentals_exits (not this scan)
    # decides whether to exit them. Must be the intersection of both:
    #  - "actually held" alone would sweep in unrelated leftover positions (e.g. dust
    #    from a since-abandoned strategy) that should instead fall through to the
    #    legacy-position liquidation in run_daily_check, not be adopted as if this
    #    system chose them.
    #  - "previously targeted" alone would grandfather a name that was targeted but
    #    never actually bought (e.g. market was closed) with no real position to protect.
    previously_targeted = set(disc.keys())
    for t in (held_tickers or set()) & previously_targeted:
        if t not in qualified:
            qualified[t] = calculate_fundamental_score(get_cached_fundamentals(brain, t))

    new_universe = {}
    for ticker, score in qualified.items():
        existing = disc.get(ticker, {})
        new_universe[ticker] = {
            "name": ticker,
            "ticker": ticker,
            "sector": "individual_growth",
            "leverage": 1,
            "trailing_stop_pct": 25.0,  # wide — a backstop, not the primary exit (see check_fundamentals_exits)
            "score_at_discovery": existing.get("score_at_discovery", score),
            "peak_score": max(existing.get("peak_score", score), score),
        }

    brain["discovered_universe"] = new_universe
    brain["universe_last_scanned"] = datetime.now().isoformat()
    passed = [r for r in results_log if r["qualifies"]]
    failed_summary = ", ".join(
        f"{r['ticker']}(fund={'Y' if r['fundamentals_pass'] else 'N'}/"
        f"trend={'Y' if r['trend_pass'] else 'N'}/insider={'Y' if r['insider_pass'] else 'N'})"
        for r in results_log if not r["qualifies"]
    )
    log(f"Rigorous screen: {len(passed)}/{len(results_log)} candidates qualified "
        f"({', '.join(f'{t}({s:+.2f})' for t, s in qualified.items()) if qualified else 'none'})")
    if failed_summary:
        log(f"Screened out: {failed_summary}")
    return new_universe

def check_fundamentals_exits(client, brain: dict, recheck_days: int = 14) -> list:
    """Sell a discovered-growth holding whose fundamental score has deteriorated
    significantly from its peak since being picked — the growth story breaking down,
    not a normal pullback. This is the primary, deliberate exit; the wide trailing
    stop in discover_stock_universe is a separate real-time backstop against a crash
    fundamentals haven't caught up to yet, and still runs every cycle.

    Gated to every `recheck_days` — the underlying fundamentals only refresh weekly
    anyway (see get_cached_fundamentals), so evaluating this every 15-minute cron
    cycle was re-deciding the same exit call for a week straight off unchanged data.
    Selling should be a deliberate, infrequent decision, not a per-cycle one."""
    trades = []
    disc = brain.setdefault("discovered_universe", {})

    last_check = brain.get("last_fundamentals_exit_check")
    if last_check:
        age_days = (datetime.now() - datetime.fromisoformat(last_check)).days
        if age_days < recheck_days:
            return trades
    brain["last_fundamentals_exit_check"] = datetime.now().isoformat()

    try:
        positions = client.get_positions()
    except Exception as e:
        log(f"Could not fetch positions for fundamentals-exit check: {e}", "ERROR")
        return trades

    for pos in positions:
        symbol = pos["symbol"]
        entry = disc.get(symbol)
        if not entry or entry.get("sector") != "individual_growth":
            continue
        fund = get_cached_fundamentals(brain, symbol)
        score = calculate_fundamental_score(fund)
        peak = entry.get("peak_score", entry.get("score_at_discovery", score))
        if score > peak:
            entry["peak_score"] = score
            continue
        deteriorated = score <= 0 or (peak > 0 and score < peak * 0.5)
        if deteriorated:
            log(f"Fundamentals deteriorated for {symbol}: score {score:+.2f} (peak {peak:+.2f}) — exiting", "WARNING")
            try:
                client.submit_order(symbol=symbol, qty=float(pos["qty"]), side="sell")
                trades.append(symbol)
                del disc[symbol]
            except Exception as e:
                log(f"Failed to exit {symbol} on fundamentals deterioration: {e}", "ERROR")
    return trades

# =============================================================================
# FEATURE 4: DOLLAR COST AVERAGING
# =============================================================================

def get_dca_amount(config: dict, brain: dict) -> float:
    """Calculate DCA amount for this period."""
    dca_config = config.get("dca", {})

    if not dca_config.get("enabled", False):
        return 0

    amount = dca_config.get("amount", 0)
    frequency = dca_config.get("frequency", "weekly")

    today = datetime.now()
    last_dca = brain.get("last_dca_date", "")

    if last_dca:
        last_date = datetime.fromisoformat(last_dca)
        days_since = (today - last_date).days

        if frequency == "weekly" and days_since < 7:
            return 0
        elif frequency == "monthly" and days_since < 28:
            return 0
        elif frequency == "daily" and days_since < 1:
            return 0

    return amount


# =============================================================================
# FEATURE 5: TRAILING STOP LOSS
# =============================================================================

def check_trailing_stops(client: AlpacaClient, brain: dict, config: dict) -> list:
    """Check and execute trailing stop losses with per-asset stop percentages."""
    trades = []
    default_trailing_pct = config.get("risk_management", {}).get("trailing_stop_percent", 8) / 100

    positions = client.get_positions()
    trailing_stops = brain.get("trailing_stops", {})
    universe = {**ASSETS, **brain.get("discovered_universe", {})}

    for pos in positions:
        symbol = pos["symbol"]
        current_price = float(pos["current_price"])
        qty = float(pos["qty"])

        # Look up per-asset trailing stop percentage
        asset_stop_pct = default_trailing_pct
        is_inverse = False
        for asset_id, asset_info in universe.items():
            if asset_info["ticker"] == symbol:
                asset_stop_pct = asset_info.get("trailing_stop_pct", 8.0) / 100
                is_inverse = asset_info.get("leverage", 1) < 0
                break

        # Apply learned stop loss adjustment (in percentage points)
        if "learning" in brain:
            learned_adj = brain["learning"].get("learned_stop_adjustments", {}).get(symbol, 0.0)
            asset_stop_pct += learned_adj / 100.0

        # Inverse ETFs don't use trailing stops — they exit on regime change only
        if is_inverse:
            continue

        # Update high water mark
        if symbol not in trailing_stops:
            trailing_stops[symbol] = {"high": current_price}
        elif current_price > trailing_stops[symbol]["high"]:
            trailing_stops[symbol]["high"] = current_price

        high = trailing_stops[symbol]["high"]
        stop_price = high * (1 - asset_stop_pct)

        # Check if stop triggered
        if current_price <= stop_price:
            log(f"Trailing stop triggered for {symbol}: ${current_price:.2f} <= ${stop_price:.2f} "
                f"(stop: {asset_stop_pct*100:.0f}%)", "WARNING")

            # Record stop event for learning
            if "learning" in brain:
                record_stop_loss_event(brain, symbol, stop_price, asset_stop_pct * 100)

            try:
                client.submit_order(symbol=symbol, qty=qty, side="sell")
                trades.append({
                    "asset": symbol,
                    "ticker": symbol,
                    "action": "TRAILING_STOP_SELL",
                    "shares": qty,
                    "price": current_price,
                    "stop_pct": asset_stop_pct * 100,
                    "timestamp": datetime.now().isoformat()
                })
                del trailing_stops[symbol]
                # Record cooldown: prevent re-buying for 15 days
                brain.setdefault("stop_cooldowns", {})[symbol] = datetime.now().isoformat()
            except Exception as e:
                log(f"Failed to execute trailing stop for {symbol}: {e}", "ERROR")

    brain["trailing_stops"] = trailing_stops
    return trades


# =============================================================================
# FEATURE 6: SECTOR LIMITS
# =============================================================================

def apply_sector_limits(allocation: dict, universe: dict = None) -> dict:
    """Ensure no sector exceeds its limit. Trimmed excess is left un-invested (cash),
    not redistributed to other positions — redistributing would silently erase the
    caller's intended cash reserve whenever a cap actually triggers.

    `universe` should be ASSETS merged with brain["discovered_universe"] — dynamically
    discovered tickers aren't in the static ASSETS dict, so callers dealing with the
    live discovered-stock universe must pass the merged view explicitly."""
    universe = universe if universe is not None else ASSETS
    # Calculate sector totals
    sector_totals = defaultdict(float)
    for asset_id, weight in allocation.items():
        sector = universe.get(asset_id, {}).get("sector", "other")
        sector_totals[sector] += weight

    # Check and adjust
    adjusted = allocation.copy()
    for sector, total in sector_totals.items():
        limit = SECTOR_LIMITS.get(sector, 1.0)
        if total > limit + 1e-9:
            # Scale down assets in this sector
            scale = limit / total
            for asset_id in allocation:
                if universe.get(asset_id, {}).get("sector") == sector:
                    adjusted[asset_id] *= scale
            log(f"Sector {sector} exceeded limit ({total*100:.1f}% > {limit*100:.1f}%), scaled down", "INFO")

    return adjusted


# =============================================================================
# FEATURE 7: CORRELATION MONITORING
# =============================================================================

def check_correlation_risk(allocation: dict) -> dict:
    """Check if portfolio is too correlated (concentrated risk)."""
    # Calculate weighted average correlation
    total_correlation = 0
    pair_count = 0
    high_correlation_pairs = []

    assets = [a for a, w in allocation.items() if w > 0.05]  # Only significant holdings

    for i, a1 in enumerate(assets):
        for a2 in assets[i+1:]:
            # Look up correlation
            key = (a1, a2) if (a1, a2) in CORRELATIONS else (a2, a1)
            corr = CORRELATIONS.get(key, 0.3)  # Default moderate correlation

            weight = allocation[a1] * allocation[a2]
            total_correlation += corr * weight
            pair_count += 1

            if corr > 0.6:
                high_correlation_pairs.append((a1, a2, corr))

    avg_correlation = total_correlation / pair_count if pair_count > 0 else 0

    result = {
        "average_correlation": avg_correlation,
        "high_correlation_pairs": high_correlation_pairs,
        "risk_level": "low"
    }

    if avg_correlation > 0.5:
        result["risk_level"] = "high"
        log(f"High portfolio correlation: {avg_correlation:.2f}", "WARNING")
    elif avg_correlation > 0.3:
        result["risk_level"] = "medium"

    return result


# =============================================================================
# FEATURE 15: PERFORMANCE VS S&P 500
# =============================================================================

def track_benchmark_performance(brain: dict, portfolio_value: float) -> dict:
    """Track portfolio performance vs S&P 500."""
    spy_history = fetch_yahoo_history("SPY", 30, "1d")

    if not spy_history:
        return {"error": "Could not fetch SPY data"}

    current_spy = spy_history[-1]["close"]

    # Get portfolio snapshots
    portfolio = load_portfolio()
    snapshots = portfolio.get("snapshots", [])

    benchmark = brain.get("spy_benchmark", {})

    if not snapshots and not benchmark.get("start_date"):
        # Initialize benchmark tracking for the first time
        brain["spy_benchmark"] = {
            "start_date": datetime.now().isoformat(),
            "start_spy_price": current_spy,
            "start_portfolio_value": portfolio_value
        }
        return {"message": "Benchmark tracking started"}
    if not benchmark:
        benchmark = {
            "start_date": snapshots[0]["date"],
            "start_spy_price": current_spy,
            "start_portfolio_value": snapshots[0]["value"]
        }
        brain["spy_benchmark"] = benchmark

    start_spy = benchmark.get("start_spy_price", current_spy)
    start_portfolio = benchmark.get("start_portfolio_value", portfolio_value)

    spy_return = ((current_spy - start_spy) / start_spy) * 100
    portfolio_return = ((portfolio_value - start_portfolio) / start_portfolio) * 100

    alpha = portfolio_return - spy_return

    result = {
        "portfolio_return": portfolio_return,
        "spy_return": spy_return,
        "alpha": alpha,
        "beating_market": alpha > 0,
        "start_date": benchmark.get("start_date", ""),
        "start_value": start_portfolio,
        "start_spy": start_spy,
        "current_spy": current_spy
    }

    # Log performance
    if alpha > 0:
        log(f"Portfolio beating S&P 500 by {alpha:.2f}%", "INFO")
    else:
        log(f"Portfolio trailing S&P 500 by {abs(alpha):.2f}%", "INFO")

    return result


# =============================================================================
# SELF-LEARNING: STOP LOSS CALIBRATION
# =============================================================================

def record_stop_loss_event(brain: dict, ticker: str, stop_price: float, stop_pct: float):
    """Record when a trailing stop fires, for later calibration."""
    learning = brain["learning"]
    learning["stop_loss_events"].append({
        "ticker": ticker,
        "stop_price": stop_price,
        "stop_pct": stop_pct,
        "date": datetime.now().isoformat()[:10],
        "price_after_15d": None,
        "checked": False,
    })
    # 90-day rolling window
    cutoff = (datetime.now() - timedelta(days=60)).isoformat()[:10]
    learning["stop_loss_events"] = [
        e for e in learning["stop_loss_events"]
        if e.get("date", "") >= cutoff
    ]


def learn_stop_loss_calibration(brain: dict):
    """Check if stopped-out assets recovered. Adjust stop percentages."""
    learning = brain["learning"]
    today = datetime.now()

    for event in learning["stop_loss_events"]:
        if event.get("checked"):
            continue
        event_date = event.get("date", "")
        try:
            days_since = (today - datetime.fromisoformat(event_date)).days
        except Exception:
            continue
        if days_since < 15:
            continue

        ticker = event["ticker"]
        try:
            history = fetch_yahoo_history(ticker, 20, "1d")
        except Exception:
            continue
        if not history:
            continue

        # Get max price in the 15 days after the stop
        max_price = max(h["close"] for h in history[-15:]) if len(history) >= 15 else history[-1]["close"]
        event["price_after_15d"] = max_price
        event["checked"] = True
        event["recovered"] = max_price > event["stop_price"]

    # Per-ticker false stop rate
    ticker_events = defaultdict(list)
    for event in learning["stop_loss_events"]:
        if event.get("checked"):
            ticker_events[event["ticker"]].append(event)

    adjustments = learning["learned_stop_adjustments"]
    for ticker, events in ticker_events.items():
        if len(events) < 2:
            continue
        false_stops = sum(1 for e in events if e.get("recovered", False))
        false_rate = false_stops / len(events)

        current_adj = adjustments.get(ticker, 0.0)
        if false_rate > 0.60:
            # Too many false stops — widen by 1%
            new_adj = current_adj + 1.0
        elif false_rate < 0.30:
            # Stops are well-placed or too loose — tighten by 1%
            new_adj = current_adj - 1.0
        else:
            continue
        # Cap at +10% / -5%
        adjustments[ticker] = max(-5.0, min(10.0, new_adj))

    learning["learned_stop_adjustments"] = adjustments


# =============================================================================
# ENHANCED ALLOCATION CALCULATION
# =============================================================================

def calculate_target_allocation(brain: dict, config: dict, held_tickers: set = None) -> dict:
    """
    Long-term buy & hold allocation: only the dynamically discovered small/mid-cap
    growth sleeve (see discover_stock_universe) + a small crypto sleeve. No broad-market
    anchor by design — this bot only holds discovered growth candidates, not an index
    fund. Fixed weights, no regime/RSI rotation. The growth sleeve's membership only
    changes when it's rescanned (every 30 days) or a holding is exited via
    check_fundamentals_exits (primary) or its wide trailing stop (backstop) — not on
    a daily re-ranking basis.
    """
    universe = discover_stock_universe(brain, held_tickers=held_tickers)  # ticker -> {sector: "individual_growth", ...}
    full_universe = {**ASSETS, **universe}

    individual_keys = list(universe.keys())
    crypto_keys = [k for k in ASSETS if ASSETS[k]["sector"] == "crypto"]

    # Fixed per-position size, not a fixed sleeve budget split across however many
    # exist. Unfilled slots stay in cash rather than being redistributed — the bar
    # for qualifying (see discover_stock_universe) directly controls how much capital
    # gets deployed now vs held back for future candidates. At the max of 6 holdings
    # this deploys 60% to stocks; most scans should qualify fewer, leaving more cash.
    per_position_pct = 0.10
    crypto_pct = 0.05

    allocation = {}
    for k in crypto_keys:
        allocation[k] = crypto_pct / len(crypto_keys) if crypto_keys else 0.0

    scores = {k: calculate_fundamental_score(get_cached_fundamentals(brain, k)) for k in individual_keys}
    for k in individual_keys:
        allocation[k] = per_position_pct

    # Ensure all universe keys present
    for k in list(ASSETS.keys()) + individual_keys:
        if k not in allocation:
            allocation[k] = 0.0

    # Apply sector limits (needs the merged universe — discovered tickers aren't in ASSETS)
    allocation = apply_sector_limits(allocation, universe=full_universe)

    invested_total = sum(allocation.values())
    cash_reserve = 1.0 - invested_total
    score_str = ", ".join(f"{k}={scores[k]:+.2f}" for k in individual_keys) if individual_keys else "(no growth holdings — nothing qualified)"
    log(f"Long-term allocation: {len(individual_keys)} stock(s) @ {per_position_pct*100:.0f}% each, "
        f"crypto={crypto_pct*100:.0f}%, cash={cash_reserve*100:.0f}% | scores: {score_str}")

    return allocation


# =============================================================================
# EMAIL NOTIFICATIONS
# =============================================================================

def send_email(config: dict, subject: str, body: str):
    smtp_server = config.get("smtp_server", "smtp.gmail.com")
    smtp_port = config.get("smtp_port", 587)
    sender_email = config.get("email_address")
    sender_password = config.get("email_password")
    recipient = config.get("notification_email", sender_email)

    if not all([sender_email, sender_password]):
        log("Email not configured", "WARNING")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient

    html_body = f"""
    <html>
    <body style="font-family: monospace; max-width: 700px; margin: 0 auto;">
        <h2>🤖 Long-Term Hold Bot v5.0</h2>
        <pre style="background: #f5f5f5; padding: 15px; border-radius: 5px; overflow-x: auto; font-size: 12px;">
{body}
        </pre>
        <p style="color: #7f8c8d; font-size: 11px;">Generated at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    </body>
    </html>
    """

    msg.attach(MIMEText(body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient, msg.as_string())
        log(f"Email sent to {recipient}")
    except Exception as e:
        log(f"Failed to send email: {e}", "ERROR")


# =============================================================================
# ENHANCED WEEKLY REPORT
# =============================================================================

def generate_weekly_report(client: AlpacaClient, brain: dict, config: dict) -> str:
    account = client.get_account()
    positions = client.get_positions()
    portfolio = load_portfolio()

    portfolio_value = float(account["portfolio_value"])
    cash = float(account["cash"])

    # Benchmark comparison
    benchmark = track_benchmark_performance(brain, portfolio_value)
    universe = discover_stock_universe(brain, held_tickers={p["symbol"] for p in positions})

    report = f"""
════════════════════════════════════════════════════════════════════════
                    LONG-TERM HOLD BOT REPORT v5.0
                    {datetime.now().strftime("%B %d, %Y")}
════════════════════════════════════════════════════════════════════════

PORTFOLIO SUMMARY
────────────────────────────────────────────────────────────────────────
  Total Value:     ${portfolio_value:>12,.2f}
  Cash:            ${cash:>12,.2f}

PERFORMANCE VS S&P 500
────────────────────────────────────────────────────────────────────────
  Your Return:     {benchmark.get('portfolio_return', 0):>+12.2f}%
  S&P 500 Return:  {benchmark.get('spy_return', 0):>+12.2f}%
  Alpha:           {benchmark.get('alpha', 0):>+12.2f}%  {'✓ BEATING MARKET' if benchmark.get('beating_market') else ''}

DISCOVERED GROWTH UNIVERSE
────────────────────────────────────────────────────────────────────────
""" + ("\n".join(f"  {t:<8} score={info['peak_score']:+.2f} (discovered at {info['score_at_discovery']:+.2f})"
                  for t, info in universe.items()) or "  (none passed screening)") + f"""

CURRENT HOLDINGS
────────────────────────────────────────────────────────────────────────
"""

    for pos in positions:
        symbol = pos["symbol"]
        qty = float(pos["qty"])
        market_value = float(pos["market_value"])
        unrealized_pl = float(pos["unrealized_plpc"]) * 100
        report += f"  {symbol:<8} {qty:>8.2f} shares  ${market_value:>10,.2f}  {unrealized_pl:>+6.1f}%\n"

    report += f"""
════════════════════════════════════════════════════════════════════════
"""
    return report


# =============================================================================
# SELF-LEARNING: ORCHESTRATOR & DISPLAY
# =============================================================================

def run_learning_cycle(client, brain: dict):
    """Run all learning functions in sequence. Wrapped in try/except for safety."""
    try:
        log("Starting learning cycle...")
        learning = brain["learning"]

        # 1. Track trade outcomes
        track_trade_outcomes(client, brain)

        # 2. Learn stop loss calibration
        learn_stop_loss_calibration(brain)

        learning["total_cycles"] += 1
        learning["last_cycle"] = datetime.now().isoformat()

        log(f"Learning cycle #{learning['total_cycles']} complete. "
            f"Closed trades: {len(learning['closed_trades'])}")

    except Exception as e:
        log(f"Learning cycle error (non-fatal): {e}", "WARNING")


def show_learning_status(brain: dict):
    """Display learning system stats."""
    if "learning" not in brain:
        print("\n SELF-LEARNING SYSTEM: Not initialized")
        return

    learning = brain["learning"]

    total_cycles = learning.get("total_cycles", 0)
    last_cycle = learning.get("last_cycle", "Never")
    closed_trades = len(learning.get("closed_trades", []))
    open_positions = len(learning.get("open_positions", {}))
    stop_events = len(learning.get("stop_loss_events", []))

    print(f"""
 SELF-LEARNING SYSTEM
 ────────────────────────────────────────
 Total Cycles:     {total_cycles:>8}
 Last Cycle:       {str(last_cycle)[:19] if last_cycle else 'Never':>19}
 Open Positions:   {open_positions:>8}
 Closed Trades:    {closed_trades:>8} (90-day window)
 Stop Events:      {stop_events:>8}""")

    # Stop loss adjustments
    stop_adj = learning.get("learned_stop_adjustments", {})
    if stop_adj:
        print(f"""
 LEARNED STOP LOSS ADJUSTMENTS
 ────────────────────────────────────────""")
        for ticker, adj in sorted(stop_adj.items()):
            direction = "wider" if adj > 0 else "tighter"
            print(f"   {ticker:<8} {adj:>+5.1f}%  ({direction})")


# =============================================================================
# ENHANCED DAILY CHECK
# =============================================================================

def run_daily_check(config: dict):
    """Long-term hold check: rescans the discovered growth universe, checks
    fundamentals-deterioration and trailing-stop exits, and rebalances toward target."""
    portfolio = load_portfolio()
    last_check = portfolio.get("last_daily_check", "")
    now = datetime.now()

    # Allow multiple runs per day -- 30 min cooldown
    if last_check:
        try:
            last_time = datetime.fromisoformat(last_check)
            minutes_since = (now - last_time).total_seconds() / 60
            if minutes_since < 60:
                log(f"Ran {minutes_since:.0f} min ago. Minimum interval: 60 min. Skipping.")
                return
        except:
            pass

    log("Starting daily check (v5.0)...")

    portfolio["last_daily_check"] = now.isoformat()
    save_portfolio(portfolio)

    api_key = config.get("alpaca_api_key")
    api_secret = config.get("alpaca_api_secret")
    paper = config.get("paper_trading", True)

    if not api_key or not api_secret:
        log("Alpaca credentials not configured", "ERROR")
        return

    client = AlpacaClient(api_key, api_secret, paper)
    brain = load_brain()

    # Get account info
    account = client.get_account()
    portfolio_value = float(account["portfolio_value"])
    positions = client.get_positions()

    # FEATURE 15: Track benchmark
    benchmark = track_benchmark_performance(brain, portfolio_value)
    log(f"Portfolio vs SPY: {benchmark.get('alpha', 0):+.2f}% alpha")

    # Risk management
    risk = config.get("risk_management", {})
    if risk.get("enabled", False):
        initial_value = portfolio.get("initial_value", portfolio_value)
        max_loss_pct = risk.get("max_loss_percent", 30) / 100
        floor_value = initial_value * (1 - max_loss_pct)

        if portfolio_value <= floor_value:
            log(f"🚨 FLOOR BREACHED! ${portfolio_value:,.2f} <= ${floor_value:,.2f}", "CRITICAL")
            # Emergency sell (same as before)
            for pos in positions:
                try:
                    client.submit_order(symbol=pos["symbol"], qty=float(pos["qty"]), side="sell")
                except:
                    pass
            send_email(config, "🚨 EMERGENCY: Floor Breached", f"Portfolio dropped to ${portfolio_value:,.2f}")
            return

        drawdown = ((initial_value - portfolio_value) / initial_value) * 100
        log(f"Risk: Value ${portfolio_value:,.2f} | Floor ${floor_value:,.2f} | Drawdown {drawdown:.1f}%")

    # Discovered growth universe — used below for legacy-liquidation, current-allocation,
    # and ticker lookups. calculate_target_allocation() also calls this; the 30-day
    # rescan gate makes the second call a no-op cache read, not a duplicate scan.
    # held_tickers = actual brokerage positions, so a name only targeted but never
    # bought (e.g. market was closed) doesn't get grandfathered past the rigorous screen.
    held_tickers = {p["symbol"] for p in positions}
    universe = discover_stock_universe(brain, held_tickers=held_tickers)
    full_universe = {**ASSETS, **universe}

    # Liquidate positions in assets no longer in our universe (market hours only)
    market_open = client.is_market_open()
    current_tickers = {info["ticker"] for info in full_universe.values()}
    liquidated = False
    if market_open:
        for pos in positions:
            if pos["symbol"] not in current_tickers:
                log(f"Liquidating legacy position: {pos['symbol']}")
                try:
                    client.submit_order(symbol=pos["symbol"], qty=float(pos["qty"]), side="sell")
                    liquidated = True
                except Exception as e:
                    log(f"Failed to liquidate {pos['symbol']}: {e}", "ERROR")
        if liquidated:
            positions = client.get_positions()  # Refresh after liquidation

        # Fundamentals deterioration is the primary exit for growth holdings; the
        # trailing stop is only a backstop against a crash fundamentals haven't caught up to.
        fundamentals_exits = check_fundamentals_exits(client, brain)
        stopped_out = check_trailing_stops(client, brain, config)
        if fundamentals_exits or stopped_out:
            positions = client.get_positions()  # Refresh after exits/stop-loss sells
            account = client.get_account()
            portfolio_value = float(account["portfolio_value"])

    # FEATURE 7: Correlation check
    current_allocation = {}
    for pos in positions:
        for asset_id, asset_info in full_universe.items():
            if asset_info["ticker"] == pos["symbol"]:
                current_allocation[asset_id] = float(pos["market_value"]) / portfolio_value if portfolio_value > 0 else 0

    correlation = check_correlation_risk(current_allocation)
    if correlation["risk_level"] == "high":
        log(f"High correlation warning: {correlation['average_correlation']:.2f}")

    # Calculate target allocation
    target = calculate_target_allocation(brain, config, held_tickers=held_tickers)

    # DCA: check if a scheduled deposit is due
    dca_amount = get_dca_amount(config, brain)
    if dca_amount > 0:
        log(f"DCA deposit due: ${dca_amount:,.2f} — adding to effective portfolio value")
        portfolio_value += dca_amount
        brain["last_dca_date"] = datetime.now().isoformat()
        brain.setdefault("total_dca_deposited", 0)
        brain["total_dca_deposited"] += dca_amount

    # Check if rebalance needed
    max_drift = 0
    for asset_id, target_weight in target.items():
        current_weight = current_allocation.get(asset_id, 0)
        drift = abs(target_weight - current_weight)
        max_drift = max(max_drift, drift)

    # SMART REBALANCING
    # - Rebalance every 2+ hours (avoid churning)
    # - 10% drift threshold (wider to reduce trades)

    last_rebalance = brain.get("last_rebalance_date", "")
    hours_since_rebalance = 999
    if last_rebalance:
        try:
            last_date = datetime.fromisoformat(last_rebalance)
            hours_since_rebalance = (datetime.now() - last_date).total_seconds() / 3600
        except:
            pass

    daily_due = hours_since_rebalance >= 2  # Rebalance every 2 hours
    drift_triggered = max_drift > 0.10

    should_rebalance = daily_due or drift_triggered

    if drift_triggered:
        log(f"Drift rebalance triggered ({max_drift*100:.1f}% > 10% threshold)")
    elif daily_due:
        log(f"Scheduled rebalance ({hours_since_rebalance:.1f}h since last)")
    else:
        log(f"No rebalance needed (drift: {max_drift*100:.1f}%, hours: {hours_since_rebalance:.1f})")

    if should_rebalance:
        if not market_open:
            log(f"Market closed — skipping rebalance (will retry next open window)")
        else:
            log(f"Executing rebalance (drift: {max_drift*100:.1f}%)")

            # Build trade list
            min_trade = max(0.50, portfolio_value * 0.001)
            sells, buys = [], []
            for asset_id, target_weight in target.items():
                ticker = full_universe[asset_id]["ticker"]
                target_value = portfolio_value * target_weight
                current = next((p for p in positions if p["symbol"] == ticker), None)
                current_value = float(current["market_value"]) if current else 0
                diff = target_value - current_value
                if abs(diff) < min_trade:
                    continue
                if diff < 0:
                    sells.append((ticker, diff, current))
                else:
                    buys.append((ticker, diff))

            # Sells first to free up cash, then buys
            for ticker, diff, current in sells:
                try:
                    price = client.get_last_price(ticker)
                    if price > 0 and current:
                        shares = min(abs(diff) / price, float(current["qty"]))
                        if shares > 0.001:
                            client.submit_order(symbol=ticker, qty=shares, side="sell")
                            log(f"SELL {shares:.4f} shares of {ticker}")
                except Exception as e:
                    log(f"Trade failed for {ticker}: {e}", "ERROR")

            if buys:
                try:
                    available = float(client.get_account().get("buying_power", 0))
                except Exception as e:
                    log(f"Could not fetch buying power, skipping buys: {e}", "ERROR")
                    available = 0

                for ticker, diff in buys:
                    notional = round(diff, 2)
                    if notional < 1.00:
                        log(f"Skipping buy of {ticker} (${notional:.2f} below $1 order minimum)")
                        continue
                    if notional > available:
                        log(f"Skipping buy of {ticker} (${notional:.2f} exceeds available buying power ${available:.2f})")
                        continue
                    try:
                        client.submit_order(symbol=ticker, notional=notional, side="buy")
                        log(f"BUY ${notional:.2f} of {ticker}")
                        available -= notional
                    except Exception as e:
                        log(f"Trade failed for {ticker}: {e}", "ERROR")

            brain["total_trades"] += 1
            brain["last_rebalance_date"] = datetime.now().isoformat()
            log(f"Rebalance complete. Next check in ~2 hours or on 10% drift.")

    # Run learning cycle before saving
    run_learning_cycle(client, brain)

    # Save state
    save_brain(brain)
    save_portfolio(portfolio)
    log(f"Daily check complete. Portfolio: ${portfolio_value:,.2f}")


def run_weekly_report(config: dict):
    log("Generating weekly report (v5.0)...")

    api_key = config.get("alpaca_api_key")
    api_secret = config.get("alpaca_api_secret")
    paper = config.get("paper_trading", True)

    if not api_key or not api_secret:
        log("Alpaca credentials not configured", "ERROR")
        return

    client = AlpacaClient(api_key, api_secret, paper)
    brain = load_brain()

    report = generate_weekly_report(client, brain, config)
    send_email(config, "📊 Long-Term Hold Bot Report v5.0", report)

    save_brain(brain)
    log("Weekly report sent")


def show_status():
    config = load_config()
    if not config.get("alpaca_api_key"):
        print("\n Bot not configured. Run setup first.")
        return

    client = AlpacaClient(
        config["alpaca_api_key"],
        config["alpaca_api_secret"],
        config.get("paper_trading", True)
    )

    account = client.get_account()
    positions = client.get_positions()
    brain = load_brain()
    portfolio = load_portfolio()

    portfolio_value = float(account['portfolio_value'])

    # Benchmark
    benchmark = track_benchmark_performance(brain, portfolio_value)

    # Days running
    start_date = benchmark.get('start_date', '')
    if start_date:
        try:
            days_running = (datetime.now() - datetime.fromisoformat(start_date)).days
        except:
            days_running = 0
    else:
        days_running = 0
    start_spy = benchmark.get('start_spy', 0)
    universe = discover_stock_universe(brain, held_tickers={p["symbol"] for p in positions})

    print(f"""
════════════════════════════════════════════════════════════════
 🤖 LONG-TERM HOLD BOT v5.0 STATUS
════════════════════════════════════════════════════════════════

 ACCOUNT
 ────────────────────────────────────────
 Portfolio Value:  ${portfolio_value:>12,.2f}
 Cash:             ${float(account['cash']):>12,.2f}

 PERFORMANCE VS S&P 500
 ────────────────────────────────────────
 Bot Running:      {days_running} days (since {start_date[:10] if start_date else 'N/A'})
 SPY on Start Day: ${start_spy:>10,.2f}
 Your Return:      {benchmark.get('portfolio_return', 0):>+12.2f}%
 S&P 500:          {benchmark.get('spy_return', 0):>+12.2f}%
 Alpha:            {benchmark.get('alpha', 0):>+12.2f}%

 DISCOVERED GROWTH UNIVERSE
 ────────────────────────────────────────""")
    if universe:
        for t, info in universe.items():
            print(f" {t:<8} score={info['peak_score']:+.2f} (discovered at {info['score_at_discovery']:+.2f})")
    else:
        print(" (none passed screening)")

    print(f"""
 HOLDINGS
 ────────────────────────────────────────""")

    for pos in positions:
        symbol = pos["symbol"]
        value = float(pos["market_value"])
        pl = float(pos["unrealized_plpc"]) * 100
        print(f" {symbol:<8} ${value:>10,.2f}  {pl:>+6.1f}%")

    print(f"""
════════════════════════════════════════════════════════════════
""")


def show_benchmark():
    """Show detailed performance vs S&P 500."""
    config = load_config()
    if not config.get("alpaca_api_key"):
        print("\n Bot not configured. Run setup first.")
        return

    client = AlpacaClient(
        config["alpaca_api_key"],
        config["alpaca_api_secret"],
        config.get("paper_trading", True)
    )

    account = client.get_account()
    brain = load_brain()
    portfolio_value = float(account['portfolio_value'])

    benchmark = track_benchmark_performance(brain, portfolio_value)
    save_brain(brain)

    # Calculate days tracking
    start_date = benchmark.get('start_date', '')
    if start_date:
        try:
            days = (datetime.now() - datetime.fromisoformat(start_date)).days
        except:
            days = 0
    else:
        days = 0

    # Get current SPY price
    spy_data = fetch_yahoo_history("SPY", 2, "1h")
    current_spy = spy_data[-1]['close'] if spy_data else 0

    your_return = benchmark.get('portfolio_return', 0)
    spy_return = benchmark.get('spy_return', 0)
    alpha = benchmark.get('alpha', 0)
    beating = benchmark.get('beating_market', False)
    start_value = benchmark.get('start_value', 100)
    start_spy = benchmark.get('start_spy', current_spy)

    # What your starting amount would be worth if invested in SPY
    spy_equivalent = start_value * (1 + spy_return / 100)
    spy_gain = spy_equivalent - start_value

    print(f"""
════════════════════════════════════════════════════════════════
 📊 PERFORMANCE VS S&P 500
════════════════════════════════════════════════════════════════

 TRACKING PERIOD
 ────────────────────────────────────────
 Start Date:       {start_date[:10] if start_date else 'N/A'}
 Days Tracking:    {days}

 YOUR PORTFOLIO
 ────────────────────────────────────────
 Initial Value:    ${start_value:>12,.2f}
 Current Value:    ${portfolio_value:>12,.2f}
 Gain/Loss:        ${portfolio_value - start_value:>+12,.2f}  ({your_return:>+.2f}%)

 IF YOU BOUGHT SPY INSTEAD
 ────────────────────────────────────────
 SPY Start Price:  ${start_spy:>12,.2f}
 SPY Now:          ${current_spy:>12,.2f}
 ${start_value:,.2f} in SPY:    ${spy_equivalent:>12,.2f}
 Gain/Loss:        ${spy_gain:>+12,.2f}  ({spy_return:>+.2f}%)

 BOTTOM LINE
 ────────────────────────────────────────
 Alpha:            {alpha:>+.2f}%
 Status:           {"✅ BEATING THE MARKET" if beating else "📉 Trailing the market"}

════════════════════════════════════════════════════════════════
""")

    # Interpretation
    if alpha > 2:
        print(" 💡 You are significantly outperforming the market!")
    elif alpha > 0:
        print(" 💡 You are beating the market - great job!")
    elif alpha > -2:
        print(" 💡 You are close to market performance - diversification at work.")
    else:
        print(" 💡 Trailing the market - this can happen with bonds/gold in bull markets.")
def show_trade_history():
    """Show recent trades with RSI signal reasoning from activity log."""
    import re
    log_path = CONFIG_DIR / "activity.log"
    if not log_path.exists():
        print("\n No activity log found.\n")
        return

    lines = log_path.read_text().splitlines()

    # Parse log into trading sessions (each starts with "Starting daily check")
    sessions = []
    current = None
    for line in lines:
        if "Starting daily check" in line:
            current = {"time": line[:20].strip("[] "), "signal": "",
                       "portfolio": "", "trades": [], "reason": ""}
        elif current:
            if "Long-term allocation:" in line and not current["signal"]:
                m = re.search(r"Long-term allocation: (.+?) \| scores: (.+)", line)
                if m:
                    current["signal"] = m.group(1)
                    current["reason"] = m.group(2)
            elif "BUY $" in line or "BUY " in line and "shares" not in line:
                m = re.search(r"BUY \$([0-9.]+) of (\w+)", line)
                if m:
                    current["trades"].append(f"  BUY  ${m.group(1):>8}  {m.group(2)}")
            elif "SELL " in line and "shares of" in line:
                m = re.search(r"SELL ([0-9.]+) shares of (\w+)", line)
                if m:
                    current["trades"].append(f"  SELL {float(m.group(1)):>8.4f}  {m.group(2)}")
            elif "Daily check complete" in line:
                m = re.search(r"Portfolio: \$([0-9,.]+)", line)
                if m:
                    current["portfolio"] = m.group(1)
                sessions.append(current)
                current = None

    # Show last 10 sessions that had trades
    sessions_with_trades = [s for s in sessions if s["trades"]]
    recent = sessions_with_trades[-10:] if sessions_with_trades else []

    print(f"""
════════════════════════════════════════════════════════════════
 📜 RECENT TRADES
════════════════════════════════════════════════════════════════""")

    if not recent:
        print(" No trades recorded yet.\n")
        return

    for s in recent:
        signal_str = s["signal"] if s["signal"] else "unknown"
        reason_str = s["reason"] if s["reason"] else ""
        print(f"""
 {s['time']}  |  Signal: {signal_str}  |  {reason_str}
 Portfolio: ${s['portfolio']}
 ────────────────────────────────────────""")
        for t in s["trades"]:
            print(f"  {t}")

    print(f"""
════════════════════════════════════════════════════════════════
""")


def main():
    import sys

    if len(sys.argv) < 2:
        print("""
Long-Term Hold Bot v5.0

Usage: python3 autonomous_investor.py [command]

Commands:
  --daily     Run the daily check (rescan/rebalance/exit checks)
  --weekly    Email the weekly report
  --status    Current holdings & performance
  --benchmark Performance vs S&P 500
  --trades    Recent trades & reasoning
        """)
        return

    config = load_config()
    command = sys.argv[1]

    if command == "--daily":
        run_daily_check(config)
    elif command == "--weekly":
        run_weekly_report(config)
    elif command == "--status":
        show_status()
    elif command == "--benchmark":
        show_benchmark()
    elif command == "--trades":
        show_trade_history()


if __name__ == "__main__":
    main()
