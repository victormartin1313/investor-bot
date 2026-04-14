# Investor Bot

An autonomous trading bot that runs on a live Alpaca brokerage account. Uses RSI signals, market regime detection, and self-learning weights to trade leveraged ETFs, individual stocks, and crypto.

## Features

- **RSI strategy** — buys oversold assets, sells overbought ones
- **Market regime detection** — switches between bull, bear, and neutral allocations automatically
- **Self-learning** — adjusts signal weights and stop-loss thresholds based on recent performance
- **Leveraged ETFs** — trades TQQQ, SOXL, UPRO, TECL, FNGU in bull regimes
- **Inverse ETFs** — rotates into SQQQ, SPXS in bear regimes
- **Trailing stops** — per-asset configurable stop-loss percentages
- **Sector limits** — caps exposure per sector to limit concentration risk
- **Paper trading comparison** — tracks a shadow paper portfolio alongside live trades
- **Backtesting** — simulate any strategy over custom date ranges
- **Portfolio diversifier** — separate tool for planning long-term asset allocation

## Files

| File | Description |
|---|---|
| `autonomous_investor.py` | Main trading bot |
| `investment_diversifier.py` | Portfolio diversification planning tool |
| `investor.sh` | Interactive terminal menu for the bot |

## Setup

1. Create an [Alpaca](https://alpaca.markets) account and generate API keys
2. Clone the repo and install dependencies:

```bash
git clone https://github.com/victormartin1313/investor-bot.git
cd investor-bot
pip install alpaca-trade-api yfinance requests
```

3. Run setup to configure your API keys and preferences:

```bash
python3 autonomous_investor.py --setup
```

4. Use the interactive menu:

```bash
bash investor.sh
```

## CLI Usage

```bash
python3 autonomous_investor.py --status       # Portfolio overview
python3 autonomous_investor.py --analysis     # Market regime analysis
python3 autonomous_investor.py --daily        # Run a trading check
python3 autonomous_investor.py --trades       # Recent trades and reasoning
python3 autonomous_investor.py --benchmark    # Performance vs S&P 500
python3 autonomous_investor.py --simulate 90  # Backtest over 90 days
python3 autonomous_investor.py --paper        # Paper vs live comparison
```

## Disclaimer

This is a personal project for educational purposes. Leveraged ETFs and algorithmic trading carry significant risk. Past performance does not guarantee future results.
