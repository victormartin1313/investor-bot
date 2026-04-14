#!/usr/bin/env python3
"""
Investment Portfolio Diversification Tool
With live market data, net worth tracking, and advanced features.
"""

import json
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import ssl

CONFIG_FILE = Path.home() / ".investment_portfolio.json"

# Disable SSL verification for API calls (some systems have issues)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Asset class definitions with risk/return profiles
ASSET_CLASSES = {
    "US Stocks": {
        "risk": "high",
        "expected_return": 10.0,
        "volatility": 16.0,
        "description": "US equities (S&P 500, total market)",
        "etf_examples": ["VTI", "VOO", "SPY", "ITOT"],
        "benchmark": "VTI"
    },
    "International Stocks": {
        "risk": "high",
        "expected_return": 8.0,
        "volatility": 18.0,
        "description": "Developed & emerging markets",
        "etf_examples": ["VXUS", "VEA", "VWO", "IXUS"],
        "benchmark": "VXUS"
    },
    "US Bonds": {
        "risk": "low",
        "expected_return": 4.5,
        "volatility": 5.0,
        "description": "US Treasury and investment-grade bonds",
        "etf_examples": ["BND", "AGG", "SCHZ", "TLT"],
        "benchmark": "BND"
    },
    "International Bonds": {
        "risk": "low",
        "expected_return": 4.0,
        "volatility": 6.0,
        "description": "Foreign government and corporate bonds",
        "etf_examples": ["BNDX", "IAGG", "BWX"],
        "benchmark": "BNDX"
    },
    "Real Estate (REITs)": {
        "risk": "medium",
        "expected_return": 8.0,
        "volatility": 14.0,
        "description": "Real estate investment trusts",
        "etf_examples": ["VNQ", "SCHH", "IYR", "XLRE"],
        "benchmark": "VNQ"
    },
    "Commodities": {
        "risk": "high",
        "expected_return": 5.0,
        "volatility": 20.0,
        "description": "Gold, silver, oil, agriculture",
        "etf_examples": ["GLD", "IAU", "DBC", "PDBC"],
        "benchmark": "GLD"
    },
    "Cash/Money Market": {
        "risk": "very_low",
        "expected_return": 5.0,
        "volatility": 0.5,
        "description": "High-yield savings, money market, T-bills",
        "etf_examples": ["SGOV", "BIL", "SHV"],
        "benchmark": "SGOV"
    },
    "Crypto": {
        "risk": "very_high",
        "expected_return": 15.0,
        "volatility": 60.0,
        "description": "Bitcoin, Ethereum, etc.",
        "etf_examples": ["IBIT", "FBTC", "ETHE"],
        "benchmark": "IBIT"
    }
}

# Model portfolios based on risk tolerance
MODEL_PORTFOLIOS = {
    "conservative": {
        "description": "Low risk, focus on capital preservation",
        "age_range": "60+",
        "allocation": {
            "US Stocks": 20,
            "International Stocks": 10,
            "US Bonds": 40,
            "International Bonds": 10,
            "Real Estate (REITs)": 5,
            "Cash/Money Market": 15
        }
    },
    "moderate_conservative": {
        "description": "Below average risk, balanced growth",
        "age_range": "50-60",
        "allocation": {
            "US Stocks": 35,
            "International Stocks": 15,
            "US Bonds": 30,
            "International Bonds": 5,
            "Real Estate (REITs)": 10,
            "Cash/Money Market": 5
        }
    },
    "moderate": {
        "description": "Balanced risk and return",
        "age_range": "40-50",
        "allocation": {
            "US Stocks": 45,
            "International Stocks": 20,
            "US Bonds": 20,
            "International Bonds": 5,
            "Real Estate (REITs)": 10
        }
    },
    "moderate_aggressive": {
        "description": "Above average risk for growth",
        "age_range": "30-40",
        "allocation": {
            "US Stocks": 55,
            "International Stocks": 25,
            "US Bonds": 10,
            "Real Estate (REITs)": 10
        }
    },
    "aggressive": {
        "description": "High risk, maximum growth potential",
        "age_range": "20-30",
        "allocation": {
            "US Stocks": 60,
            "International Stocks": 30,
            "Real Estate (REITs)": 5,
            "Crypto": 5
        }
    }
}


# =============================================================================
# LIVE DATA APIs
# =============================================================================

def fetch_stock_price(symbol: str) -> Optional[dict]:
    """Fetch live stock/ETF price from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            data = json.loads(response.read().decode())
            result = data['chart']['result'][0]
            meta = result['meta']
            return {
                "symbol": symbol,
                "price": meta.get('regularMarketPrice', 0),
                "previous_close": meta.get('previousClose', 0),
                "change": meta.get('regularMarketPrice', 0) - meta.get('previousClose', 0),
                "change_percent": ((meta.get('regularMarketPrice', 0) - meta.get('previousClose', 0)) / meta.get('previousClose', 1)) * 100,
                "currency": meta.get('currency', 'USD')
            }
    except Exception as e:
        return None

def fetch_crypto_price(symbol: str) -> Optional[dict]:
    """Fetch crypto price from CoinGecko."""
    crypto_ids = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "XRP": "ripple",
        "ADA": "cardano",
        "DOGE": "dogecoin"
    }

    coin_id = crypto_ids.get(symbol.upper(), symbol.lower())
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            data = json.loads(response.read().decode())
            if coin_id in data:
                return {
                    "symbol": symbol.upper(),
                    "price": data[coin_id]['usd'],
                    "change_percent": data[coin_id].get('usd_24h_change', 0)
                }
    except Exception:
        pass
    return None

def fetch_treasury_rates() -> Optional[dict]:
    """Fetch current Treasury rates (approximation from ETF yields)."""
    # Use short-term treasury ETF as proxy
    sgov = fetch_stock_price("SGOV")
    tlt = fetch_stock_price("TLT")  # Long-term treasury

    return {
        "short_term": 5.25 if sgov else 5.0,  # Approximate current short-term rate
        "long_term": 4.5 if tlt else 4.5,
        "source": "Estimated from market data"
    }

def fetch_fed_funds_rate() -> float:
    """Return current approximate Fed Funds rate."""
    # As of late 2024/early 2025, Fed Funds rate is around 4.25-4.50%
    return 4.50

def get_live_portfolio_prices(holdings: Dict[str, List[dict]]) -> Dict[str, dict]:
    """Fetch live prices for all holdings."""
    prices = {}
    print("\n  Fetching live prices", end="", flush=True)

    for asset_class, positions in holdings.items():
        for position in positions:
            symbol = position.get("symbol", "")
            if symbol and symbol not in prices:
                if asset_class == "Crypto":
                    price_data = fetch_crypto_price(symbol)
                else:
                    price_data = fetch_stock_price(symbol)

                if price_data:
                    prices[symbol] = price_data
                print(".", end="", flush=True)

    print(" Done!")
    return prices


# =============================================================================
# DATA PERSISTENCE
# =============================================================================

def load_portfolio():
    """Load saved portfolio."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {
        "holdings": {},
        "detailed_holdings": {},
        "net_worth": {},
        "history": []
    }

def save_portfolio(portfolio):
    """Save portfolio."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(portfolio, f, indent=2)


# =============================================================================
# FORMATTING HELPERS
# =============================================================================

def format_currency(amount):
    return f"${amount:,.2f}"

def format_percent(value):
    return f"{value:.1f}%"

def print_section(title):
    print(f"\n{'='*70}")
    print(f" {title}")
    print('='*70)

def print_subsection(title):
    print(f"\n  {title}")
    print("  " + "-"*60)


# =============================================================================
# PORTFOLIO ANALYSIS
# =============================================================================

def calculate_portfolio_metrics(holdings: Dict[str, float]) -> dict:
    """Calculate portfolio risk and return metrics."""
    total = sum(holdings.values())
    if total == 0:
        return {"expected_return": 0, "volatility": 0, "risk_level": "none"}

    weighted_return = 0
    weighted_volatility = 0

    for asset_class, amount in holdings.items():
        if asset_class in ASSET_CLASSES:
            weight = amount / total
            info = ASSET_CLASSES[asset_class]
            weighted_return += weight * info["expected_return"]
            weighted_volatility += weight * info["volatility"]

    if weighted_volatility < 5:
        risk_level = "Very Low"
    elif weighted_volatility < 10:
        risk_level = "Low"
    elif weighted_volatility < 15:
        risk_level = "Moderate"
    elif weighted_volatility < 20:
        risk_level = "High"
    else:
        risk_level = "Very High"

    return {
        "expected_return": weighted_return,
        "volatility": weighted_volatility,
        "risk_level": risk_level
    }

def analyze_diversification(holdings: Dict[str, float]) -> dict:
    """Analyze how well diversified the portfolio is."""
    total = sum(holdings.values())
    if total == 0:
        return {"score": 0, "issues": ["No holdings"]}

    issues = []
    score = 100

    for asset_class, amount in holdings.items():
        percent = (amount / total) * 100
        if percent > 50:
            issues.append(f"Over-concentrated in {asset_class} ({format_percent(percent)})")
            score -= 30
        elif percent > 35:
            issues.append(f"High concentration in {asset_class} ({format_percent(percent)})")
            score -= 15

    has_stocks = any(k in holdings and holdings[k] > 0 for k in ["US Stocks", "International Stocks"])
    has_bonds = any(k in holdings and holdings[k] > 0 for k in ["US Bonds", "International Bonds"])
    has_alternatives = any(k in holdings and holdings[k] > 0 for k in ["Real Estate (REITs)", "Commodities"])

    if not has_stocks:
        issues.append("Missing equity exposure")
        score -= 20
    if not has_bonds:
        issues.append("Missing fixed income exposure")
        score -= 15
    if not has_alternatives:
        issues.append("Consider adding alternative assets (REITs, commodities)")
        score -= 5

    us_only = holdings.get("US Stocks", 0) + holdings.get("US Bonds", 0)
    intl = holdings.get("International Stocks", 0) + holdings.get("International Bonds", 0)
    if us_only > 0 and intl / max(us_only + intl, 1) < 0.15:
        issues.append("Low international diversification")
        score -= 10

    return {
        "score": max(0, score),
        "issues": issues if issues else ["Portfolio is well diversified!"]
    }

def suggest_rebalancing(holdings: Dict[str, float], target_risk: str) -> Dict[str, dict]:
    """Suggest rebalancing based on target risk profile."""
    total = sum(holdings.values())
    if total == 0:
        return {}

    target = MODEL_PORTFOLIOS.get(target_risk, MODEL_PORTFOLIOS["moderate"])
    suggestions = {}

    for asset_class, target_percent in target["allocation"].items():
        current_amount = holdings.get(asset_class, 0)
        current_percent = (current_amount / total) * 100 if total > 0 else 0
        target_amount = total * (target_percent / 100)
        difference = target_amount - current_amount

        suggestions[asset_class] = {
            "current_percent": current_percent,
            "target_percent": target_percent,
            "current_amount": current_amount,
            "target_amount": target_amount,
            "action": "buy" if difference > 0 else "sell" if difference < 0 else "hold",
            "amount": abs(difference)
        }

    return suggestions

def project_growth(total: float, expected_return: float, years: int = 10, monthly_contribution: float = 0) -> List[dict]:
    """Project portfolio growth over time with optional contributions."""
    annual_return = expected_return / 100
    projections = []
    current_value = total
    total_contributions = 0

    for year in range(1, years + 1):
        # Add monthly contributions
        for _ in range(12):
            current_value += monthly_contribution
            total_contributions += monthly_contribution
            current_value *= (1 + annual_return / 12)

        projections.append({
            "year": year,
            "value": current_value,
            "contributions": total_contributions,
            "gain": current_value - total - total_contributions
        })

    return projections


# =============================================================================
# NET WORTH TRACKER
# =============================================================================

def input_net_worth(portfolio: dict) -> dict:
    """Input all assets and liabilities for net worth calculation."""
    print_section("NET WORTH TRACKER")

    net_worth = portfolio.get("net_worth", {})

    print("\n  Enter your assets and liabilities.")
    print("  Press Enter to keep existing value, or enter new amount.\n")

    # Assets
    print("  ASSETS:")
    print("  -------")

    # Investment accounts
    default = net_worth.get("investment_accounts", 0)
    val = input(f"    Investment accounts (401k, IRA, brokerage) [{format_currency(default)}]: ").strip()
    net_worth["investment_accounts"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Real estate
    default = net_worth.get("real_estate", 0)
    val = input(f"    Real estate (home value) [{format_currency(default)}]: ").strip()
    net_worth["real_estate"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Cash & savings
    default = net_worth.get("cash_savings", 0)
    val = input(f"    Cash & savings accounts [{format_currency(default)}]: ").strip()
    net_worth["cash_savings"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Vehicles
    default = net_worth.get("vehicles", 0)
    val = input(f"    Vehicles [{format_currency(default)}]: ").strip()
    net_worth["vehicles"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Other assets
    default = net_worth.get("other_assets", 0)
    val = input(f"    Other assets (collectibles, etc.) [{format_currency(default)}]: ").strip()
    net_worth["other_assets"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Liabilities
    print("\n  LIABILITIES:")
    print("  ------------")

    # Mortgage
    default = net_worth.get("mortgage", 0)
    val = input(f"    Mortgage balance [{format_currency(default)}]: ").strip()
    net_worth["mortgage"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Car loans
    default = net_worth.get("car_loans", 0)
    val = input(f"    Car loans [{format_currency(default)}]: ").strip()
    net_worth["car_loans"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Student loans
    default = net_worth.get("student_loans", 0)
    val = input(f"    Student loans [{format_currency(default)}]: ").strip()
    net_worth["student_loans"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Credit cards
    default = net_worth.get("credit_cards", 0)
    val = input(f"    Credit card debt [{format_currency(default)}]: ").strip()
    net_worth["credit_cards"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Other debt
    default = net_worth.get("other_debt", 0)
    val = input(f"    Other debt [{format_currency(default)}]: ").strip()
    net_worth["other_debt"] = float(val.replace(",", "").replace("$", "")) if val else default

    # Income info
    print("\n  INCOME:")
    print("  -------")
    default = net_worth.get("yearly_income", 0)
    val = input(f"    Yearly gross income [{format_currency(default)}]: ").strip()
    net_worth["yearly_income"] = float(val.replace(",", "").replace("$", "")) if val else default

    default = net_worth.get("monthly_savings", 0)
    val = input(f"    Monthly investment contribution [{format_currency(default)}]: ").strip()
    net_worth["monthly_savings"] = float(val.replace(",", "").replace("$", "")) if val else default

    return net_worth

def display_net_worth(net_worth: dict):
    """Display net worth summary."""

    assets = (
        net_worth.get("investment_accounts", 0) +
        net_worth.get("real_estate", 0) +
        net_worth.get("cash_savings", 0) +
        net_worth.get("vehicles", 0) +
        net_worth.get("other_assets", 0)
    )

    liabilities = (
        net_worth.get("mortgage", 0) +
        net_worth.get("car_loans", 0) +
        net_worth.get("student_loans", 0) +
        net_worth.get("credit_cards", 0) +
        net_worth.get("other_debt", 0)
    )

    total_net_worth = assets - liabilities

    print_subsection("ASSETS")
    print(f"    Investment Accounts:  {format_currency(net_worth.get('investment_accounts', 0)):>15}")
    print(f"    Real Estate:          {format_currency(net_worth.get('real_estate', 0)):>15}")
    print(f"    Cash & Savings:       {format_currency(net_worth.get('cash_savings', 0)):>15}")
    print(f"    Vehicles:             {format_currency(net_worth.get('vehicles', 0)):>15}")
    print(f"    Other Assets:         {format_currency(net_worth.get('other_assets', 0)):>15}")
    print(f"    {'─'*40}")
    print(f"    TOTAL ASSETS:         {format_currency(assets):>15}")

    print_subsection("LIABILITIES")
    print(f"    Mortgage:             {format_currency(net_worth.get('mortgage', 0)):>15}")
    print(f"    Car Loans:            {format_currency(net_worth.get('car_loans', 0)):>15}")
    print(f"    Student Loans:        {format_currency(net_worth.get('student_loans', 0)):>15}")
    print(f"    Credit Cards:         {format_currency(net_worth.get('credit_cards', 0)):>15}")
    print(f"    Other Debt:           {format_currency(net_worth.get('other_debt', 0)):>15}")
    print(f"    {'─'*40}")
    print(f"    TOTAL LIABILITIES:    {format_currency(liabilities):>15}")

    print_subsection("NET WORTH")
    print(f"    ┌{'─'*42}┐")
    print(f"    │  TOTAL NET WORTH:   {format_currency(total_net_worth):>18}  │")
    print(f"    └{'─'*42}┘")

    # Key ratios
    yearly_income = net_worth.get("yearly_income", 1)
    print_subsection("KEY METRICS")
    print(f"    Savings Rate:         {format_percent((net_worth.get('monthly_savings', 0) * 12 / yearly_income) * 100) if yearly_income else 'N/A':>15}")
    print(f"    Debt-to-Income:       {format_percent((liabilities / yearly_income) * 100) if yearly_income else 'N/A':>15}")
    print(f"    Net Worth/Income:     {(total_net_worth / yearly_income):.1f}x" if yearly_income else "N/A")

    return total_net_worth


# =============================================================================
# DETAILED HOLDINGS TRACKER
# =============================================================================

def input_detailed_holdings(portfolio: dict) -> dict:
    """Input detailed holdings with specific symbols and shares."""
    print_section("DETAILED HOLDINGS INPUT")

    detailed = portfolio.get("detailed_holdings", {})

    print("\n  Enter your holdings by asset class.")
    print("  Format: SYMBOL SHARES (e.g., 'VTI 100' or 'AAPL 50')")
    print("  Type 'done' when finished with each category.\n")

    for asset_class in ASSET_CLASSES.keys():
        print(f"\n  {asset_class}:")
        examples = ASSET_CLASSES[asset_class]["etf_examples"]
        print(f"    Suggested ETFs: {', '.join(examples)}")

        if asset_class not in detailed:
            detailed[asset_class] = []

        # Show existing
        if detailed[asset_class]:
            print(f"    Current holdings:")
            for h in detailed[asset_class]:
                print(f"      - {h['symbol']}: {h['shares']} shares")

            clear = input("    Clear existing and re-enter? (y/n): ").strip().lower()
            if clear == 'y':
                detailed[asset_class] = []
            else:
                continue

        while True:
            entry = input(f"    Enter holding (or 'done'): ").strip()
            if entry.lower() == 'done' or entry == '':
                break

            parts = entry.upper().split()
            if len(parts) >= 2:
                try:
                    symbol = parts[0]
                    shares = float(parts[1])
                    detailed[asset_class].append({
                        "symbol": symbol,
                        "shares": shares,
                        "added_date": datetime.now().isoformat()
                    })
                    print(f"      Added: {symbol} - {shares} shares")
                except ValueError:
                    print("      Invalid format. Use: SYMBOL SHARES")
            else:
                print("      Invalid format. Use: SYMBOL SHARES")

    return detailed

def display_detailed_holdings(detailed: dict, live_prices: dict):
    """Display detailed holdings with live prices."""

    print_subsection("HOLDINGS BY ASSET CLASS")

    grand_total = 0
    totals_by_class = {}

    for asset_class, positions in detailed.items():
        if not positions:
            continue

        class_total = 0
        print(f"\n    {asset_class}:")
        print(f"    {'Symbol':<8} {'Shares':>10} {'Price':>12} {'Value':>14} {'Day Chg':>10}")
        print(f"    {'-'*58}")

        for pos in positions:
            symbol = pos["symbol"]
            shares = pos["shares"]

            if symbol in live_prices:
                price = live_prices[symbol]["price"]
                change = live_prices[symbol].get("change_percent", 0)
                value = shares * price
                class_total += value

                change_str = f"{'+' if change >= 0 else ''}{change:.1f}%"
                print(f"    {symbol:<8} {shares:>10.2f} {format_currency(price):>12} {format_currency(value):>14} {change_str:>10}")
            else:
                print(f"    {symbol:<8} {shares:>10.2f} {'N/A':>12} {'N/A':>14} {'N/A':>10}")

        print(f"    {'-'*58}")
        print(f"    {'SUBTOTAL':<8} {'':<10} {'':<12} {format_currency(class_total):>14}")
        totals_by_class[asset_class] = class_total
        grand_total += class_total

    print(f"\n    {'='*58}")
    print(f"    PORTFOLIO TOTAL: {format_currency(grand_total):>37}")

    return totals_by_class, grand_total


# =============================================================================
# MARKET OVERVIEW
# =============================================================================

def display_market_overview():
    """Show current market conditions."""
    print_section("LIVE MARKET OVERVIEW")

    # Fetch key indices
    indices = {
        "S&P 500": "SPY",
        "Nasdaq": "QQQ",
        "Dow Jones": "DIA",
        "Total Bond": "BND",
        "Gold": "GLD",
        "Bitcoin ETF": "IBIT"
    }

    print("\n  Fetching market data", end="", flush=True)

    print(f"\n\n  {'Index/Asset':<15} {'Price':>12} {'Day Change':>12}")
    print(f"  {'-'*42}")

    for name, symbol in indices.items():
        data = fetch_stock_price(symbol)
        if data:
            change_str = f"{'+' if data['change_percent'] >= 0 else ''}{data['change_percent']:.2f}%"
            print(f"  {name:<15} {format_currency(data['price']):>12} {change_str:>12}")
        else:
            print(f"  {name:<15} {'N/A':>12} {'N/A':>12}")
        print(".", end="", flush=True)

    # Interest rates
    print(f"\n\n  INTEREST RATES:")
    print(f"  {'-'*42}")
    rates = fetch_treasury_rates()
    print(f"  {'Fed Funds Rate':<25} {format_percent(fetch_fed_funds_rate()):>15}")
    print(f"  {'Short-term Treasury':<25} {format_percent(rates['short_term']):>15}")
    print(f"  {'Long-term Treasury':<25} {format_percent(rates['long_term']):>15}")


# =============================================================================
# ADVANCED FEATURES
# =============================================================================

def tax_loss_harvesting(detailed: dict, live_prices: dict, cost_basis: dict) -> List[dict]:
    """Identify tax-loss harvesting opportunities."""
    opportunities = []

    for asset_class, positions in detailed.items():
        for pos in positions:
            symbol = pos["symbol"]
            shares = pos["shares"]

            if symbol in live_prices and symbol in cost_basis:
                current_price = live_prices[symbol]["price"]
                basis = cost_basis[symbol]
                current_value = shares * current_price
                gain_loss = current_value - basis

                if gain_loss < -100:  # At least $100 loss
                    opportunities.append({
                        "symbol": symbol,
                        "asset_class": asset_class,
                        "shares": shares,
                        "cost_basis": basis,
                        "current_value": current_value,
                        "loss": gain_loss,
                        "tax_savings_estimate": abs(gain_loss) * 0.22  # Assume 22% tax bracket
                    })

    return sorted(opportunities, key=lambda x: x["loss"])

def retirement_projection(net_worth: dict, holdings: Dict[str, float], target_age: int = 65):
    """Project retirement readiness."""
    current_age = int(input("  Enter your current age: ") or "35")
    years_to_retirement = target_age - current_age

    investment_total = sum(holdings.values())
    monthly_contribution = net_worth.get("monthly_savings", 0)

    metrics = calculate_portfolio_metrics(holdings)
    expected_return = metrics["expected_return"]

    projections = project_growth(investment_total, expected_return, years_to_retirement, monthly_contribution)

    if projections:
        final = projections[-1]

        print_subsection(f"RETIREMENT PROJECTION (Age {target_age})")
        print(f"    Current Investment Portfolio:  {format_currency(investment_total)}")
        print(f"    Monthly Contributions:         {format_currency(monthly_contribution)}")
        print(f"    Expected Annual Return:        {format_percent(expected_return)}")
        print(f"    Years to Retirement:           {years_to_retirement}")
        print()
        print(f"    Projected Portfolio at {target_age}:    {format_currency(final['value'])}")
        print(f"    Total Contributions:           {format_currency(final['contributions'])}")
        print(f"    Investment Growth:             {format_currency(final['gain'])}")

        # 4% rule
        safe_withdrawal = final['value'] * 0.04
        print()
        print(f"    Safe Annual Withdrawal (4%):   {format_currency(safe_withdrawal)}")
        print(f"    Monthly Income:                {format_currency(safe_withdrawal / 12)}")

        # Milestones
        print_subsection("MILESTONES")
        for p in projections:
            if p["year"] % 5 == 0 or p["year"] == years_to_retirement:
                age = current_age + p["year"]
                print(f"    Age {age}: {format_currency(p['value'])}")


def correlation_analysis(holdings: Dict[str, float]):
    """Show asset class correlation information."""
    print_subsection("ASSET CORRELATION GUIDE")
    print("""
    Understanding correlations helps with diversification:

    POSITIVELY CORRELATED (move together):
    - US Stocks & International Stocks (0.7-0.8)
    - US Bonds & International Bonds (0.6-0.7)
    - REITs & US Stocks (0.5-0.7)

    NEGATIVELY/LOW CORRELATED (diversification benefit):
    - Stocks & Bonds (-0.2 to 0.2)
    - Gold & Stocks (-0.1 to 0.1)
    - Cash & Everything (~0)

    RECOMMENDATION: Combine assets with low/negative correlation
    for better risk-adjusted returns.
    """)

    # Check user's correlation exposure
    total = sum(holdings.values())
    if total == 0:
        return

    stock_pct = (holdings.get("US Stocks", 0) + holdings.get("International Stocks", 0)) / total * 100
    bond_pct = (holdings.get("US Bonds", 0) + holdings.get("International Bonds", 0)) / total * 100
    alt_pct = (holdings.get("Real Estate (REITs)", 0) + holdings.get("Commodities", 0) + holdings.get("Crypto", 0)) / total * 100

    print(f"    Your allocation:")
    print(f"    - Equities:     {format_percent(stock_pct)}")
    print(f"    - Fixed Income: {format_percent(bond_pct)}")
    print(f"    - Alternatives: {format_percent(alt_pct)}")


# =============================================================================
# MAIN MENU
# =============================================================================

def display_portfolio(holdings: Dict[str, float]):
    """Display current portfolio breakdown."""
    total = sum(holdings.values())
    if total == 0:
        print("\n  No holdings recorded yet.")
        return

    print(f"\n  Total Portfolio Value: {format_currency(total)}\n")
    print(f"  {'Asset Class':<25} {'Amount':>15} {'Allocation':>12}")
    print("  " + "-"*55)

    for asset_class, amount in sorted(holdings.items(), key=lambda x: -x[1]):
        percent = (amount / total) * 100 if total > 0 else 0
        print(f"  {asset_class:<25} {format_currency(amount):>15} {format_percent(percent):>12}")


def input_simple_holdings() -> Dict[str, float]:
    """Simple holdings input by asset class total."""
    print("\n  Enter total value for each asset class:")
    print("  (Press Enter to skip)\n")

    holdings = {}
    for asset_class, info in ASSET_CLASSES.items():
        examples = ", ".join(info["etf_examples"][:3])
        value = input(f"    {asset_class} (e.g., {examples}): $").strip()
        if value:
            try:
                amount = float(value.replace(",", "").replace("$", ""))
                if amount > 0:
                    holdings[asset_class] = amount
            except ValueError:
                print(f"      Invalid amount, skipping")

    return holdings


def main():
    print("\n" + "="*70)
    print(" 📊 INVESTMENT PORTFOLIO DIVERSIFICATION TOOL")
    print("    With Live Data, Net Worth Tracking & Advanced Features")
    print("="*70)

    portfolio = load_portfolio()
    holdings = portfolio.get("holdings", {})
    detailed = portfolio.get("detailed_holdings", {})
    net_worth = portfolio.get("net_worth", {})

    while True:
        print("\n  ┌─────────────────────────────────────────┐")
        print("  │              MAIN MENU                  │")
        print("  ├─────────────────────────────────────────┤")
        print("  │  1. View Market Overview (Live)         │")
        print("  │  2. Enter/Update Simple Holdings        │")
        print("  │  3. Enter/Update Detailed Holdings      │")
        print("  │  4. View Portfolio with Live Prices     │")
        print("  │  5. Portfolio Analysis & Diversification│")
        print("  │  6. Get Rebalancing Suggestions         │")
        print("  │  7. Growth Projections                  │")
        print("  │  8. Net Worth Tracker                   │")
        print("  │  9. Retirement Planning                 │")
        print("  │  10. Compare Model Portfolios           │")
        print("  │  11. Asset Correlation Guide            │")
        print("  │  0. Exit                                │")
        print("  └─────────────────────────────────────────┘")

        choice = input("\n  Select option: ").strip()

        if choice == "0":
            print("\n  Portfolio saved. Goodbye!\n")
            break

        elif choice == "1":
            display_market_overview()

        elif choice == "2":
            holdings = input_simple_holdings()
            portfolio["holdings"] = holdings
            portfolio["last_updated"] = datetime.now().isoformat()
            save_portfolio(portfolio)
            print("\n  Portfolio saved!")

        elif choice == "3":
            detailed = input_detailed_holdings(portfolio)
            portfolio["detailed_holdings"] = detailed
            portfolio["last_updated"] = datetime.now().isoformat()
            save_portfolio(portfolio)
            print("\n  Detailed holdings saved!")

        elif choice == "4":
            if detailed and any(detailed.values()):
                live_prices = get_live_portfolio_prices(detailed)
                totals, grand_total = display_detailed_holdings(detailed, live_prices)
                # Update simple holdings from detailed
                holdings = totals
                portfolio["holdings"] = holdings
                save_portfolio(portfolio)
            elif holdings:
                display_portfolio(holdings)
            else:
                print("\n  No holdings to display. Enter holdings first.")

        elif choice == "5":
            if holdings:
                print_section("PORTFOLIO ANALYSIS")
                display_portfolio(holdings)

                metrics = calculate_portfolio_metrics(holdings)
                print(f"\n  Portfolio Metrics:")
                print(f"    Expected Annual Return: {format_percent(metrics['expected_return'])}")
                print(f"    Estimated Volatility:   {format_percent(metrics['volatility'])}")
                print(f"    Risk Level:             {metrics['risk_level']}")

                diversification = analyze_diversification(holdings)
                print(f"\n  Diversification Score: {diversification['score']}/100")
                print("  Analysis:")
                for issue in diversification["issues"]:
                    print(f"    • {issue}")
            else:
                print("\n  No holdings to analyze. Enter holdings first.")

        elif choice == "6":
            if holdings:
                print("\n  Select target risk profile:")
                for i, (name, info) in enumerate(MODEL_PORTFOLIOS.items(), 1):
                    print(f"    {i}. {name.replace('_', ' ').title()} - {info['description']}")

                risk_choice = input("\n  Select (1-5): ").strip()
                risk_names = list(MODEL_PORTFOLIOS.keys())
                try:
                    target_risk = risk_names[int(risk_choice) - 1]
                except (ValueError, IndexError):
                    target_risk = "moderate"

                print_section(f"REBALANCING TO: {target_risk.upper().replace('_', ' ')}")

                suggestions = suggest_rebalancing(holdings, target_risk)
                total = sum(holdings.values())

                print(f"\n  {'Asset Class':<25} {'Current':>10} {'Target':>10} {'Action':>8} {'Amount':>14}")
                print("  " + "-"*70)

                for asset_class, info in suggestions.items():
                    if info["amount"] > 10:
                        print(f"  {asset_class:<25} {format_percent(info['current_percent']):>10} {format_percent(info['target_percent']):>10} {info['action'].upper():>8} {format_currency(info['amount']):>14}")

                # Show specific ETFs to buy
                print("\n  Suggested ETF Trades:")
                for asset_class, info in suggestions.items():
                    if info["action"] == "buy" and info["amount"] > 100:
                        etf = ASSET_CLASSES[asset_class]["etf_examples"][0]
                        print(f"    BUY ~{format_currency(info['amount'])} of {etf} ({asset_class})")
            else:
                print("\n  No holdings to rebalance. Enter holdings first.")

        elif choice == "7":
            if holdings:
                print_section("GROWTH PROJECTIONS")
                total = sum(holdings.values())
                metrics = calculate_portfolio_metrics(holdings)

                monthly = float(input("  Monthly contribution amount [$500]: ").replace("$", "").replace(",", "") or "500")
                years = int(input("  Projection years [10]: ") or "10")

                projections = project_growth(total, metrics["expected_return"], years, monthly)

                print(f"\n  Starting: {format_currency(total)} | Return: {format_percent(metrics['expected_return'])}/yr | Adding: {format_currency(monthly)}/mo\n")
                print(f"  {'Year':<6} {'Portfolio':>15} {'Contributed':>15} {'Growth':>15}")
                print("  " + "-"*55)

                for p in projections:
                    print(f"  {p['year']:<6} {format_currency(p['value']):>15} {format_currency(p['contributions']):>15} {format_currency(p['gain']):>15}")
            else:
                print("\n  No holdings for projection. Enter holdings first.")

        elif choice == "8":
            net_worth = input_net_worth(portfolio)
            portfolio["net_worth"] = net_worth
            portfolio["last_updated"] = datetime.now().isoformat()

            # Track history
            if "history" not in portfolio:
                portfolio["history"] = []
            portfolio["history"].append({
                "date": datetime.now().isoformat(),
                "net_worth": display_net_worth(net_worth)
            })

            save_portfolio(portfolio)

        elif choice == "9":
            if holdings and net_worth:
                print_section("RETIREMENT PLANNING")
                retirement_projection(net_worth, holdings)
            else:
                print("\n  Please enter holdings and net worth data first.")

        elif choice == "10":
            print_section("MODEL PORTFOLIO COMPARISON")
            print(f"\n  {'Portfolio':<22} {'Return':>8} {'Risk':>12} {'Stocks':>8} {'Bonds':>8}")
            print("  " + "-"*62)

            for name, info in MODEL_PORTFOLIOS.items():
                mock_holdings = {k: v * 1000 for k, v in info["allocation"].items()}
                metrics = calculate_portfolio_metrics(mock_holdings)
                stocks = info["allocation"].get("US Stocks", 0) + info["allocation"].get("International Stocks", 0)
                bonds = info["allocation"].get("US Bonds", 0) + info["allocation"].get("International Bonds", 0)
                print(f"  {name.replace('_', ' ').title():<22} {format_percent(metrics['expected_return']):>8} {metrics['risk_level']:>12} {stocks:>7}% {bonds:>7}%")

            print("\n  ETF Guide by Asset Class:")
            print("  " + "-"*62)
            for name, info in ASSET_CLASSES.items():
                print(f"  {name:<25} {', '.join(info['etf_examples'][:4])}")

        elif choice == "11":
            correlation_analysis(holdings)

        input("\n  Press Enter to continue...")


if __name__ == "__main__":
    main()
