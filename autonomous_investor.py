#!/usr/bin/env python3
"""
RSI Day-Trader Bot v4.0
Features:
- RSI Buy-Low / Sell-High Strategy
- Leveraged ETFs (TQQQ, SOXL, UPRO, TECL, FNGU)
- Individual Stocks (NVDA, AAPL, TSLA, AMD, META, AMZN, GOOGL, MSFT)
- Per-Asset RSI Weight Adjustment
- Daily Rebalancing / 10% Drift
- Performance vs S&P 500 Tracking
- Paper Trading Comparison
"""

import json
import math
import os
import smtplib
import urllib.request
import urllib.error
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
PAPER_FILE = CONFIG_DIR / "paper_portfolio.json"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# =============================================================================
# ENHANCED ASSET DEFINITIONS WITH SECTORS
# =============================================================================

ASSETS = {
    # === LEVERAGED ETFs (3x) ===
    "TQQQ": {
        "name": "3x Nasdaq",
        "ticker": "TQQQ",
        "sector": "leveraged_tech",
        "base_return": 30.0,
        "volatility": 48.0,
        "leverage": 3,
        "trailing_stop_pct": 15.0
    },
    "SOXL": {
        "name": "3x Semis",
        "ticker": "SOXL",
        "sector": "leveraged_tech",
        "base_return": 35.0,
        "volatility": 60.0,
        "leverage": 3,
        "trailing_stop_pct": 15.0
    },
    "UPRO": {
        "name": "3x S&P 500",
        "ticker": "UPRO",
        "sector": "leveraged_broad",
        "base_return": 28.0,
        "volatility": 45.0,
        "leverage": 3,
        "trailing_stop_pct": 15.0
    },
    "TECL": {
        "name": "3x Tech",
        "ticker": "TECL",
        "sector": "leveraged_tech",
        "base_return": 32.0,
        "volatility": 50.0,
        "leverage": 3,
        "trailing_stop_pct": 15.0
    },
    "FNGU": {
        "name": "3x FANG+",
        "ticker": "FNGU",
        "sector": "leveraged_tech",
        "base_return": 33.0,
        "volatility": 55.0,
        "leverage": 3,
        "trailing_stop_pct": 15.0
    },
    # === BROAD MARKET ===
    "SPY_HOLD": {
        "name": "S&P 500 ETF",
        "ticker": "SPY",
        "sector": "broad_market",
        "base_return": 12.0,
        "volatility": 15.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    # === INDIVIDUAL STOCKS ===
    "NVDA": {
        "name": "NVIDIA",
        "ticker": "NVDA",
        "sector": "individual_tech",
        "base_return": 25.0,
        "volatility": 40.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    "AAPL": {
        "name": "Apple",
        "ticker": "AAPL",
        "sector": "individual_tech",
        "base_return": 18.0,
        "volatility": 25.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    "TSLA": {
        "name": "Tesla",
        "ticker": "TSLA",
        "sector": "individual_auto",
        "base_return": 20.0,
        "volatility": 50.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    "AMD": {
        "name": "AMD",
        "ticker": "AMD",
        "sector": "individual_tech",
        "base_return": 22.0,
        "volatility": 38.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    "META": {
        "name": "Meta",
        "ticker": "META",
        "sector": "individual_tech",
        "base_return": 20.0,
        "volatility": 32.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    "AMZN": {
        "name": "Amazon",
        "ticker": "AMZN",
        "sector": "individual_tech",
        "base_return": 18.0,
        "volatility": 30.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    "GOOGL": {
        "name": "Alphabet",
        "ticker": "GOOGL",
        "sector": "individual_tech",
        "base_return": 17.0,
        "volatility": 28.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    "MSFT": {
        "name": "Microsoft",
        "ticker": "MSFT",
        "sector": "individual_tech",
        "base_return": 17.0,
        "volatility": 25.0,
        "leverage": 1,
        "trailing_stop_pct": 10.0
    },
    # === INVERSE ETFs (bear market) ===
    "SQQQ": {
        "name": "3x Inverse Nasdaq",
        "ticker": "SQQQ",
        "sector": "inverse",
        "base_return": -30.0,
        "volatility": 48.0,
        "leverage": -3,
        "trailing_stop_pct": 12.0
    },
    "SPXU": {
        "name": "3x Inverse S&P",
        "ticker": "SPXU",
        "sector": "inverse",
        "base_return": -28.0,
        "volatility": 45.0,
        "leverage": -3,
        "trailing_stop_pct": 12.0
    },
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
    "leveraged_tech": 0.45,
    "leveraged_broad": 0.25,
    "individual_tech": 0.50,
    "individual_auto": 0.15,
    "inverse": 0.50,
    "crypto": 0.15
}

# Signal categories used in regime detection (for learning system)
REGIME_SIGNAL_NAMES = [
    "trend_cross",       # SMA10 vs SMA20
    "trend_price",       # Price vs SMA10
    "momentum",          # 10-period momentum
    "rsi",               # RSI overbought/oversold
    "vix",               # VIX fear gauge
    "macd",              # MACD crossover
    "bollinger",         # Bollinger Bands
    "volume",            # Volume analysis
    "yield_curve",       # Yield curve shape
    "sector_rotation",   # Sector rotation
    "market_breadth",    # Market breadth
    "news_sentiment",    # News sentiment
]

# Correlation matrix (simplified)
CORRELATIONS = {
    ("TQQQ", "SOXL"): 0.85,
    ("TQQQ", "TECL"): 0.92,
    ("TQQQ", "FNGU"): 0.90,
    ("TQQQ", "UPRO"): 0.88,
    ("SOXL", "NVDA"): 0.80,
    ("SOXL", "AMD"): 0.82,
    ("NVDA", "AMD"): 0.75,
    ("AAPL", "MSFT"): 0.65,
    ("META", "GOOGL"): 0.70,
    ("AMZN", "GOOGL"): 0.60,
    ("TQQQ", "NVDA"): 0.78,
    ("TQQQ", "CRYPTO"): 0.45,
    ("TSLA", "CRYPTO"): 0.40,
    ("SQQQ", "SPXU"): 0.88,
    ("SQQQ", "TQQQ"): -0.95,
    ("SPXU", "UPRO"): -0.95,
}


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

def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

DEFAULT_ALLOCATION = {
    "SPY_HOLD": 0.35,
    "TQQQ": 0.05, "SOXL": 0.03, "UPRO": 0.04,
    "TECL": 0.03, "FNGU": 0.00,
    "NVDA": 0.06, "AAPL": 0.05, "TSLA": 0.04,
    "AMD": 0.04, "META": 0.05, "AMZN": 0.04,
    "GOOGL": 0.05, "MSFT": 0.04,
    "SQQQ": 0.00, "SPXU": 0.00,
    "CRYPTO": 0.05,
}

def initialize_learning_state(brain: dict):
    """Ensure brain['learning'] exists with all required sub-keys."""
    defaults = {
        "open_positions": {},
        "closed_trades": [],
        "regime_predictions": [],
        "regime_signal_weights": {name: 1.0 for name in REGIME_SIGNAL_NAMES},
        "asset_regime_performance": {},
        "stop_loss_events": [],
        "learned_stop_adjustments": {},
        "momentum_outcomes": [],
        "learned_multipliers": {
            "strong_buy": 1.8,
            "buy": 1.4,
            "neutral": 1.0,
            "sell": 0.3,
            "strong_sell": 0.0,
        },
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
        "regime_history": [],
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

def track_trade_outcomes(client, brain: dict, regime: str):
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
                "regime": regime,
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
            "regime": entry.get("regime", "unknown"),
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

def calc_sma(history: list, period: int) -> float:
    if not history or len(history) < period:
        return None
    return sum(h['close'] for h in history[-period:]) / period

def calc_momentum(history: list, period: int = 20) -> float:
    if not history or len(history) < period:
        return None
    return (history[-1]['close'] - history[-period]['close']) / history[-period]['close']

def calc_rsi(history: list, period: int = 14) -> float:
    if not history or len(history) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        change = history[i]['close'] - history[i-1]['close']
        gains.append(max(0, change))
        losses.append(max(0, -change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    return 100 - (100 / (1 + avg_gain / avg_loss))


def calc_macd(history: list, fast: int = 5, slow: int = 13, signal_period: int = 5) -> dict:
    """Calculate MACD indicator. Default (5,13,5) tuned for intraday day trading."""
    min_len = slow + signal_period + 5
    if not history or len(history) < min_len:
        return None

    closes = [h['close'] for h in history]

    # EMA calculation helper
    def ema(data, period):
        multiplier = 2 / (period + 1)
        ema_values = [sum(data[:period]) / period]
        for price in data[period:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    # Align arrays
    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
    signal_line = ema(macd_line, signal_period)

    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    histogram = current_macd - current_signal

    # Determine signal
    if current_macd > current_signal and histogram > 0:
        signal = "bullish"
    elif current_macd < current_signal and histogram < 0:
        signal = "bearish"
    else:
        signal = "neutral"

    return {
        "macd": current_macd,
        "signal_line": current_signal,
        "histogram": histogram,
        "signal": signal
    }


def calc_bollinger_bands(history: list, period: int = 20) -> dict:
    """Calculate Bollinger Bands."""
    if not history or len(history) < period:
        return None

    closes = [h['close'] for h in history[-period:]]
    sma = sum(closes) / period
    variance = sum((c - sma) ** 2 for c in closes) / period
    std_dev = variance ** 0.5

    upper = sma + (2 * std_dev)
    lower = sma - (2 * std_dev)
    current = history[-1]['close']

    # Position within bands (0 = lower, 1 = upper)
    band_position = (current - lower) / (upper - lower) if upper != lower else 0.5

    # Bandwidth (volatility indicator)
    bandwidth = (upper - lower) / sma

    if band_position > 0.95:
        signal = "overbought"
    elif band_position < 0.05:
        signal = "oversold"
    elif band_position > 0.8:
        signal = "high"
    elif band_position < 0.2:
        signal = "low"
    else:
        signal = "neutral"

    return {
        "upper": upper,
        "middle": sma,
        "lower": lower,
        "current": current,
        "position": band_position,
        "bandwidth": bandwidth,
        "signal": signal
    }


def calc_atr(history: list, period: int = 14) -> float:
    """Calculate Average True Range (volatility measure)."""
    if not history or len(history) < period + 1:
        return None

    true_ranges = []
    for i in range(-period, 0):
        high = history[i]['high']
        low = history[i]['low']
        prev_close = history[i-1]['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    return sum(true_ranges) / period


def calc_volume_trend(history: list, period: int = 20) -> dict:
    """Analyze volume trends."""
    if not history or len(history) < period:
        return None

    recent = history[-period:]
    volumes = [h.get('volume', 0) for h in recent]

    if not any(volumes):
        return {"signal": "no_data", "trend": 0}

    avg_volume = sum(volumes) / len(volumes)
    recent_avg = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else avg_volume

    # Volume trend
    volume_ratio = recent_avg / avg_volume if avg_volume > 0 else 1

    # Price direction with volume
    price_change = (recent[-1]['close'] - recent[0]['close']) / recent[0]['close']

    if volume_ratio > 1.5 and price_change > 0:
        signal = "strong_bullish"
    elif volume_ratio > 1.5 and price_change < 0:
        signal = "strong_bearish"
    elif volume_ratio > 1.2 and price_change > 0:
        signal = "bullish"
    elif volume_ratio > 1.2 and price_change < 0:
        signal = "bearish"
    else:
        signal = "neutral"

    return {
        "avg_volume": avg_volume,
        "recent_volume": recent_avg,
        "ratio": volume_ratio,
        "price_change": price_change,
        "signal": signal
    }


def fetch_yield_curve() -> dict:
    """Fetch Treasury yield curve (10Y - 2Y spread)."""
    try:
        # Use Yahoo Finance for Treasury ETFs as proxy
        tlt = fetch_yahoo_history("TLT", 5, "1h")  # 20+ Year Treasury
        shy = fetch_yahoo_history("SHY", 5, "1h")  # 1-3 Year Treasury

        if not tlt or not shy:
            return {"spread": None, "signal": "no_data"}

        # Calculate yield proxy from price changes
        # When long-term bonds fall more than short-term, curve is steepening
        lookback = min(20, len(tlt) - 1, len(shy) - 1)
        if lookback < 2:
            return {"spread": None, "signal": "no_data"}
        tlt_change = (tlt[-1]['close'] - tlt[-lookback]['close']) / tlt[-lookback]['close']
        shy_change = (shy[-1]['close'] - shy[-lookback]['close']) / shy[-lookback]['close']

        # Relative performance indicates curve shape changes
        spread_proxy = (shy_change - tlt_change) * 100

        if spread_proxy > 2:
            signal = "steepening"  # Bullish for economy
        elif spread_proxy < -2:
            signal = "flattening"  # Caution
        else:
            signal = "stable"

        return {
            "spread_proxy": spread_proxy,
            "tlt_change": tlt_change * 100,
            "shy_change": shy_change * 100,
            "signal": signal
        }
    except Exception as e:
        log(f"Yield curve fetch failed: {e}", "WARNING")
        return {"spread": None, "signal": "no_data"}


def fetch_sector_rotation() -> dict:
    """Analyze sector rotation for market phase detection."""
    sectors = {
        "XLK": "Technology",
        "XLF": "Financials",
        "XLE": "Energy",
        "XLV": "Healthcare",
        "XLY": "Consumer Discretionary",
        "XLP": "Consumer Staples",
        "XLU": "Utilities",
        "XLI": "Industrials",
        "XLB": "Materials",
        "XLRE": "Real Estate"
    }

    # Cyclical vs Defensive
    cyclical = ["XLK", "XLF", "XLY", "XLI", "XLB"]
    defensive = ["XLV", "XLP", "XLU", "XLRE"]

    results = {}
    cyclical_perf = []
    defensive_perf = []

    try:
        for ticker, name in sectors.items():
            history = fetch_yahoo_history(ticker, 5, "1h")
            if history and len(history) >= 20:
                perf_20d = (history[-1]['close'] - history[-min(20, len(history)-1)]['close']) / history[-min(20, len(history)-1)]['close']
                perf_5d = (history[-1]['close'] - history[-min(5, len(history)-1)]['close']) / history[-min(5, len(history)-1)]['close']
                results[ticker] = {
                    "name": name,
                    "perf_20d": perf_20d * 100,
                    "perf_5d": perf_5d * 100
                }

                if ticker in cyclical:
                    cyclical_perf.append(perf_20d)
                elif ticker in defensive:
                    defensive_perf.append(perf_20d)

        # Calculate rotation signal
        avg_cyclical = sum(cyclical_perf) / len(cyclical_perf) if cyclical_perf else 0
        avg_defensive = sum(defensive_perf) / len(defensive_perf) if defensive_perf else 0

        rotation_score = avg_cyclical - avg_defensive

        if rotation_score > 0.02:
            signal = "risk_on"
            phase = "expansion"
        elif rotation_score < -0.02:
            signal = "risk_off"
            phase = "contraction"
        else:
            signal = "neutral"
            phase = "transition"

        # Find leaders and laggards
        sorted_sectors = sorted(results.items(), key=lambda x: x[1]['perf_20d'], reverse=True)
        leaders = [f"{s[1]['name']}" for s in sorted_sectors[:3]]
        laggards = [f"{s[1]['name']}" for s in sorted_sectors[-3:]]

        return {
            "sectors": results,
            "cyclical_avg": avg_cyclical * 100,
            "defensive_avg": avg_defensive * 100,
            "rotation_score": rotation_score * 100,
            "signal": signal,
            "phase": phase,
            "leaders": leaders,
            "laggards": laggards
        }
    except Exception as e:
        log(f"Sector rotation fetch failed: {e}", "WARNING")
        return {"signal": "no_data", "phase": "unknown"}


def fetch_market_breadth() -> dict:
    """Analyze market breadth using sector ETFs."""
    etfs = ["SPY", "QQQ", "IWM", "DIA"]

    try:
        above_sma = 0
        positive_momentum = 0
        results = {}

        for ticker in etfs:
            history = fetch_yahoo_history(ticker, 7, "1h")
            if history and len(history) >= 20:
                sma20 = calc_sma(history, 20)
                current = history[-1]['close']
                mom = calc_momentum(history, 10)

                is_above = current > sma20 if sma20 else False
                is_positive = mom > 0 if mom else False

                if is_above:
                    above_sma += 1
                if is_positive:
                    positive_momentum += 1

                results[ticker] = {
                    "price": current,
                    "sma20": sma20,
                    "above_sma": is_above,
                    "momentum": mom * 100 if mom else 0
                }

        breadth_pct = above_sma / len(etfs)
        momentum_pct = positive_momentum / len(etfs)

        if breadth_pct >= 0.8 and momentum_pct >= 0.8:
            signal = "strong_bullish"
        elif breadth_pct >= 0.6:
            signal = "bullish"
        elif breadth_pct <= 0.2:
            signal = "bearish"
        elif breadth_pct <= 0.4:
            signal = "weak"
        else:
            signal = "mixed"

        return {
            "above_sma20_pct": breadth_pct * 100,
            "positive_momentum_pct": momentum_pct * 100,
            "signal": signal,
            "details": results
        }
    except Exception as e:
        log(f"Market breadth fetch failed: {e}", "WARNING")
        return {"signal": "no_data"}


# =============================================================================
# FEATURE 1: NEWS SENTIMENT ANALYSIS
# =============================================================================

def fetch_news_sentiment() -> dict:
    """Analyze market news sentiment using free RSS feeds."""
    sentiment = {"score": 0, "headlines": [], "signal": "neutral"}

    # Negative keywords (bearish)
    negative_words = [
        "crash", "plunge", "recession", "crisis", "bear", "sell-off", "selloff",
        "fear", "panic", "collapse", "decline", "drop", "fall", "sink", "tumble",
        "warning", "risk", "threat", "concern", "worry", "inflation", "layoff",
        "bankruptcy", "default", "downgrade", "cut", "slash", "worst"
    ]

    # Positive keywords (bullish)
    positive_words = [
        "rally", "surge", "boom", "bull", "growth", "gain", "rise", "jump",
        "soar", "record", "high", "strong", "beat", "exceed", "optimism",
        "recovery", "rebound", "upgrade", "buy", "best", "profit", "earnings"
    ]

    try:
        # Fetch Google News RSS for market news
        urls = [
            "https://news.google.com/rss/search?q=stock+market&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=S%26P+500&hl=en-US&gl=US&ceid=US:en"
        ]

        headlines = []
        for url in urls:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                content = response.read().decode()
                # Extract titles from RSS
                titles = re.findall(r'<title>(.*?)</title>', content)
                headlines.extend(titles[1:6])  # Skip first (feed title), take 5

        # Analyze sentiment
        pos_count = 0
        neg_count = 0

        for headline in headlines:
            headline_lower = headline.lower()
            for word in negative_words:
                if word in headline_lower:
                    neg_count += 1
            for word in positive_words:
                if word in headline_lower:
                    pos_count += 1

        # Calculate score (-1 to +1)
        total = pos_count + neg_count
        if total > 0:
            sentiment["score"] = (pos_count - neg_count) / total

        if sentiment["score"] > 0.3:
            sentiment["signal"] = "bullish"
        elif sentiment["score"] < -0.3:
            sentiment["signal"] = "bearish"
        else:
            sentiment["signal"] = "neutral"

        sentiment["headlines"] = headlines[:5]
        sentiment["positive_count"] = pos_count
        sentiment["negative_count"] = neg_count

    except Exception as e:
        log(f"News sentiment fetch failed: {e}", "WARNING")
        sentiment["signal"] = "neutral"

    return sentiment


# =============================================================================
# FEATURE 2: EARNINGS CALENDAR AWARENESS
# =============================================================================

def check_earnings_risk(symbols: list) -> dict:
    """Check if any individual stock holdings have earnings risk."""
    today = datetime.now()
    month = today.month
    day = today.day

    # Earnings season: first 3 weeks of Jan, Apr, Jul, Oct
    earnings_season = month in [1, 4, 7, 10] and day <= 21

    # Identify individual stocks at risk during earnings season
    individual_tickers = {info["ticker"] for info in ASSETS.values()
                          if info.get("leverage", 1) == 1 and info["sector"] != "crypto"}
    stocks_held = [s for s in symbols if s in individual_tickers]

    result = {
        "is_earnings_season": earnings_season,
        "recommendation": "normal",
        "message": "",
        "stocks_at_risk": []
    }

    if earnings_season and stocks_held:
        result["recommendation"] = "reduce_individual"
        result["stocks_at_risk"] = stocks_held
        result["message"] = (f"Earnings season! Individual stocks at risk: "
                           f"{', '.join(stocks_held)}. Reduce positions or tighten stops.")
        log(f"Earnings risk: {result['message']}", "WARNING")
    elif earnings_season:
        result["recommendation"] = "cautious"
        result["message"] = "Earnings season active - increased volatility expected"
        log(f"Earnings season warning: {result['message']}", "INFO")

    return result


# =============================================================================
# FEATURE 3: MOMENTUM SIGNALS
# =============================================================================

def calculate_momentum_signals(brain=None) -> dict:
    """Calculate momentum for each asset to overweight winners.
    If brain is provided, uses learned multipliers instead of hard-coded defaults."""
    signals = {}

    # Load learned multipliers if available
    learned = {}
    if brain and "learning" in brain:
        learned = brain["learning"].get("learned_multipliers", {})

    default_multipliers = {
        "strong_buy": learned.get("strong_buy", 1.8),
        "buy": learned.get("buy", 1.4),
        "neutral": learned.get("neutral", 1.0),
        "sell": learned.get("sell", 0.3),
        "strong_sell": learned.get("strong_sell", 0.0),
    }

    for asset_id, asset_info in ASSETS.items():
        ticker = asset_info["ticker"]
        history = fetch_yahoo_history(ticker, 5, "1h")

        if not history:
            signals[asset_id] = {"momentum": 0, "signal": "neutral", "multiplier": default_multipliers["neutral"]}
            continue

        # 20-day momentum
        mom_20 = calc_momentum(history, 20)
        # 5-day momentum (short-term)
        mom_5 = calc_momentum(history, 5) if len(history) >= 5 else 0

        # RSI
        rsi = calc_rsi(history, 14)

        # Combined score
        if mom_20 is None:
            mom_20 = 0
        if mom_5 is None:
            mom_5 = 0

        # Balanced momentum: equal weight reduces whipsaw from short-term noise
        score = (mom_20 * 0.5) + (mom_5 * 0.5)

        # Determine signal category, then use learned multipliers
        if score > 0.03 and (rsi is None or rsi < 75):
            signal = "strong_buy"
        elif score > 0.01:
            signal = "buy"
        elif score < -0.03 and (rsi is None or rsi > 25):
            signal = "strong_sell"
        elif score < -0.01:
            signal = "sell"
        else:
            signal = "neutral"

        multiplier = default_multipliers.get(signal, 1.0)
        current_price = history[-1]["close"] if history else None

        signals[asset_id] = {
            "momentum_20d": mom_20,
            "momentum_5d": mom_5,
            "rsi": rsi,
            "signal": signal,
            "multiplier": multiplier,
            "current_price": current_price,
        }

    return signals


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

    for pos in positions:
        symbol = pos["symbol"]
        current_price = float(pos["current_price"])
        qty = float(pos["qty"])

        # Look up per-asset trailing stop percentage
        asset_stop_pct = default_trailing_pct
        is_inverse = False
        for asset_id, asset_info in ASSETS.items():
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

def apply_sector_limits(allocation: dict) -> dict:
    """Ensure no sector exceeds its limit."""
    # Calculate sector totals
    sector_totals = defaultdict(float)
    for asset_id, weight in allocation.items():
        sector = ASSETS[asset_id]["sector"]
        sector_totals[sector] += weight

    # Check and adjust
    adjusted = allocation.copy()
    for sector, total in sector_totals.items():
        limit = SECTOR_LIMITS.get(sector, 1.0)
        if total > limit:
            # Scale down assets in this sector
            scale = limit / total
            for asset_id in allocation:
                if ASSETS[asset_id]["sector"] == sector:
                    adjusted[asset_id] *= scale
            log(f"Sector {sector} exceeded limit ({total*100:.1f}% > {limit*100:.1f}%), scaled down", "INFO")

    # Normalize
    total = sum(adjusted.values())
    if total > 0:
        adjusted = {k: v/total for k, v in adjusted.items()}

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
# ENHANCED MARKET REGIME DETECTION
# =============================================================================

def detect_market_regime(brain=None) -> dict:
    """
    Intraday regime detection for day trading:
    - Moving averages (SMA10, SMA20 on hourly bars)
    - Momentum & RSI (short-term)
    - VIX (fear gauge)
    - MACD indicator (5,13,5)
    - Bollinger Bands
    - Volume analysis
    - Yield curve
    - Sector rotation
    - Market breadth
    - News sentiment

    If brain is provided, applies learned signal weights and returns
    per-signal scores in a 'signal_scores' dict.
    """
    spy = fetch_yahoo_history("SPY", 7, "1h")
    vix = fetch_yahoo_history("^VIX", 3, "1h")

    if not spy:
        return {"name": "neutral", "score": 0, "confidence": 0.5, "signals": [], "analysis": {}, "signal_scores": {}}

    # Load learned signal weights
    weights = {}
    if brain and "learning" in brain:
        weights = brain["learning"].get("regime_signal_weights", {})

    def _w(signal_name):
        return weights.get(signal_name, 1.0)

    price = spy[-1]['close']
    sma10 = calc_sma(spy, 10)
    sma20 = calc_sma(spy, 20)
    momentum = calc_momentum(spy, 10)
    rsi = calc_rsi(spy, 14)
    vix_val = vix[-1]['close'] if vix else None

    score = 0
    signals = []
    analysis = {}
    signal_scores = {}  # per-signal raw contribution

    # ═══════════════════════════════════════════════════════════════
    # TREND ANALYSIS (weight: high)
    # ═══════════════════════════════════════════════════════════════
    if sma10 and sma20:
        raw = 2 if sma10 > sma20 else -2
        weighted = raw * _w("trend_cross")
        signal_scores["trend_cross"] = raw
        score += weighted
        if sma10 > sma20:
            signals.append("Bullish Cross (SMA10>20)")
        else:
            signals.append("Bearish Cross (SMA10<20)")

    if sma10:
        raw = 1 if price > sma10 else -1
        weighted = raw * _w("trend_price")
        signal_scores["trend_price"] = raw
        score += weighted
        if price > sma10:
            signals.append("Price above SMA10")
        else:
            signals.append("Price below SMA10")

    # ═══════════════════════════════════════════════════════════════
    # MOMENTUM ANALYSIS
    # ═══════════════════════════════════════════════════════════════
    if momentum:
        if momentum > 0.02:
            raw = 2
            signals.append(f"Strong momentum +{momentum*100:.1f}%")
        elif momentum > 0:
            raw = 1
            signals.append(f"Positive momentum +{momentum*100:.1f}%")
        elif momentum > -0.02:
            raw = -1
            signals.append(f"Weak momentum {momentum*100:.1f}%")
        else:
            raw = -2
            signals.append(f"Negative momentum {momentum*100:.1f}%")
        weighted = raw * _w("momentum")
        signal_scores["momentum"] = raw
        score += weighted

    if rsi:
        analysis["rsi"] = rsi
        raw = 0
        if rsi > 70:
            signals.append(f"Overbought RSI={rsi:.0f}")
            raw = -1
        elif rsi < 30:
            signals.append(f"Oversold RSI={rsi:.0f}")
            raw = 1
        if raw != 0:
            weighted = raw * _w("rsi")
            signal_scores["rsi"] = raw
            score += weighted

    # ═══════════════════════════════════════════════════════════════
    # VOLATILITY ANALYSIS (VIX)
    # ═══════════════════════════════════════════════════════════════
    if vix_val:
        analysis["vix"] = vix_val
        raw = 0
        if vix_val > 30:
            signals.append(f"Extreme fear VIX={vix_val:.0f}")
            raw = -2
        elif vix_val > 25:
            signals.append(f"High fear VIX={vix_val:.0f}")
            raw = -1
        elif vix_val < 15:
            signals.append(f"Complacency VIX={vix_val:.0f}")
            raw = 1
        if raw != 0:
            weighted = raw * _w("vix")
            signal_scores["vix"] = raw
            score += weighted

    # ═══════════════════════════════════════════════════════════════
    # MACD INDICATOR
    # ═══════════════════════════════════════════════════════════════
    macd = calc_macd(spy)
    if macd:
        analysis["macd"] = macd
        raw = 0
        if macd["signal"] == "bullish":
            signals.append("MACD bullish crossover")
            raw = 1
        elif macd["signal"] == "bearish":
            signals.append("MACD bearish crossover")
            raw = -1
        if raw != 0:
            weighted = raw * _w("macd")
            signal_scores["macd"] = raw
            score += weighted

    # ═══════════════════════════════════════════════════════════════
    # BOLLINGER BANDS
    # ═══════════════════════════════════════════════════════════════
    bb = calc_bollinger_bands(spy)
    if bb:
        analysis["bollinger"] = bb
        raw = 0
        if bb["signal"] == "oversold":
            signals.append("BB oversold (potential bounce)")
            raw = 1
        elif bb["signal"] == "overbought":
            signals.append("BB overbought (potential pullback)")
            raw = -1
        if raw != 0:
            weighted = raw * _w("bollinger")
            signal_scores["bollinger"] = raw
            score += weighted
        # High bandwidth = high volatility
        if bb["bandwidth"] > 0.1:
            signals.append(f"High volatility (BB width {bb['bandwidth']*100:.1f}%)")

    # ═══════════════════════════════════════════════════════════════
    # VOLUME ANALYSIS
    # ═══════════════════════════════════════════════════════════════
    volume = calc_volume_trend(spy)
    if volume and volume.get("signal") != "no_data":
        analysis["volume"] = volume
        raw = 0
        if volume["signal"] == "strong_bullish":
            signals.append("Strong volume + price up")
            raw = 1
        elif volume["signal"] == "strong_bearish":
            signals.append("Strong volume + price down")
            raw = -1
        if raw != 0:
            weighted = raw * _w("volume")
            signal_scores["volume"] = raw
            score += weighted

    # ═══════════════════════════════════════════════════════════════
    # YIELD CURVE ANALYSIS
    # ═══════════════════════════════════════════════════════════════
    try:
        yield_curve = fetch_yield_curve()
        if yield_curve.get("signal") != "no_data":
            analysis["yield_curve"] = yield_curve
            raw = 0
            if yield_curve["signal"] == "steepening":
                signals.append("Yield curve steepening (economic growth)")
                raw = 1
            elif yield_curve["signal"] == "flattening":
                signals.append("Yield curve flattening (caution)")
                raw = -1
            if raw != 0:
                weighted = raw * _w("yield_curve")
                signal_scores["yield_curve"] = raw
                score += weighted
    except:
        pass

    # ═══════════════════════════════════════════════════════════════
    # SECTOR ROTATION
    # ═══════════════════════════════════════════════════════════════
    try:
        sectors = fetch_sector_rotation()
        if sectors.get("signal") != "no_data":
            analysis["sector_rotation"] = sectors
            raw = 0
            if sectors["signal"] == "risk_on":
                signals.append(f"Risk-on rotation ({sectors['phase']})")
                raw = 1
            elif sectors["signal"] == "risk_off":
                signals.append(f"Risk-off rotation ({sectors['phase']})")
                raw = -1
            if raw != 0:
                weighted = raw * _w("sector_rotation")
                signal_scores["sector_rotation"] = raw
                score += weighted
            if sectors.get("leaders"):
                analysis["sector_leaders"] = sectors["leaders"]
    except:
        pass

    # ═══════════════════════════════════════════════════════════════
    # MARKET BREADTH
    # ═══════════════════════════════════════════════════════════════
    try:
        breadth = fetch_market_breadth()
        if breadth.get("signal") != "no_data":
            analysis["market_breadth"] = breadth
            raw = 0
            if breadth["signal"] == "strong_bullish":
                signals.append(f"Strong breadth ({breadth['above_sma20_pct']:.0f}% above SMA20)")
                raw = 1
            elif breadth["signal"] == "bearish":
                signals.append(f"Weak breadth ({breadth['above_sma20_pct']:.0f}% above SMA20)")
                raw = -1
            if raw != 0:
                weighted = raw * _w("market_breadth")
                signal_scores["market_breadth"] = raw
                score += weighted
    except:
        pass

    # ═══════════════════════════════════════════════════════════════
    # NEWS SENTIMENT
    # ═══════════════════════════════════════════════════════════════
    news = fetch_news_sentiment()
    analysis["news"] = news
    raw = 0
    if news["signal"] == "bullish":
        signals.append("Bullish news sentiment")
        raw = 1
    elif news["signal"] == "bearish":
        signals.append("Bearish news sentiment")
        raw = -1
    if raw != 0:
        weighted = raw * _w("news_sentiment")
        signal_scores["news_sentiment"] = raw
        score += weighted

    # ═══════════════════════════════════════════════════════════════
    # DETERMINE FINAL REGIME
    # ═══════════════════════════════════════════════════════════════
    # Expanded scoring with more signals
    if score >= 6:
        name = "strong_bull"
    elif score >= 3:
        name = "bull"
    elif score >= -2:
        name = "neutral"
    elif score >= -5:
        name = "bear"
    else:
        name = "strong_bear"

    # Confidence based on signal agreement
    num_signals = len(signals)
    bullish_signals = len([s for s in signals if any(w in s.lower() for w in ['bullish', 'above', 'golden', 'strong momentum', 'positive', 'oversold', 'steepening', 'risk-on'])])
    bearish_signals = len([s for s in signals if any(w in s.lower() for w in ['bearish', 'below', 'death', 'negative', 'fear', 'overbought', 'flattening', 'risk-off', 'weak'])])

    if num_signals > 0:
        agreement = max(bullish_signals, bearish_signals) / num_signals
        confidence = min(0.95, 0.5 + agreement * 0.4 + abs(score) * 0.02)
    else:
        confidence = 0.5

    return {
        "name": name,
        "score": score,
        "confidence": confidence,
        "signals": signals,
        "spy_price": price,
        "vix": vix_val,
        "news_sentiment": news,
        "analysis": analysis,
        "signal_scores": signal_scores,
        "indicators_used": num_signals,
        "timestamp": datetime.now().isoformat()
    }


# =============================================================================
# SELF-LEARNING: REGIME SIGNAL ACCURACY
# =============================================================================

def track_regime_prediction(brain: dict, regime: dict):
    """Record today's regime prediction and per-signal scores."""
    learning = brain["learning"]
    today = datetime.now().isoformat()[:10]

    # Don't duplicate if already recorded today
    if learning["regime_predictions"] and learning["regime_predictions"][-1].get("date") == today:
        return

    spy_price = regime.get("spy_price", 0)
    learning["regime_predictions"].append({
        "date": today,
        "regime": regime["name"],
        "score": regime["score"],
        "signal_scores": regime.get("signal_scores", {}),
        "spy_price": spy_price,
        "validated": False,
        "actual_direction": None,
    })

    # 90-day rolling window
    cutoff = (datetime.now() - timedelta(days=60)).isoformat()[:10]
    learning["regime_predictions"] = [
        p for p in learning["regime_predictions"]
        if p.get("date", "") >= cutoff
    ]


def validate_regime_predictions(brain: dict):
    """After 7 days, check if SPY moved in the predicted direction."""
    learning = brain["learning"]
    today = datetime.now()

    try:
        spy_history = fetch_yahoo_history("SPY", 14, "1d")
    except Exception:
        return

    if not spy_history or len(spy_history) < 2:
        return

    # Build date->price map
    price_map = {}
    for h in spy_history:
        price_map[h["date"][:10]] = h["close"]

    for pred in learning["regime_predictions"]:
        if pred.get("validated"):
            continue
        pred_date = pred.get("date", "")
        try:
            days_ago = (today - datetime.fromisoformat(pred_date)).days
        except Exception:
            continue
        if days_ago < 7:
            continue

        spy_at_pred = pred.get("spy_price", 0)
        if spy_at_pred <= 0:
            continue

        # Find SPY price ~7 days after prediction
        target_date = (datetime.fromisoformat(pred_date) + timedelta(days=7)).isoformat()[:10]
        spy_after = None
        for d in sorted(price_map.keys()):
            if d >= target_date:
                spy_after = price_map[d]
                break
        if spy_after is None and price_map:
            spy_after = list(price_map.values())[-1]
        if spy_after is None:
            continue

        actual_return = (spy_after - spy_at_pred) / spy_at_pred
        # Bullish regimes predict up, bearish predict down
        predicted_bullish = pred["regime"] in ("strong_bull", "bull")
        predicted_bearish = pred["regime"] in ("bear", "strong_bear")
        actual_up = actual_return > 0.001
        actual_down = actual_return < -0.001

        if predicted_bullish:
            pred["actual_direction"] = "correct" if actual_up else "incorrect"
        elif predicted_bearish:
            pred["actual_direction"] = "correct" if actual_down else "incorrect"
        else:
            pred["actual_direction"] = "neutral"

        pred["validated"] = True
        pred["actual_return"] = actual_return


def learn_regime_signal_weights(brain: dict):
    """Adjust signal weights based on prediction accuracy. Max 5% per cycle."""
    learning = brain["learning"]

    validated = [p for p in learning["regime_predictions"]
                 if p.get("validated") and p.get("actual_direction") in ("correct", "incorrect")]

    if len(validated) < 15:
        return

    # Per-signal accuracy
    signal_correct = defaultdict(int)
    signal_total = defaultdict(int)

    for pred in validated:
        direction = pred["actual_direction"]
        for sig_name, sig_score in pred.get("signal_scores", {}).items():
            predicted_bullish = sig_score > 0
            predicted_bearish = sig_score < 0
            actual_up = pred.get("actual_return", 0) > 0.001
            actual_down = pred.get("actual_return", 0) < -0.001

            sig_correct = False
            if predicted_bullish and actual_up:
                sig_correct = True
            elif predicted_bearish and actual_down:
                sig_correct = True

            signal_total[sig_name] += 1
            if sig_correct:
                signal_correct[sig_name] += 1

    weights = learning["regime_signal_weights"]
    for sig_name in REGIME_SIGNAL_NAMES:
        total = signal_total.get(sig_name, 0)
        if total < 5:
            continue
        accuracy = signal_correct[sig_name] / total
        current_weight = weights.get(sig_name, 1.0)
        if accuracy > 0.55:
            new_weight = current_weight * 1.05  # +5%
        elif accuracy < 0.45:
            new_weight = current_weight * 0.95  # -5%
        else:
            continue
        weights[sig_name] = max(0.2, min(3.0, new_weight))

    learning["regime_signal_weights"] = weights


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
# SELF-LEARNING: MOMENTUM SIGNAL EFFECTIVENESS
# =============================================================================

def track_momentum_signal(brain: dict, momentum_signals: dict):
    """Record each asset's momentum signal and current price."""
    learning = brain["learning"]
    today = datetime.now().isoformat()[:10]

    for asset_id, sig in momentum_signals.items():
        ticker = ASSETS.get(asset_id, {}).get("ticker", asset_id)
        try:
            price = sig.get("current_price")
            if not price:
                history = fetch_yahoo_history(ticker, 2, "1d")
                price = history[-1]["close"] if history else None
        except Exception:
            price = None
        if price is None:
            continue

        learning["momentum_outcomes"].append({
            "date": today,
            "asset": asset_id,
            "signal": sig.get("signal", "neutral"),
            "price_at_signal": price,
            "price_after_5d": None,
            "checked": False,
        })

    # 90-day rolling window
    cutoff = (datetime.now() - timedelta(days=60)).isoformat()[:10]
    learning["momentum_outcomes"] = [
        o for o in learning["momentum_outcomes"]
        if o.get("date", "") >= cutoff
    ]


def learn_momentum_effectiveness(brain: dict):
    """After 7 days, fill in actual 5-day return. Adjust multipliers."""
    learning = brain["learning"]
    today = datetime.now()

    for outcome in learning["momentum_outcomes"]:
        if outcome.get("checked"):
            continue
        outcome_date = outcome.get("date", "")
        try:
            days_since = (today - datetime.fromisoformat(outcome_date)).days
        except Exception:
            continue
        if days_since < 7:
            continue

        asset_id = outcome["asset"]
        ticker = ASSETS.get(asset_id, {}).get("ticker", asset_id)
        try:
            history = fetch_yahoo_history(ticker, 10, "1d")
        except Exception:
            continue
        if not history or len(history) < 2:
            continue

        # Use latest available price as the "after" price
        price_after = history[-1]["close"]
        outcome["price_after_5d"] = price_after
        outcome["checked"] = True
        price_at = outcome.get("price_at_signal", 0)
        if price_at > 0:
            outcome["actual_return"] = (price_after - price_at) / price_at
        else:
            outcome["actual_return"] = 0.0

    # Group by signal type and calculate average actual return
    signal_returns = defaultdict(list)
    for outcome in learning["momentum_outcomes"]:
        if outcome.get("checked") and "actual_return" in outcome:
            signal_returns[outcome["signal"]].append(outcome["actual_return"])

    multipliers = learning["learned_multipliers"]
    for signal_type, returns in signal_returns.items():
        if len(returns) < 8:
            continue
        avg_return = sum(returns) / len(returns)
        current_mult = multipliers.get(signal_type)
        if current_mult is None:
            continue

        # If strong_buy/buy signals led to actual gains, increase multiplier
        # If they led to losses, decrease. Vice versa for sell signals.
        if signal_type in ("strong_buy", "buy"):
            if avg_return > 0.005:
                new_mult = current_mult + 0.05
            elif avg_return < -0.005:
                new_mult = current_mult - 0.05
            else:
                continue
        elif signal_type in ("sell", "strong_sell"):
            if avg_return < -0.005:
                new_mult = current_mult - 0.05  # more aggressive sell
            elif avg_return > 0.005:
                new_mult = current_mult + 0.05  # less aggressive sell
            else:
                continue
        else:
            continue

        # Clamp: strong_buy [0.5, 2.5], buy [0.3, 2.0], sell [0.0, 1.5], strong_sell [0.0, 0.5]
        if signal_type == "strong_buy":
            multipliers[signal_type] = max(0.5, min(2.5, new_mult))
        elif signal_type == "buy":
            multipliers[signal_type] = max(0.3, min(2.0, new_mult))
        elif signal_type == "sell":
            multipliers[signal_type] = max(0.0, min(1.5, new_mult))
        elif signal_type == "strong_sell":
            multipliers[signal_type] = max(0.0, min(0.5, new_mult))

    learning["learned_multipliers"] = multipliers


# =============================================================================
# SELF-LEARNING: PER-ASSET REGIME PERFORMANCE
# =============================================================================

def learn_asset_regime_performance(brain: dict):
    """Build matrix of asset x regime -> avg return % from closed_trades."""
    learning = brain["learning"]

    perf = defaultdict(lambda: defaultdict(list))
    for trade in learning["closed_trades"]:
        symbol = trade.get("symbol", "")
        regime = trade.get("regime", "unknown")
        ret = trade.get("return_pct", 0)
        perf[symbol][regime].append(ret)

    result = {}
    for symbol in perf:
        result[symbol] = {}
        for regime in perf[symbol]:
            returns = perf[symbol][regime]
            result[symbol][regime] = {
                "avg_return": sum(returns) / len(returns) if returns else 0,
                "count": len(returns),
            }

    learning["asset_regime_performance"] = result


# =============================================================================
# ENHANCED ALLOCATION CALCULATION
# =============================================================================

def calculate_target_allocation(brain: dict, regime: dict, config: dict) -> dict:
    """
    RSI buy-low / sell-high allocation strategy.

    Uses SPY RSI + trend to determine macro allocation:
    - RSI low (oversold) → leverage up, buy the dip
    - RSI high + downtrend → take profits, go to cash
    - Default → heavy SPY to track benchmark
    Per-asset RSI adjusts individual weights (trim overbought, load oversold).
    """
    # Categorize assets
    leveraged_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) > 1]
    inverse_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) < 0]
    broad_keys = [k for k in ASSETS if ASSETS[k].get("sector") == "broad_market"]
    individual_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) == 1 and ASSETS[k]["sector"] not in ("crypto", "broad_market")]
    crypto_keys = [k for k in ASSETS if ASSETS[k]["sector"] == "crypto"]

    # SPY RSI + trend signal
    spy_hist = fetch_yahoo_history("SPY", 30, "1d")
    spy_rsi = calc_rsi(spy_hist, 14) if spy_hist and len(spy_hist) >= 15 else 50.0
    if spy_rsi is None:
        spy_rsi = 50.0
    spy_price = spy_hist[-1]["close"] if spy_hist else 0
    sma20 = sum(h['close'] for h in spy_hist[-20:]) / min(20, len(spy_hist)) if spy_hist and len(spy_hist) >= 5 else spy_price
    uptrend = spy_price > sma20

    if spy_rsi < 25:
        signal = "deep_value"
    elif spy_rsi < 40:
        signal = "buy_dip"
    elif spy_rsi > 75 and not uptrend:
        signal = "sell_high"
    elif spy_rsi > 65 and not uptrend:
        signal = "trim"
    else:
        signal = "hold"

    # RSI-based macro allocation
    if signal == "deep_value":
        leveraged_pct, broad_pct, individual_pct, inverse_pct, crypto_pct, cash_reserve = 0.50, 0.35, 0.10, 0.00, 0.05, 0.00
    elif signal == "buy_dip":
        leveraged_pct, broad_pct, individual_pct, inverse_pct, crypto_pct, cash_reserve = 0.25, 0.55, 0.15, 0.00, 0.05, 0.00
    elif signal == "sell_high":
        leveraged_pct, broad_pct, individual_pct, inverse_pct, crypto_pct, cash_reserve = 0.00, 0.25, 0.00, 0.10, 0.00, 0.65
    elif signal == "trim":
        leveraged_pct, broad_pct, individual_pct, inverse_pct, crypto_pct, cash_reserve = 0.00, 0.45, 0.05, 0.05, 0.00, 0.45
    else:  # hold — track SPY closely
        leveraged_pct, broad_pct, individual_pct, inverse_pct, crypto_pct, cash_reserve = 0.00, 0.85, 0.10, 0.00, 0.00, 0.05

    allocation = {}

    # Calculate momentum signals for per-asset weighting
    momentum = calculate_momentum_signals(brain)

    def distribute_within_group(keys, total_pct, top_n=None):
        """Distribute total_pct among keys, weighted by momentum. top_n picks best N."""
        if not keys or total_pct <= 0:
            for k in keys:
                allocation[k] = 0.0
            return
        weights = {}
        for k in keys:
            mom = momentum.get(k, {})
            multiplier = mom.get("multiplier", 1.0)
            # Per-asset RSI: buy low, sell high
            rsi = mom.get("rsi")
            if rsi is not None:
                if rsi > 75: multiplier *= 0.3
                elif rsi > 65: multiplier *= 0.6
                elif rsi < 25: multiplier *= 1.8
                elif rsi < 35: multiplier *= 1.4
            if mom.get("signal") == "strong_sell":
                multiplier *= 0.2
            weights[k] = max(0, multiplier)
        # Top N filter
        if top_n and len(weights) > top_n:
            sorted_keys = sorted(weights, key=lambda k: weights[k], reverse=True)
            weights = {k: weights[k] for k in sorted_keys[:top_n]}
        total_weight = sum(weights.values())
        if total_weight > 0:
            for k in weights:
                allocation[k] = (weights[k] / total_weight) * total_pct
        for k in keys:
            if k not in allocation:
                allocation[k] = 0.0

    distribute_within_group(broad_keys, broad_pct)
    distribute_within_group(leveraged_keys, leveraged_pct, top_n=3)
    distribute_within_group(individual_keys, individual_pct, top_n=3)
    distribute_within_group(inverse_keys, inverse_pct)
    distribute_within_group(crypto_keys, crypto_pct)

    # Scale so invested portion = (1 - cash_reserve)
    invested_total = sum(allocation.values())
    if invested_total > 0:
        target_invested = 1.0 - cash_reserve
        scale = target_invested / invested_total
        allocation = {k: v * scale for k, v in allocation.items()}

    # Ensure all ASSETS keys present
    for k in ASSETS:
        if k not in allocation:
            allocation[k] = 0.0

    # Apply sector limits
    allocation = apply_sector_limits(allocation)

    log(f"RSI signal: {signal} (SPY RSI={spy_rsi:.0f}, {'uptrend' if uptrend else 'downtrend'}) → "
        f"lev={leveraged_pct*100:.0f}% broad={broad_pct*100:.0f}% ind={individual_pct*100:.0f}% "
        f"inv={inverse_pct*100:.0f}% cash={cash_reserve*100:.0f}%")

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
        <h2>🤖 RSI Day-Trader Bot v4.0</h2>
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

    # Get current RSI signal
    spy_hist = fetch_yahoo_history("SPY", 30, "1d")
    spy_rsi = calc_rsi(spy_hist, 14) if spy_hist and len(spy_hist) >= 15 else 50.0
    if spy_rsi is None:
        spy_rsi = 50.0
    spy_price = spy_hist[-1]["close"] if spy_hist else 0
    sma20 = sum(h['close'] for h in spy_hist[-20:]) / min(20, len(spy_hist)) if spy_hist and len(spy_hist) >= 5 else spy_price
    uptrend = spy_price > sma20

    if spy_rsi < 25:
        signal = "deep_value"
    elif spy_rsi < 40:
        signal = "buy_dip"
    elif spy_rsi > 75 and not uptrend:
        signal = "sell_high"
    elif spy_rsi > 65 and not uptrend:
        signal = "trim"
    else:
        signal = "hold"

    report = f"""
════════════════════════════════════════════════════════════════════════
                    RSI DAY TRADER REPORT v4.0
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

RSI STRATEGY
────────────────────────────────────────────────────────────────────────
  Signal:          {signal.upper()}
  SPY RSI:         {spy_rsi:.1f}
  Trend:           {'Uptrend' if uptrend else 'Downtrend'}

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

def run_learning_cycle(client, brain: dict, regime: dict):
    """Run all learning functions in sequence. Wrapped in try/except for safety."""
    try:
        log("Starting learning cycle...")
        learning = brain["learning"]

        # 1. Track trade outcomes
        track_trade_outcomes(client, brain, regime.get("name", "neutral"))

        # 2. Track regime prediction
        track_regime_prediction(brain, regime)

        # 3. Validate past regime predictions
        validate_regime_predictions(brain)

        # 4. Learn regime signal weights (needs 30+ validated predictions)
        learn_regime_signal_weights(brain)

        # 5. Learn stop loss calibration
        learn_stop_loss_calibration(brain)

        # 6. Track momentum signals
        momentum_signals = calculate_momentum_signals(brain)
        track_momentum_signal(brain, momentum_signals)

        # 7. Learn momentum effectiveness
        learn_momentum_effectiveness(brain)

        # 8. Learn asset regime performance
        learn_asset_regime_performance(brain)

        learning["total_cycles"] += 1
        learning["last_cycle"] = datetime.now().isoformat()

        log(f"Learning cycle #{learning['total_cycles']} complete. "
            f"Closed trades: {len(learning['closed_trades'])}, "
            f"Regime predictions: {len(learning['regime_predictions'])}, "
            f"Momentum outcomes: {len(learning['momentum_outcomes'])}")

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
    regime_preds = len(learning.get("regime_predictions", []))
    validated_preds = len([p for p in learning.get("regime_predictions", []) if p.get("validated")])
    correct_preds = len([p for p in learning.get("regime_predictions", [])
                         if p.get("actual_direction") == "correct"])
    stop_events = len(learning.get("stop_loss_events", []))
    momentum_outcomes = len(learning.get("momentum_outcomes", []))

    print(f"""
 SELF-LEARNING SYSTEM
 ────────────────────────────────────────
 Total Cycles:     {total_cycles:>8}
 Last Cycle:       {str(last_cycle)[:19] if last_cycle else 'Never':>19}
 Open Positions:   {open_positions:>8}
 Closed Trades:    {closed_trades:>8} (90-day window)

 REGIME PREDICTIONS
 ────────────────────────────────────────
 Total Predictions: {regime_preds:>7}
 Validated:         {validated_preds:>7}
 Correct:           {correct_preds:>7}""")
    if validated_preds > 0:
        accuracy = correct_preds / validated_preds * 100
        print(f" Accuracy:          {accuracy:>6.1f}%")

    # Signal weights
    weights = learning.get("regime_signal_weights", {})
    modified_weights = {k: v for k, v in weights.items() if abs(v - 1.0) > 0.01}
    if modified_weights:
        print(f"""
 LEARNED SIGNAL WEIGHTS (modified)
 ────────────────────────────────────────""")
        for sig, w in sorted(modified_weights.items(), key=lambda x: -abs(x[1] - 1.0)):
            direction = "+" if w > 1.0 else ""
            print(f"   {sig:<20} {direction}{(w - 1.0) * 100:>5.1f}%  (weight: {w:.2f})")
    else:
        print(f"\n Signal Weights:    All at default (1.0)")

    # Momentum multipliers
    multipliers = learning.get("learned_multipliers", {})
    defaults = {"strong_buy": 1.4, "buy": 1.2, "neutral": 1.0, "sell": 0.5, "strong_sell": 0.0}
    modified_mult = {k: v for k, v in multipliers.items() if abs(v - defaults.get(k, 1.0)) > 0.001}
    if modified_mult:
        print(f"""
 LEARNED MOMENTUM MULTIPLIERS (modified)
 ────────────────────────────────────────""")
        for sig, m in modified_mult.items():
            print(f"   {sig:<14} {m:.2f}  (default: {defaults.get(sig, '?')})")

    # Stop loss adjustments
    stop_adj = learning.get("learned_stop_adjustments", {})
    if stop_adj:
        print(f"""
 LEARNED STOP LOSS ADJUSTMENTS
 ────────────────────────────────────────""")
        for ticker, adj in sorted(stop_adj.items()):
            direction = "wider" if adj > 0 else "tighter"
            print(f"   {ticker:<8} {adj:>+5.1f}%  ({direction})")
    print(f"""
 Stop Events:       {stop_events:>7}
 Momentum Outcomes: {momentum_outcomes:>7}""")

    # Asset regime performance matrix
    perf = learning.get("asset_regime_performance", {})
    if perf:
        # Find assets with enough data
        notable = {}
        for symbol, regimes in perf.items():
            for regime, stats in regimes.items():
                if stats.get("count", 0) >= 5:
                    notable.setdefault(symbol, {})[regime] = stats

        if notable:
            print(f"""
 ASSET-REGIME PERFORMANCE (5+ trades)
 ────────────────────────────────────────""")
            for symbol in sorted(notable.keys()):
                parts = []
                for regime in ("strong_bull", "bull", "neutral", "bear", "strong_bear"):
                    stats = notable[symbol].get(regime)
                    if stats:
                        parts.append(f"{regime}:{stats['avg_return']:>+5.1f}%({stats['count']})")
                if parts:
                    print(f"   {symbol:<8} {' | '.join(parts)}")


# =============================================================================
# ENHANCED DAILY CHECK
# =============================================================================

def run_daily_check(config: dict):
    """Aggressive day-trading check with frequent rebalancing."""
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

    log("Starting day-trader check (v4.0)...")

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

    # Detect regime with news sentiment (pass brain for learned signal weights)
    regime = detect_market_regime(brain)
    log(f"Market regime detected: {regime['name']} (score: {regime['score']})")

    # Log news sentiment
    news = regime.get("news_sentiment", {})
    log(f"News sentiment: {news.get('signal', 'N/A')} (score: {news.get('score', 0):.2f})")

    # Record regime
    brain["regime_history"].append({
        "date": datetime.now().isoformat(),
        "name": regime["name"],
        "score": regime["score"]
    })
    brain["regime_history"] = brain["regime_history"][-365:]

    # Regime logged for reference (allocations now driven by RSI, not regime)
    brain["confirmed_regime"] = regime["name"]
    log(f"Regime (info only): {regime['name']}")

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

        # Trailing stops disabled — RSI strategy handles risk via cash allocation
        drawdown = ((initial_value - portfolio_value) / initial_value) * 100
        log(f"Risk: Value ${portfolio_value:,.2f} | Floor ${floor_value:,.2f} | Drawdown {drawdown:.1f}%")

    # Liquidate positions in assets no longer in our universe (market hours only)
    market_open = client.is_market_open()
    current_tickers = {info["ticker"] for info in ASSETS.values()}
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

    # FEATURE 7: Correlation check
    current_allocation = {}
    for pos in positions:
        for asset_id, asset_info in ASSETS.items():
            if asset_info["ticker"] == pos["symbol"]:
                current_allocation[asset_id] = float(pos["market_value"]) / portfolio_value if portfolio_value > 0 else 0

    correlation = check_correlation_risk(current_allocation)
    if correlation["risk_level"] == "high":
        log(f"High correlation warning: {correlation['average_correlation']:.2f}")

    # Calculate target allocation (includes Features 2, 3, 6)
    target = calculate_target_allocation(brain, regime, config)

    # DCA: check if a scheduled deposit is due
    dca_amount = get_dca_amount(config, brain)
    if dca_amount > 0:
        log(f"DCA deposit due: ${dca_amount:,.2f} — adding to effective portfolio value")
        portfolio_value += dca_amount
        brain["last_dca_date"] = datetime.now().isoformat()
        brain.setdefault("total_dca_deposited", 0)
        brain["total_dca_deposited"] += dca_amount

    # Check if rebalance needed
    last_regime = brain["regime_history"][-2]["name"] if len(brain["regime_history"]) > 1 else None
    regime_changed = last_regime != regime["name"]

    max_drift = 0
    for asset_id, target_weight in target.items():
        current_weight = current_allocation.get(asset_id, 0)
        drift = abs(target_weight - current_weight)
        max_drift = max(max_drift, drift)

    # SMART REBALANCING
    # - Rebalance every 4+ hours (avoid churning)
    # - 10% drift threshold (wider to reduce trades)
    # - Confirmed regime changes trigger immediate rebalance

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
    regime_shift = regime_changed

    should_rebalance = daily_due or drift_triggered or regime_shift

    if regime_shift:
        log(f"Regime changed: {last_regime} -> {regime['name']} -- triggering rebalance")
    elif drift_triggered:
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
                ticker = ASSETS[asset_id]["ticker"]
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

            for ticker, diff in buys:
                try:
                    client.submit_order(symbol=ticker, notional=diff, side="buy")
                    log(f"BUY ${diff:.2f} of {ticker}")
                except Exception as e:
                    log(f"Trade failed for {ticker}: {e}", "ERROR")

            brain["total_trades"] += 1
            brain["last_rebalance_date"] = datetime.now().isoformat()
            log(f"Rebalance complete. Next check in ~2 hours or on 10% drift.")

    # Run learning cycle before saving
    run_learning_cycle(client, brain, regime)

    # Save state
    save_brain(brain)
    save_portfolio(portfolio)
    log(f"Daily check complete. Portfolio: ${portfolio_value:,.2f}")


def run_weekly_report(config: dict):
    log("Generating day trader report (v4.0)...")

    api_key = config.get("alpaca_api_key")
    api_secret = config.get("alpaca_api_secret")
    paper = config.get("paper_trading", True)

    if not api_key or not api_secret:
        log("Alpaca credentials not configured", "ERROR")
        return

    client = AlpacaClient(api_key, api_secret, paper)
    brain = load_brain()

    report = generate_weekly_report(client, brain, config)
    send_email(config, "📊 RSI Day Trader Report v4.0", report)

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

    # Get current RSI signal
    spy_hist = fetch_yahoo_history("SPY", 30, "1d")
    spy_rsi = calc_rsi(spy_hist, 14) if spy_hist and len(spy_hist) >= 15 else 50.0
    if spy_rsi is None:
        spy_rsi = 50.0
    spy_price = spy_hist[-1]["close"] if spy_hist else 0
    sma20 = sum(h['close'] for h in spy_hist[-20:]) / min(20, len(spy_hist)) if spy_hist and len(spy_hist) >= 5 else spy_price
    uptrend = spy_price > sma20

    if spy_rsi < 25:
        signal = "deep_value"
    elif spy_rsi < 40:
        signal = "buy_dip"
    elif spy_rsi > 75 and not uptrend:
        signal = "sell_high"
    elif spy_rsi > 65 and not uptrend:
        signal = "trim"
    else:
        signal = "hold"

    print(f"""
════════════════════════════════════════════════════════════════
 🤖 RSI DAY-TRADER v4.0 STATUS
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

 RSI STRATEGY
 ────────────────────────────────────────
 Signal:           {signal.upper()}
 SPY RSI:          {spy_rsi:.1f}
 Trend:            {'Uptrend' if uptrend else 'Downtrend'}

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


def show_market_analysis():
    """Show comprehensive market analysis."""
    print("\n Analyzing market... (this may take 15-30 seconds)\n")

    brain = load_brain()
    regime = detect_market_regime(brain)
    analysis = regime.get("analysis", {})

    # Regime header
    regime_emoji = {
        "strong_bull": "🚀",
        "bull": "📈",
        "neutral": "➡️",
        "bear": "📉",
        "strong_bear": "💥"
    }

    print(f"""
════════════════════════════════════════════════════════════════
 📊 COMPREHENSIVE MARKET ANALYSIS
════════════════════════════════════════════════════════════════

 MARKET REGIME: {regime_emoji.get(regime['name'], '?')} {regime['name'].upper().replace('_', ' ')}
 ────────────────────────────────────────
 Score:           {regime['score']:+.0f} (range: -10 to +10)
 Confidence:      {regime['confidence']*100:.0f}%
 Indicators Used: {regime.get('indicators_used', 0)}
 SPY Price:       ${regime.get('spy_price', 0):,.2f}

 SIGNALS DETECTED ({len(regime['signals'])})
 ────────────────────────────────────────""")

    for i, signal in enumerate(regime['signals'], 1):
        # Color code signals
        if any(w in signal.lower() for w in ['bullish', 'above', 'golden', 'strong', 'positive', 'oversold']):
            indicator = "🟢"
        elif any(w in signal.lower() for w in ['bearish', 'below', 'death', 'negative', 'fear', 'overbought']):
            indicator = "🔴"
        else:
            indicator = "🟡"
        print(f"   {indicator} {signal}")

    # MACD
    macd = analysis.get("macd", {})
    if macd:
        print(f"""
 MACD INDICATOR
 ────────────────────────────────────────
 MACD Line:       {macd.get('macd', 0):>+10.2f}
 Signal Line:     {macd.get('signal_line', 0):>+10.2f}
 Histogram:       {macd.get('histogram', 0):>+10.2f}
 Signal:          {macd.get('signal', 'N/A').upper()}""")

    # Bollinger Bands
    bb = analysis.get("bollinger", {})
    if bb:
        print(f"""
 BOLLINGER BANDS
 ────────────────────────────────────────
 Upper Band:      ${bb.get('upper', 0):>10,.2f}
 Middle (SMA20):  ${bb.get('middle', 0):>10,.2f}
 Lower Band:      ${bb.get('lower', 0):>10,.2f}
 Current Price:   ${bb.get('current', 0):>10,.2f}
 Band Position:   {bb.get('position', 0)*100:>10.1f}% (0=lower, 100=upper)
 Bandwidth:       {bb.get('bandwidth', 0)*100:>10.1f}% (volatility)
 Signal:          {bb.get('signal', 'N/A').upper()}""")

    # Volume
    volume = analysis.get("volume", {})
    if volume and volume.get("signal") != "no_data":
        print(f"""
 VOLUME ANALYSIS
 ────────────────────────────────────────
 Avg Volume:      {volume.get('avg_volume', 0):>12,.0f}
 Recent Volume:   {volume.get('recent_volume', 0):>12,.0f}
 Volume Ratio:    {volume.get('ratio', 1):>12.2f}x
 Price Change:    {volume.get('price_change', 0)*100:>+11.1f}%
 Signal:          {volume.get('signal', 'N/A').upper()}""")

    # Yield Curve
    yc = analysis.get("yield_curve", {})
    if yc and yc.get("signal") != "no_data":
        print(f"""
 YIELD CURVE (Treasury ETF Proxy)
 ────────────────────────────────────────
 Long-term (TLT): {yc.get('tlt_change', 0):>+11.1f}% (20d)
 Short-term (SHY):{yc.get('shy_change', 0):>+11.1f}% (20d)
 Curve Signal:    {yc.get('signal', 'N/A').upper()}""")

    # Sector Rotation
    sectors = analysis.get("sector_rotation", {})
    if sectors and sectors.get("signal") != "no_data":
        print(f"""
 SECTOR ROTATION
 ────────────────────────────────────────
 Cyclical Avg:    {sectors.get('cyclical_avg', 0):>+11.1f}%
 Defensive Avg:   {sectors.get('defensive_avg', 0):>+11.1f}%
 Rotation Score:  {sectors.get('rotation_score', 0):>+11.1f}%
 Market Phase:    {sectors.get('phase', 'N/A').upper()}
 Signal:          {sectors.get('signal', 'N/A').upper()}

 Leaders:         {', '.join(sectors.get('leaders', []))}
 Laggards:        {', '.join(sectors.get('laggards', []))}""")

    # Market Breadth
    breadth = analysis.get("market_breadth", {})
    if breadth and breadth.get("signal") != "no_data":
        print(f"""
 MARKET BREADTH
 ────────────────────────────────────────
 Above SMA20:     {breadth.get('above_sma20_pct', 0):>11.0f}%
 Positive Mom:    {breadth.get('positive_momentum_pct', 0):>11.0f}%
 Signal:          {breadth.get('signal', 'N/A').upper()}""")

    # News
    news = analysis.get("news", {})
    if news:
        print(f"""
 NEWS SENTIMENT
 ────────────────────────────────────────
 Sentiment:       {news.get('signal', 'N/A').upper()}
 Score:           {news.get('score', 0):>+11.2f} (-1 to +1)
 Positive words:  {news.get('positive_count', 0):>11}
 Negative words:  {news.get('negative_count', 0):>11}""")

    # Interpretation
    print(f"""
════════════════════════════════════════════════════════════════
 💡 INTERPRETATION
════════════════════════════════════════════════════════════════""")

    if regime['name'] == "strong_bull":
        print("""
 Maximum aggression. All signals aligned bullish.
 - Action: 60% leveraged ETFs (TQQQ/SOXL/UPRO), 30% stocks, 10% crypto
 - Momentum: Overweighting top performers aggressively
 - Risk: 5% trailing stops on leveraged, watch for RSI > 80 reversal
""")
    elif regime['name'] == "bull":
        print("""
 Bullish regime. Leveraged ETFs active with momentum stocks.
 - Action: 40% leveraged, 45% individual stocks, 10% crypto
 - Momentum: Winners overweighted, losers cut hard
 - Risk: Trailing stops active, 5% cash buffer
""")
    elif regime['name'] == "neutral":
        print("""
 Mixed signals. Reducing leverage, favoring individual stocks.
 - Action: 15% leveraged, 60% individual stocks, 20% cash
 - Momentum: Selective positions only, cut weak signals
 - Risk: Higher cash reserve, tight stops, ready for breakout
""")
    elif regime['name'] == "bear":
        print("""
 Bearish regime. Inverse ETFs active, profiting from downturn.
 - Action: 50% inverse (SQQQ/SPXU), 15% stocks, 35% cash
 - Momentum: Only holding strong_buy signals on long side
 - Risk: Watching for oversold bounces and regime reversal
""")
    else:  # strong_bear
        print("""
 Extreme bearish. Maximum inverse position.
 - Action: 70% inverse (SQQQ/SPXU), 0% long, 30% cash
 - Momentum: Fully short the market via inverse ETFs
 - Risk: Tight 5% stops on inverse, watching for capitulation reversal
""")

    print("════════════════════════════════════════════════════════════════\n")


# =============================================================================
# =============================================================================
# PAPER TRADING (RSI buy-low/sell-high strategy)
# =============================================================================

def load_paper_portfolio() -> dict:
    if PAPER_FILE.exists():
        with open(PAPER_FILE) as f:
            return json.load(f)
    return {}


def save_paper_portfolio(paper: dict):
    with open(PAPER_FILE, 'w') as f:
        json.dump(paper, f, indent=2)


def init_paper_portfolio(starting_value: float):
    """Initialize paper portfolio with given starting value."""
    paper = {
        "started": datetime.now().strftime("%Y-%m-%d"),
        "starting_value": starting_value,
        "cash": starting_value,
        "positions": {},
        "trailing_highs": {},
        "history": [],
        "trade_log": [],
    }
    save_paper_portfolio(paper)
    log(f"Paper portfolio initialized with ${starting_value:.2f}")
    return paper


def run_paper_trade(config: dict):
    """Run one paper trading cycle using RSI buy-low/sell-high strategy."""
    paper = load_paper_portfolio()
    if not paper:
        log("Paper portfolio not initialized. Run --paper-init first.", "ERROR")
        return

    # Fetch current prices
    day_prices = {}
    for asset_id, asset_info in ASSETS.items():
        hist = fetch_yahoo_history(asset_info["ticker"], 5, "1d")
        if hist:
            day_prices[asset_id] = hist[-1]['close']

    spy_hist = fetch_yahoo_history("SPY", 30, "1d")
    if not spy_hist or len(spy_hist) < 15:
        log("Paper trade: not enough SPY data", "ERROR")
        return

    # Calculate SPY RSI + trend
    spy_rsi = calc_rsi(spy_hist, 14)
    if spy_rsi is None:
        spy_rsi = 50.0
    sma20 = sum(h['close'] for h in spy_hist[-20:]) / min(20, len(spy_hist))
    spy_price = spy_hist[-1]['close']
    uptrend = spy_price > sma20

    # Determine signal
    if spy_rsi < 25:
        signal = "deep_value"
    elif spy_rsi < 40:
        signal = "buy_dip"
    elif spy_rsi > 75 and not uptrend:
        signal = "sell_high"
    elif spy_rsi > 65 and not uptrend:
        signal = "trim"
    else:
        signal = "hold"

    # Calculate current paper portfolio value
    cash = paper["cash"]
    positions = paper["positions"]
    portfolio_value = cash
    for aid, pos in positions.items():
        if aid in day_prices:
            portfolio_value += pos["shares"] * day_prices[aid]

    # Target allocations
    leveraged_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) > 1]
    inverse_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) < 0]
    broad_keys = [k for k in ASSETS if ASSETS[k].get("sector") == "broad_market"]
    individual_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) == 1 and ASSETS[k]["sector"] not in ("crypto", "broad_market")]
    crypto_keys = [k for k in ASSETS if ASSETS[k]["sector"] == "crypto"]

    if signal == "deep_value":
        lev, broad, ind, inv, cry, csh = 0.50, 0.35, 0.10, 0.00, 0.05, 0.00
    elif signal == "buy_dip":
        lev, broad, ind, inv, cry, csh = 0.25, 0.55, 0.15, 0.00, 0.05, 0.00
    elif signal == "sell_high":
        lev, broad, ind, inv, cry, csh = 0.00, 0.25, 0.00, 0.10, 0.00, 0.65
    elif signal == "trim":
        lev, broad, ind, inv, cry, csh = 0.00, 0.45, 0.05, 0.05, 0.00, 0.45
    else:  # hold
        lev, broad, ind, inv, cry, csh = 0.00, 0.85, 0.10, 0.00, 0.00, 0.05

    # Momentum-weighted allocation within groups
    def momentum_weight(keys, group_pct, top_n=None):
        if not keys or group_pct <= 0:
            return {}
        mom_scores = {}
        for k in keys:
            if k in day_prices:
                hist = fetch_yahoo_history(ASSETS[k]["ticker"], 15, "1d")
                if hist and len(hist) >= 10:
                    ret = (hist[-1]['close'] - hist[-10]['close']) / hist[-10]['close']
                    mom_scores[k] = ret
                else:
                    mom_scores[k] = 0.0
        if not mom_scores:
            return {}
        if top_n and len(mom_scores) > top_n:
            sorted_keys = sorted(mom_scores, key=lambda k: mom_scores[k], reverse=True)
            mom_scores = {k: mom_scores[k] for k in sorted_keys[:top_n]}
        weights = {k: max(v + 1, 0.1) for k, v in mom_scores.items()}
        total_w = sum(weights.values())
        if total_w <= 0:
            return {k: group_pct / len(mom_scores) for k in mom_scores}
        return {k: (weights[k] / total_w) * group_pct for k in mom_scores}

    target = {}
    target.update(momentum_weight(leveraged_keys, lev, top_n=3))
    target.update(momentum_weight(broad_keys, broad))
    target.update(momentum_weight(individual_keys, ind, top_n=3))
    target.update(momentum_weight(inverse_keys, inv))
    target.update(momentum_weight(crypto_keys, cry))

    # Scale to (1 - cash_reserve)
    total_t = sum(target.values())
    if total_t > 0:
        target = {k: v / total_t * (1 - csh) for k, v in target.items()}

    # Per-asset RSI adjustment (buy low / sell high)
    for aid in list(target.keys()):
        hist = fetch_yahoo_history(ASSETS[aid]["ticker"], 25, "1d")
        if hist and len(hist) >= 15:
            rsi = calc_rsi(hist, 14)
            if rsi is not None:
                if rsi > 75:
                    target[aid] *= 0.3
                elif rsi > 65:
                    target[aid] *= 0.6
                elif rsi < 25:
                    target[aid] *= 1.8
                elif rsi < 35:
                    target[aid] *= 1.4

    # Re-normalize
    total_t = sum(target.values())
    max_invested = 1 - csh
    if total_t > max_invested:
        target = {k: v / total_t * max_invested for k, v in target.items()}

    # Ensure every asset has a target (missing = 0, so held positions get sold)
    for aid in ASSETS:
        if aid not in target:
            target[aid] = 0.0

    # Execute paper trades — sells first to free cash, then buys
    day_trades = 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    min_trade = portfolio_value * 0.001

    paper_sells, paper_buys = [], []
    for aid, target_weight in target.items():
        if aid not in day_prices:
            continue
        price = day_prices[aid]
        target_value = portfolio_value * target_weight
        current_value = positions[aid]["shares"] * price if aid in positions else 0
        diff = target_value - current_value
        if abs(diff) < min_trade:
            continue
        if diff < 0 and aid in positions:
            paper_sells.append((aid, diff, price))
        elif diff > 0:
            paper_buys.append((aid, diff, price))

    for aid, diff, price in paper_sells:
        shares_to_sell = min(abs(diff) / price, positions[aid]["shares"])
        proceeds = shares_to_sell * price
        positions[aid]["shares"] -= shares_to_sell
        cash += proceeds
        if positions[aid]["shares"] < 0.001:
            del positions[aid]
        day_trades += 1
        paper["trade_log"].append(f"{now_str}  SELL {ASSETS[aid]['name']:<18} ${abs(diff):.2f}  @ ${price:.2f}  [{signal}]")

    for aid, diff, price in paper_buys:
        if cash < diff:
            diff = cash  # buy as much as cash allows
        if diff < min_trade:
            continue
        shares = diff / price
        if aid in positions:
            old_shares = positions[aid]["shares"]
            old_cost = positions[aid]["avg_price"] * old_shares
            positions[aid]["shares"] += shares
            positions[aid]["avg_price"] = (old_cost + diff) / positions[aid]["shares"]
        else:
            positions[aid] = {"shares": shares, "avg_price": price}
        cash -= diff
        day_trades += 1
        paper["trade_log"].append(f"{now_str}  BUY  {ASSETS[aid]['name']:<18} ${diff:.2f}  @ ${price:.2f}  [{signal}]")

    # Keep only last 200 trade log entries
    paper["trade_log"] = paper["trade_log"][-200:]

    # Recalculate final value
    portfolio_value = cash
    for aid, pos in positions.items():
        if aid in day_prices:
            portfolio_value += pos["shares"] * day_prices[aid]

    paper["cash"] = cash
    paper["positions"] = positions
    paper["history"].append({
        "date": now_str,
        "value": round(portfolio_value, 2),
        "signal": signal,
        "spy_rsi": round(spy_rsi, 1),
        "trades": day_trades,
    })
    # Keep last 2000 history entries
    paper["history"] = paper["history"][-2000:]
    save_paper_portfolio(paper)
    log(f"Paper trade: ${portfolio_value:.2f} | signal={signal} | RSI={spy_rsi:.0f} | trades={day_trades}")


def show_paper_status(config: dict):
    """Show paper portfolio status vs live portfolio."""
    paper = load_paper_portfolio()
    if not paper:
        print("\n Paper portfolio not initialized. Run with --paper-init to start.\n")
        return

    # Get live portfolio value
    api_key = config.get("alpaca_api_key")
    api_secret = config.get("alpaca_api_secret")
    is_paper = config.get("paper_trading", True)
    live_value = 0
    if api_key and api_secret:
        try:
            client = AlpacaClient(api_key, api_secret, is_paper)
            account = client.get_account()
            live_value = float(account.get("equity", 0))
        except:
            live_value = 0

    # Calculate paper portfolio value with current prices
    day_prices = {}
    for asset_id, asset_info in ASSETS.items():
        hist = fetch_yahoo_history(asset_info["ticker"], 5, "1d")
        if hist:
            day_prices[asset_id] = hist[-1]['close']

    paper_cash = paper["cash"]
    paper_value = paper_cash
    positions = paper["positions"]
    for aid, pos in positions.items():
        if aid in day_prices:
            paper_value += pos["shares"] * day_prices[aid]

    starting = paper["starting_value"]
    paper_return = ((paper_value - starting) / starting) * 100
    live_return = ((live_value - starting) / starting) * 100 if live_value > 0 else 0

    # SPY return since paper start
    spy_hist = fetch_yahoo_history("SPY", 60, "1d")
    spy_return = 0
    if spy_hist:
        start_date = paper["started"]
        spy_start_price = None
        for h in spy_hist:
            if h['date'][:10] >= start_date:
                spy_start_price = h['close']
                break
        if spy_start_price:
            spy_return = ((spy_hist[-1]['close'] - spy_start_price) / spy_start_price) * 100

    history = paper.get("history", [])
    last_signal = history[-1]["signal"] if history else "n/a"
    last_rsi = history[-1]["spy_rsi"] if history else 0

    print(f"""
════════════════════════════════════════════════════════════════
 📊 PAPER vs LIVE COMPARISON
════════════════════════════════════════════════════════════════
 Started:          {paper['started']}
 Starting Value:   ${starting:>10,.2f}

 CURRENT VALUES
 ────────────────────────────────────────
 Paper (RSI):      ${paper_value:>10,.2f}   ({paper_return:>+.2f}%)
 Live  (RSI):      ${live_value:>10,.2f}   ({live_return:>+.2f}%)
 S&P 500:          {'':>10}   ({spy_return:>+.2f}%)
 ────────────────────────────────────────
 Paper vs Live:    {paper_return - live_return:>+10.2f}%
 Paper vs SPY:     {paper_return - spy_return:>+10.2f}%
 Live vs SPY:      {live_return - spy_return:>+10.2f}%

 PAPER STRATEGY STATE
 ────────────────────────────────────────
 Signal:           {last_signal}
 SPY RSI:          {last_rsi:.0f}
 Cash:             ${paper_cash:>10,.2f}  ({paper_cash/paper_value*100:.0f}%)""")

    if positions:
        print(f"""
 PAPER HOLDINGS
 ────────────────────────────────────────""")
        for aid, pos in sorted(positions.items(), key=lambda x: -x[1]["shares"] * day_prices.get(x[0], 0)):
            if aid in day_prices:
                val = pos["shares"] * day_prices[aid]
                pct = val / paper_value * 100
                pl = ((day_prices[aid] - pos["avg_price"]) / pos["avg_price"]) * 100
                print(f"   {ASSETS[aid]['name']:<20} ${val:>8,.2f}  ({pct:>4.1f}%)  {pl:>+6.1f}%")

    # Recent trades
    recent_trades = paper.get("trade_log", [])[-10:]
    if recent_trades:
        print(f"""
 RECENT PAPER TRADES
 ────────────────────────────────────────""")
        for t in recent_trades:
            print(f"   {t}")

    print(f"""
════════════════════════════════════════════════════════════════
""")


# =============================================================================
# STRATEGY COMPARISON (RSI vs Regime vs SPY)
# =============================================================================

def run_comparison(config: dict, days: int = 365):
    """Run RSI and Regime strategies side-by-side on historical data."""
    print(f"""
════════════════════════════════════════════════════════════════
 🔀 STRATEGY COMPARISON — {days} DAYS
    RSI (Paper) vs Regime (Live) vs S&P 500
════════════════════════════════════════════════════════════════
 Fetching historical data...
""")

    histories = {}
    for asset_id, asset_info in ASSETS.items():
        hist = fetch_yahoo_history(asset_info["ticker"], days + 30, "1d")
        if hist:
            histories[asset_id] = hist
    spy_hist = fetch_yahoo_history("SPY", days + 30, "1d")
    vix_hist = fetch_yahoo_history("^VIX", days + 30, "1d")

    if not spy_hist or len(spy_hist) < 30:
        print("\n Failed to fetch enough SPY data.")
        return

    print(f"   Loaded {len(histories)} assets + SPY ({len(spy_hist)} bars) + VIX")

    trading_days = spy_hist
    starting_cash = 100.0
    spy_start = trading_days[0]['close']

    # --- RSI strategy state ---
    r_cash, r_pos, r_history = starting_cash, {}, []

    # --- Regime strategy state ---
    g_cash, g_pos, g_stops, g_entry = starting_cash, {}, {}, {}
    g_stopped_until = {}
    g_brain = {"regime_history": [], "confirmed_regime": "neutral"}

    leveraged_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) > 1]
    inverse_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) < 0]
    broad_keys = [k for k in ASSETS if ASSETS[k].get("sector") == "broad_market"]
    individual_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) == 1 and ASSETS[k]["sector"] not in ("crypto", "broad_market")]
    crypto_keys = [k for k in ASSETS if ASSETS[k]["sector"] == "crypto"]

    def momentum_weight(keys, group_pct, day_prices, histories, date_str, top_n=None):
        if not keys or group_pct <= 0:
            return {}
        mom_scores = {}
        for k in keys:
            if k in histories and k in day_prices:
                hist = [h for h in histories[k] if h['date'][:10] <= date_str]
                if len(hist) >= 10:
                    ret = (hist[-1]['close'] - hist[-10]['close']) / hist[-10]['close'] if hist[-10]['close'] > 0 else 0
                    mom_scores[k] = ret
                else:
                    mom_scores[k] = 0.0
        if not mom_scores:
            return {}
        if top_n and len(mom_scores) > top_n:
            sorted_keys = sorted(mom_scores, key=lambda k: mom_scores[k], reverse=True)
            mom_scores = {k: mom_scores[k] for k in sorted_keys[:top_n]}
        weights = {k: max(v + 1, 0.1) for k, v in mom_scores.items()}
        total_w = sum(weights.values())
        if total_w <= 0:
            return {k: group_pct / len(mom_scores) for k in mom_scores}
        return {k: (weights[k] / total_w) * group_pct for k in mom_scores}

    def execute_trades(cash, positions, target, portfolio_value, day_prices):
        trades = 0
        min_trade = portfolio_value * 0.001  # 0.1% of portfolio
        for aid, tw in target.items():
            if aid not in day_prices:
                continue
            price = day_prices[aid]
            target_val = portfolio_value * tw
            current_val = positions[aid]["shares"] * price if aid in positions else 0
            diff = target_val - current_val
            if abs(diff) < min_trade:
                continue
            if diff > 0 and cash >= diff:
                shares = diff / price
                if aid in positions:
                    old_s = positions[aid]["shares"]
                    old_c = positions[aid]["avg_price"] * old_s
                    positions[aid]["shares"] += shares
                    positions[aid]["avg_price"] = (old_c + diff) / positions[aid]["shares"]
                else:
                    positions[aid] = {"shares": shares, "avg_price": price}
                cash -= diff
                trades += 1
            elif diff < 0 and aid in positions:
                sell_s = min(abs(diff) / price, positions[aid]["shares"])
                cash += sell_s * price
                positions[aid]["shares"] -= sell_s
                if positions[aid]["shares"] < 0.001:
                    del positions[aid]
                trades += 1
        return cash, trades

    def calc_value(cash, positions, day_prices):
        v = cash
        for aid, pos in positions.items():
            if aid in day_prices:
                v += pos["shares"] * day_prices[aid]
        return v

    print(f"\n Starting capital: ${starting_cash:,.2f}")
    print(f" Simulating {len(trading_days)} trading days (~{days} calendar days)...\n")
    print(f" {'DATE':<12} {'RSI':>10} {'REGIME':>10} {'SPY':>10} {'RSI α':>8} {'REG α':>8}")
    print(f" {'─'*12} {'─'*10} {'─'*10} {'─'*10} {'─'*8} {'─'*8}")

    for day_idx, day in enumerate(trading_days):
        date_str = day['date'][:10]
        spy_price = day['close']

        day_prices = {}
        for asset_id in histories:
            for h in histories[asset_id]:
                if h['date'][:10] == date_str:
                    day_prices[asset_id] = h['close']
                    break
            if asset_id not in day_prices:
                for h in reversed(histories[asset_id]):
                    if h['date'][:10] <= date_str:
                        day_prices[asset_id] = h['close']
                        break

        spy_slice = [h for h in spy_hist if h['date'][:10] <= date_str][-30:]
        spy_rsi = calc_rsi(spy_slice, 14) if len(spy_slice) >= 15 else 50.0
        if spy_rsi is None:
            spy_rsi = 50.0
        sma20 = sum(h['close'] for h in spy_slice[-20:]) / 20 if len(spy_slice) >= 20 else spy_price
        uptrend = spy_price > sma20

        # ========== RSI STRATEGY ==========
        if spy_rsi < 25:
            r_signal = "deep_value"
        elif spy_rsi < 40:
            r_signal = "buy_dip"
        elif spy_rsi > 75 and not uptrend:
            r_signal = "sell_high"
        elif spy_rsi > 65 and not uptrend:
            r_signal = "trim"
        else:
            r_signal = "hold"

        if r_signal == "deep_value":
            lev, broad, ind, inv, cry, csh = 0.50, 0.35, 0.10, 0.00, 0.05, 0.00
        elif r_signal == "buy_dip":
            lev, broad, ind, inv, cry, csh = 0.25, 0.55, 0.15, 0.00, 0.05, 0.00
        elif r_signal == "sell_high":
            lev, broad, ind, inv, cry, csh = 0.00, 0.25, 0.00, 0.10, 0.00, 0.65
        elif r_signal == "trim":
            lev, broad, ind, inv, cry, csh = 0.00, 0.45, 0.05, 0.05, 0.00, 0.45
        else:
            lev, broad, ind, inv, cry, csh = 0.00, 0.85, 0.10, 0.00, 0.00, 0.05

        r_target = {}
        r_target.update(momentum_weight(leveraged_keys, lev, day_prices, histories, date_str, top_n=3))
        r_target.update(momentum_weight(broad_keys, broad, day_prices, histories, date_str))
        r_target.update(momentum_weight(individual_keys, ind, day_prices, histories, date_str, top_n=3))
        r_target.update(momentum_weight(inverse_keys, inv, day_prices, histories, date_str))
        r_target.update(momentum_weight(crypto_keys, cry, day_prices, histories, date_str))
        total_t = sum(r_target.values())
        if total_t > 0:
            r_target = {k: v / total_t * (1 - csh) for k, v in r_target.items()}

        # Per-asset RSI adjustment
        for aid in list(r_target.keys()):
            if aid in histories:
                ahist = [h for h in histories[aid] if h['date'][:10] <= date_str]
                arsi = calc_rsi(ahist, 14) if len(ahist) >= 15 else None
                if arsi is not None:
                    if arsi > 75: r_target[aid] *= 0.3
                    elif arsi > 65: r_target[aid] *= 0.6
                    elif arsi < 25: r_target[aid] *= 1.8
                    elif arsi < 35: r_target[aid] *= 1.4
        total_t = sum(r_target.values())
        if total_t > (1 - csh):
            r_target = {k: v / total_t * (1 - csh) for k, v in r_target.items()}

        r_val = calc_value(r_cash, r_pos, day_prices)
        r_cash, _ = execute_trades(r_cash, r_pos, r_target, r_val, day_prices)

        # ========== REGIME STRATEGY (with trailing stops) ==========
        # Regime scoring
        if len(spy_slice) >= 20:
            sma10 = sum(h['close'] for h in spy_slice[-10:]) / 10
            sma20_g = sum(h['close'] for h in spy_slice[-20:]) / 20
            g_score = 0
            if sma10 > sma20_g: g_score += 2
            else: g_score -= 2
            if spy_price > sma10: g_score += 1
            else: g_score -= 1
            if len(spy_slice) >= 10:
                mom = (spy_slice[-1]['close'] - spy_slice[-10]['close']) / spy_slice[-10]['close']
                if mom > 0.02: g_score += 2
                elif mom > 0: g_score += 1
                elif mom > -0.02: g_score -= 1
                else: g_score -= 2
            if len(spy_slice) >= 15:
                rsi_val = calc_rsi(spy_slice, 14)
                if rsi_val and rsi_val > 70: g_score -= 1
                elif rsi_val and rsi_val < 30: g_score += 1
            if vix_hist:
                for vh in vix_hist:
                    if vh['date'][:10] == date_str:
                        vd = vh['close']
                        if vd > 30: g_score -= 2
                        elif vd > 25: g_score -= 1
                        elif vd < 15: g_score += 1
                        break
            if g_score >= 6: g_regime_raw = "strong_bull"
            elif g_score >= 3: g_regime_raw = "bull"
            elif g_score >= -2: g_regime_raw = "neutral"
            elif g_score >= -5: g_regime_raw = "bear"
            else: g_regime_raw = "strong_bear"
        else:
            g_regime_raw = "neutral"

        g_brain["regime_history"].append({"name": g_regime_raw})
        rh = g_brain["regime_history"]
        if len(rh) >= 5 and all(rh[-(i+1)]["name"] == rh[-1]["name"] for i in range(5)):
            g_brain["confirmed_regime"] = rh[-1]["name"]
        g_regime = g_brain["confirmed_regime"]

        # Trailing stops
        for aid in list(g_pos.keys()):
            if aid not in day_prices: continue
            price = day_prices[aid]
            if ASSETS[aid].get("leverage", 1) < 0: continue
            stop_pct = ASSETS[aid].get("trailing_stop_pct", 10.0) / 100.0
            if aid not in g_stops: g_stops[aid] = price
            elif price > g_stops[aid]: g_stops[aid] = price
            if price <= g_stops[aid] * (1 - stop_pct):
                g_cash += g_pos[aid]["shares"] * price
                del g_pos[aid]
                if aid in g_stops: del g_stops[aid]
                g_stopped_until[aid] = day_idx + 15

        # Regime allocations
        if g_regime == "strong_bull":
            lev, broad, ind, inv, cry, csh = 0.30, 0.35, 0.25, 0.00, 0.05, 0.05
        elif g_regime == "bull":
            lev, broad, ind, inv, cry, csh = 0.15, 0.45, 0.25, 0.00, 0.05, 0.05
        elif g_regime == "neutral":
            lev, broad, ind, inv, cry, csh = 0.00, 0.55, 0.30, 0.00, 0.05, 0.10
        elif g_regime == "bear":
            lev, broad, ind, inv, cry, csh = 0.00, 0.15, 0.05, 0.30, 0.00, 0.50
        else:
            lev, broad, ind, inv, cry, csh = 0.00, 0.00, 0.00, 0.40, 0.00, 0.60

        act_lev = [k for k in leveraged_keys if k not in g_stopped_until or day_idx >= g_stopped_until[k]]
        act_ind = [k for k in individual_keys if k not in g_stopped_until or day_idx >= g_stopped_until[k]]
        act_inv = [k for k in inverse_keys if k not in g_stopped_until or day_idx >= g_stopped_until[k]]
        act_cry = [k for k in crypto_keys if k not in g_stopped_until or day_idx >= g_stopped_until[k]]

        g_target = {}
        g_target.update(momentum_weight(act_lev, lev, day_prices, histories, date_str, top_n=3))
        g_target.update(momentum_weight(broad_keys, broad, day_prices, histories, date_str))
        g_target.update(momentum_weight(act_ind, ind, day_prices, histories, date_str, top_n=3))
        g_target.update(momentum_weight(act_inv, inv, day_prices, histories, date_str))
        g_target.update(momentum_weight(act_cry, cry, day_prices, histories, date_str))
        total_t = sum(g_target.values())
        if total_t > 0:
            g_target = {k: v / total_t * (1 - csh) for k, v in g_target.items()}

        g_val = calc_value(g_cash, g_pos, day_prices)
        if day_idx % 15 == 0 or (len(g_brain["regime_history"]) > 1 and g_brain["regime_history"][-2]["name"] != g_regime):
            g_cash, _ = execute_trades(g_cash, g_pos, g_target, g_val, day_prices)

        # Track values
        r_val = calc_value(r_cash, r_pos, day_prices)
        g_val = calc_value(g_cash, g_pos, day_prices)
        spy_ret = ((spy_price - spy_start) / spy_start) * 100
        r_ret = ((r_val - starting_cash) / starting_cash) * 100
        g_ret = ((g_val - starting_cash) / starting_cash) * 100

        r_history.append({"date": date_str, "rsi": r_val, "regime": g_val, "spy_ret": spy_ret, "r_ret": r_ret, "g_ret": g_ret})

        if day_idx % 10 == 0 or day_idx == len(trading_days) - 1:
            r_alpha = r_ret - spy_ret
            g_alpha = g_ret - spy_ret
            print(f" {date_str:<12} {r_ret:>+9.1f}% {g_ret:>+9.1f}% {spy_ret:>+9.1f}% {r_alpha:>+7.1f}% {g_alpha:>+7.1f}%")

    # Max drawdowns
    def calc_dd(history, key):
        peak = starting_cash
        max_dd = 0
        for h in history:
            val = h[key]
            if val > peak: peak = val
            dd = ((peak - val) / peak) * 100
            if dd > max_dd: max_dd = dd
        return max_dd

    r_dd = calc_dd(r_history, "rsi")
    g_dd = calc_dd(r_history, "regime")

    final = r_history[-1]
    print(f"""
════════════════════════════════════════════════════════════════
 📊 STRATEGY COMPARISON — {days} DAYS
════════════════════════════════════════════════════════════════

                    {'RSI (Paper)':>14} {'Regime (Live)':>14} {'S&P 500':>14}
 ───────────────── ────────────── ────────────── ──────────────
 Final Value:      ${r_history[-1]['rsi']:>13,.2f} ${r_history[-1]['regime']:>13,.2f} {'':>14}
 Total Return:     {final['r_ret']:>+13.2f}% {final['g_ret']:>+13.2f}% {final['spy_ret']:>+13.2f}%
 Alpha vs SPY:     {final['r_ret']-final['spy_ret']:>+13.2f}% {final['g_ret']-final['spy_ret']:>+13.2f}% {'0.00':>13}%
 Max Drawdown:     {r_dd:>13.2f}% {g_dd:>13.2f}% {'':>14}

 WINNER: {'RSI (Paper) ✅' if final['r_ret'] > final['g_ret'] else 'Regime (Live) ✅'}  by {abs(final['r_ret'] - final['g_ret']):.2f}%
 {'Both beat SPY ✅' if final['r_ret'] > final['spy_ret'] and final['g_ret'] > final['spy_ret'] else 'RSI beats SPY ✅' if final['r_ret'] > final['spy_ret'] else 'Regime beats SPY ✅' if final['g_ret'] > final['spy_ret'] else 'Both trail SPY ❌'}

════════════════════════════════════════════════════════════════
""")


# BACKTEST SIMULATION
# =============================================================================

def run_backtest(config: dict, days: int = 90):
    """Simulate the day-trading strategy over historical data."""
    import time as _time

    print(f"""
════════════════════════════════════════════════════════════════
 🔄 BACKTEST SIMULATION — {days} DAYS
════════════════════════════════════════════════════════════════
 Fetching historical data for all assets...
""")

    # Fetch daily history for all assets + SPY + VIX
    histories = {}
    for asset_id, asset_info in ASSETS.items():
        ticker = asset_info["ticker"]
        hist = fetch_yahoo_history(ticker, days + 30, "1d")
        if hist:
            histories[asset_id] = hist
            print(f"   ✓ {asset_info['name']:<20} {len(hist)} bars")
        else:
            print(f"   ✗ {asset_info['name']:<20} FAILED")

    spy_hist = fetch_yahoo_history("SPY", days + 30, "1d")
    vix_hist = fetch_yahoo_history("^VIX", days + 30, "1d")

    if not spy_hist or len(spy_hist) < 30:
        print("\n Failed to fetch enough SPY data for backtest.")
        return

    print(f"   ✓ {'SPY (benchmark)':<20} {len(spy_hist)} bars")
    if vix_hist:
        print(f"   ✓ {'VIX':<20} {len(vix_hist)} bars")

    # Determine trading days (use SPY dates — excludes weekends/holidays)
    trading_days = spy_hist

    # Simulation state
    starting_cash = 100.0
    cash = starting_cash
    positions = {}  # asset_id -> {"shares": float, "avg_price": float}
    trailing_highs = {}  # asset_id -> highest price since entry
    entry_day = {}  # asset_id -> day_idx when position was entered (for stop cooldown)
    stopped_until = {}  # asset_id -> day_idx when stop cooldown expires (don't rebuy)
    portfolio_history = []
    trade_log = []
    regime_log = []
    total_trades = 0

    # Brain for allocation
    sim_brain = {
        "base_allocation": DEFAULT_ALLOCATION.copy(),
        "regime_history": [],
    }

    actual_days = len(trading_days)
    print(f"\n Starting capital: ${starting_cash:,.2f}")
    print(f" Simulating {actual_days} trading days (~{days} calendar days)...\n")
    print(f" {'DATE':<12} {'REGIME':<12} {'VALUE':>12} {'RETURN':>8} {'SPY':>8} {'ALPHA':>8} {'TRADES':>7}")
    print(f" {'─'*12} {'─'*12} {'─'*12} {'─'*8} {'─'*8} {'─'*8} {'─'*7}")

    spy_start = trading_days[0]['close']

    for day_idx, day in enumerate(trading_days):
        date_str = day['date'][:10]
        spy_price = day['close']

        # Get prices for this day
        day_prices = {}
        for asset_id in histories:
            hist = histories[asset_id]
            # Find matching date
            for h in hist:
                if h['date'][:10] == date_str:
                    day_prices[asset_id] = h['close']
                    break
            # If no exact match, use latest available before this date
            if asset_id not in day_prices:
                for h in reversed(hist):
                    if h['date'][:10] <= date_str:
                        day_prices[asset_id] = h['close']
                        break

        # Calculate portfolio value
        portfolio_value = cash
        for asset_id, pos in positions.items():
            if asset_id in day_prices:
                portfolio_value += pos["shares"] * day_prices[asset_id]

        # Buy low / sell high: SPY RSI + trend
        spy_slice = [h for h in spy_hist if h['date'][:10] <= date_str][-25:]
        spy_rsi = calc_rsi(spy_slice, 14) if len(spy_slice) >= 15 else 50.0
        if spy_rsi is None:
            spy_rsi = 50.0
        sma20 = sum(h['close'] for h in spy_slice[-20:]) / 20 if len(spy_slice) >= 20 else spy_price
        uptrend = spy_price > sma20
        score = spy_rsi

        if spy_rsi < 25:
            regime_name = "deep_value"
        elif spy_rsi < 40:
            regime_name = "buy_dip"
        elif spy_rsi > 75 and not uptrend:
            regime_name = "sell_high"
        elif spy_rsi > 65 and not uptrend:
            regime_name = "trim"
        else:
            regime_name = "hold"

        sim_brain["regime_history"].append({"date": date_str, "name": regime_name, "score": score})

        day_trades = 0

        # Rebalance daily
        if True:
            leveraged_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) > 1]
            inverse_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) < 0]
            broad_keys = [k for k in ASSETS if ASSETS[k].get("sector") == "broad_market"]
            individual_keys = [k for k in ASSETS if ASSETS[k].get("leverage", 1) == 1 and ASSETS[k]["sector"] not in ("crypto", "broad_market")]
            crypto_keys = [k for k in ASSETS if ASSETS[k]["sector"] == "crypto"]

            # Buy low: RSI low → leverage up. Sell high: RSI high + downtrend → cash.
            # Default: heavy SPY to track the benchmark, slight individual tilt for alpha.
            if regime_name == "deep_value":
                lev, broad, ind, inv, cry, csh = 0.50, 0.35, 0.10, 0.00, 0.05, 0.00
            elif regime_name == "buy_dip":
                lev, broad, ind, inv, cry, csh = 0.25, 0.55, 0.15, 0.00, 0.05, 0.00
            elif regime_name == "sell_high":
                lev, broad, ind, inv, cry, csh = 0.00, 0.25, 0.00, 0.10, 0.00, 0.65
            elif regime_name == "trim":
                lev, broad, ind, inv, cry, csh = 0.00, 0.45, 0.05, 0.05, 0.00, 0.45
            else:  # hold — track SPY closely
                lev, broad, ind, inv, cry, csh = 0.00, 0.85, 0.10, 0.00, 0.00, 0.05

            # Momentum-weighted allocation: pick top N assets by momentum, weight by strength
            def momentum_weight(keys, group_pct, day_prices, histories, date_str, top_n=None):
                """Weight assets by 10-day momentum. If top_n set, only include top N performers."""
                if not keys or group_pct <= 0:
                    return {k: 0 for k in keys}
                # Calculate 10-day return for each asset
                mom_scores = {}
                for k in keys:
                    if k in histories and k in day_prices:
                        hist = [h for h in histories[k] if h['date'][:10] <= date_str]
                        if len(hist) >= 10:
                            old_price = hist[-10]['close']
                            cur_price = day_prices[k]
                            ret = (cur_price - old_price) / old_price if old_price > 0 else 0
                            mom_scores[k] = ret
                        else:
                            mom_scores[k] = 0.0
                    else:
                        mom_scores[k] = 0.0
                # If top_n, only keep the N assets with highest momentum
                if top_n and len(mom_scores) > top_n:
                    sorted_keys = sorted(mom_scores, key=lambda k: mom_scores[k], reverse=True)
                    mom_scores = {k: mom_scores[k] for k in sorted_keys[:top_n]}
                # Shift to positive weights
                weights = {k: max(v + 1, 0.1) for k, v in mom_scores.items()}
                total_w = sum(weights.values())
                if total_w <= 0:
                    return {k: group_pct / len(mom_scores) for k in mom_scores}
                return {k: (weights[k] / total_w) * group_pct for k in mom_scores}

            target = {}
            target.update(momentum_weight(leveraged_keys, lev, day_prices, histories, date_str, top_n=3))
            target.update(momentum_weight(broad_keys, broad, day_prices, histories, date_str))
            target.update(momentum_weight(individual_keys, ind, day_prices, histories, date_str, top_n=3))
            target.update(momentum_weight(inverse_keys, inv, day_prices, histories, date_str))
            target.update(momentum_weight(crypto_keys, cry, day_prices, histories, date_str))

            # Scale to (1 - cash)
            total_t = sum(target.values())
            if total_t > 0:
                target = {k: v / total_t * (1 - csh) for k, v in target.items()}

            # RSI-based buy low / sell high adjustment
            for aid in list(target.keys()):
                if aid in histories:
                    asset_hist = [h for h in histories[aid] if h['date'][:10] <= date_str]
                    rsi = calc_rsi(asset_hist, 14) if len(asset_hist) >= 15 else None
                    if rsi is not None:
                        if rsi > 75:
                            target[aid] *= 0.3   # overbought — take profits
                            trade_log.append(f"   {date_str}  RSI TRIM  {ASSETS[aid]['name']:<18} RSI={rsi:.0f} → weight x0.3")
                        elif rsi > 65:
                            target[aid] *= 0.6   # getting hot — reduce
                        elif rsi < 25:
                            target[aid] *= 1.8   # oversold — load up
                            trade_log.append(f"   {date_str}  RSI BUY   {ASSETS[aid]['name']:<18} RSI={rsi:.0f} → weight x1.8")
                        elif rsi < 35:
                            target[aid] *= 1.4   # cheap — accumulate

            # Re-normalize so total target doesn't exceed (1 - cash)
            total_t = sum(target.values())
            max_invested = 1 - csh
            if total_t > max_invested:
                target = {k: v / total_t * max_invested for k, v in target.items()}

            # Recalculate current portfolio value
            portfolio_value = cash
            for asset_id, pos in positions.items():
                if asset_id in day_prices:
                    portfolio_value += pos["shares"] * day_prices[asset_id]

            # Execute trades
            for asset_id, target_weight in target.items():
                if asset_id not in day_prices:
                    continue
                price = day_prices[asset_id]
                target_value = portfolio_value * target_weight
                current_value = positions.get(asset_id, {"shares": 0})["shares"] * price if asset_id in positions else 0
                diff = target_value - current_value

                if abs(diff) < portfolio_value * 0.001:
                    continue

                if diff > 0 and cash >= diff:
                    # Buy
                    shares = diff / price
                    if asset_id in positions:
                        old_shares = positions[asset_id]["shares"]
                        old_cost = positions[asset_id]["avg_price"] * old_shares
                        positions[asset_id]["shares"] += shares
                        positions[asset_id]["avg_price"] = (old_cost + diff) / positions[asset_id]["shares"]
                    else:
                        positions[asset_id] = {"shares": shares, "avg_price": price}
                        entry_day[asset_id] = day_idx  # track entry for stop cooldown
                    cash -= diff
                    trailing_highs[asset_id] = price
                    day_trades += 1
                elif diff < 0 and asset_id in positions:
                    # Sell
                    shares_to_sell = min(abs(diff) / price, positions[asset_id]["shares"])
                    proceeds = shares_to_sell * price
                    positions[asset_id]["shares"] -= shares_to_sell
                    cash += proceeds
                    if positions[asset_id]["shares"] < 0.001:
                        del positions[asset_id]
                        if asset_id in trailing_highs:
                            del trailing_highs[asset_id]
                        if asset_id in entry_day:
                            del entry_day[asset_id]
                    day_trades += 1

        total_trades += day_trades

        # Recalculate final portfolio value for the day
        portfolio_value = cash
        for asset_id, pos in positions.items():
            if asset_id in day_prices:
                portfolio_value += pos["shares"] * day_prices[asset_id]

        portfolio_return = ((portfolio_value - starting_cash) / starting_cash) * 100
        spy_return = ((spy_price - spy_start) / spy_start) * 100
        alpha = portfolio_return - spy_return

        portfolio_history.append({
            "date": date_str,
            "value": portfolio_value,
            "return": portfolio_return,
            "spy_return": spy_return,
            "alpha": alpha,
            "regime": regime_name,
            "trades": day_trades
        })

        # Print weekly summary (every 5 days)
        if day_idx % 5 == 0 or day_idx == len(trading_days) - 1:
            regime_icon = {"deep_value": "🟢", "buy_dip": "📈", "hold": "➡️ ", "trim": "📉", "sell_high": "🔴"}.get(regime_name, "?")
            alpha_color = f"+{alpha:.1f}" if alpha >= 0 else f"{alpha:.1f}"
            print(f" {date_str:<12} {regime_icon}{regime_name:<10} ${portfolio_value:>11,.2f} {portfolio_return:>+7.1f}% {spy_return:>+7.1f}% {alpha_color:>7}% {day_trades:>5}")

    # Final summary
    final = portfolio_history[-1]
    best_day = max(portfolio_history, key=lambda x: x["return"])
    worst_day = min(portfolio_history, key=lambda x: x["return"])

    # Max drawdown
    peak = starting_cash
    max_dd = 0
    for ph in portfolio_history:
        if ph["value"] > peak:
            peak = ph["value"]
        dd = ((peak - ph["value"]) / peak) * 100
        if dd > max_dd:
            max_dd = dd

    # Count regime days
    regime_counts = {}
    for ph in portfolio_history:
        r = ph["regime"]
        regime_counts[r] = regime_counts.get(r, 0) + 1

    # Win rate (days with positive return)
    positive_days = sum(1 for i in range(1, len(portfolio_history))
                        if portfolio_history[i]["value"] > portfolio_history[i-1]["value"])
    total_days = len(portfolio_history) - 1

    print(f"""
════════════════════════════════════════════════════════════════
 📊 BACKTEST RESULTS — {days} DAYS
════════════════════════════════════════════════════════════════

 PERFORMANCE
 ────────────────────────────────────────
 Starting Capital: ${starting_cash:>12,.2f}
 Final Value:      ${final['value']:>12,.2f}
 Total Return:     {final['return']:>+12.2f}%
 S&P 500 Return:   {final['spy_return']:>+12.2f}%
 Alpha:            {final['alpha']:>+12.2f}%  {'✅ BEAT MARKET' if final['alpha'] > 0 else '❌ Trailed market'}

 RISK METRICS
 ────────────────────────────────────────
 Max Drawdown:     {max_dd:>12.2f}%
 Total Trades:     {total_trades:>12}
 Win Rate (days):  {(positive_days/total_days*100) if total_days > 0 else 0:>11.1f}%  ({positive_days}/{total_days})
 Best Day:         {best_day['return']:>+12.2f}%  ({best_day['date']})
 Worst Day:        {worst_day['return']:>+12.2f}%  ({worst_day['date']})

 REGIME BREAKDOWN
 ────────────────────────────────────────""")
    for r, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
        pct = count / len(portfolio_history) * 100
        bar = "█" * int(pct / 2)
        print(f"   {r:<14} {count:>3} days ({pct:>4.0f}%)  {bar}")

    print(f"""
 FINAL POSITIONS
 ────────────────────────────────────────""")
    if positions:
        for asset_id, pos in sorted(positions.items(), key=lambda x: -x[1]["shares"] * day_prices.get(x[0], 0)):
            if asset_id in day_prices:
                val = pos["shares"] * day_prices[asset_id]
                pct = val / final["value"] * 100
                pl = ((day_prices[asset_id] - pos["avg_price"]) / pos["avg_price"]) * 100
                print(f"   {ASSETS[asset_id]['name']:<20} ${val:>10,.2f}  ({pct:>4.1f}%)  {pl:>+6.1f}%")
    print(f"   {'Cash':<20} ${cash:>10,.2f}  ({cash/final['value']*100:>4.1f}%)")

    # RSI signal events
    rsi_events = [t for t in trade_log if "RSI " in t]
    if rsi_events:
        print(f"""
 RSI SIGNAL EVENTS ({len(rsi_events)})
 ────────────────────────────────────────""")
        for t in rsi_events[-15:]:
            print(t)
        if len(rsi_events) > 15:
            print(f"   ... and {len(rsi_events) - 15} more")

    print(f"""
════════════════════════════════════════════════════════════════
""")


def show_trade_history():
    """Show recent trades with RSI signal reasoning from activity log."""
    import re
    log_path = CONFIG_DIR / "activity.log"
    if not log_path.exists():
        print("\n No activity log found.\n")
        return

    lines = log_path.read_text().splitlines()

    # Parse log into trading sessions (each starts with "Starting day-trader check")
    sessions = []
    current = None
    for line in lines:
        if "Starting day-trader check" in line:
            current = {"time": line[:20].strip("[] "), "signal": "", "spy_rsi": "",
                       "portfolio": "", "trades": [], "reason": ""}
        elif current:
            if "RSI signal:" in line:
                m = re.search(r"RSI signal: (\w+) \(SPY RSI=(\d+), (\w+)\)", line)
                if m:
                    current["signal"] = m.group(1)
                    current["spy_rsi"] = m.group(2)
                    current["reason"] = f"SPY RSI={m.group(2)}, {m.group(3)}"
            elif "Target allocation" in line and not current["signal"]:
                m = re.search(r"Target allocation \((\w+)\)", line)
                if m:
                    current["signal"] = m.group(1)
                    current["reason"] = f"regime: {m.group(1)} (old strategy)"
            elif "Confirmed regime:" in line and not current["signal"]:
                m = re.search(r"Confirmed regime: (\w+)", line)
                if m:
                    current["signal"] = m.group(1)
                    current["reason"] = f"regime: {m.group(1)} (old strategy)"
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
RSI Day-Trader Bot v4.0

Usage: python3 autonomous_investor.py [command]

Commands:
  --daily     Run trading check
  --benchmark Performance vs S&P 500
  --trades    Recent trades & reasoning
  --simulate [days]  Run backtest simulation (default 90 days)
  --compare [days]   Compare RSI vs Regime vs SPY (default 365)
  --paper-init       Initialize paper trading at current live value
  --paper            Show paper vs live comparison
        """)
        return

    config = load_config()
    command = sys.argv[1]

    if command == "--daily":
        run_daily_check(config)
        # Also run paper trade if initialized
        if PAPER_FILE.exists():
            run_paper_trade(config)
    elif command == "--weekly":
        run_weekly_report(config)
    elif command == "--status":
        show_status()
    elif command == "--benchmark":
        show_benchmark()
    elif command == "--analysis":
        show_market_analysis()
    elif command == "--simulate":
        days = 90
        if len(sys.argv) > 2:
            try:
                days = max(30, min(1500, int(sys.argv[2])))
            except ValueError:
                pass
        run_backtest(config, days=days)
    elif command == "--compare":
        days = 365
        if len(sys.argv) > 2:
            try:
                days = max(30, min(1500, int(sys.argv[2])))
            except ValueError:
                pass
        run_comparison(config, days=days)
    elif command == "--paper-init":
        api_key = config.get("alpaca_api_key")
        api_secret = config.get("alpaca_api_secret")
        is_paper = config.get("paper_trading", True)
        if api_key and api_secret:
            client = AlpacaClient(api_key, api_secret, is_paper)
            account = client.get_account()
            live_value = float(account.get("equity", 0))
            init_paper_portfolio(live_value)
            print(f"\n Paper portfolio initialized at ${live_value:.2f}")
            print(f" It will auto-trade alongside --daily runs.\n")
        else:
            print("\n Alpaca credentials not configured.\n")
    elif command == "--trades":
        show_trade_history()
    elif command == "--paper":
        show_paper_status(config)


if __name__ == "__main__":
    main()
