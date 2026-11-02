# Investor Bot

A long-term, buy-and-hold trading bot for [Alpaca](https://alpaca.markets) brokerage accounts. It finds small and mid-cap growth stocks, requires each one to pass independent checks, and holds a small portfolio instead of trading frequently.

Earlier versions rotated through leveraged and inverse ETFs using RSI signals. v5.0 replaces that approach with fundamentals-based selection.

## Features

- **Stock discovery** — builds its candidate list from small and mid-cap growth screens
- **Three-part screen** — a stock must pass fundamentals, price trend, and insider activity checks, and any one can veto it
- **Concentrated portfolio** — up to 6 stocks at 10% each, with a small Bitcoin ETF (IBIT) position
- **Risk controls** — per-asset trailing stops, sector limits, and correlation checks
- **Exit checks** — periodically rechecks the fundamentals of held stocks
- **Stop-loss calibration** — adjusts stop levels based on past stop-loss outcomes
- **Reporting** — tracks performance against the S&P 500 and emails a weekly report
- **Portfolio diversifier** — separate tool for planning long-term asset allocation

## Files

| File | Description |
|---|---|
| `autonomous_investor.py` | Main trading bot |
| `investment_diversifier.py` | Portfolio diversification planning tool |

## Setup

Requires macOS and Python 3.10+. The bot has no third-party dependencies.

1. Create an Alpaca account and generate API keys.
2. Store your credentials in the macOS Keychain:

```bash
security add-generic-password -s autonomous_investor -a alpaca_api_key -w
security add-generic-password -s autonomous_investor -a alpaca_api_secret -w
security add-generic-password -s autonomous_investor -a email_password -w
```

3. Add your non-secret settings to `~/.autonomous_investor/config.json`, such as `paper_trading`, `email_address`, `notification_email`, `smtp_server`, and `smtp_port`. Use `paper_trading: true` to test without real money.

## CLI Usage

```bash
python3 autonomous_investor.py --status       # Current holdings and performance
python3 autonomous_investor.py --daily        # Rescan, rebalance, and check exits
python3 autonomous_investor.py --weekly       # Email the weekly report
python3 autonomous_investor.py --trades       # Recent trades and reasoning
python3 autonomous_investor.py --benchmark    # Performance vs S&P 500
```

## Disclaimer

This is a personal project for educational purposes. Trading carries significant risk, and this code is not financial advice.
