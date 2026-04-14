#!/bin/bash

while true; do
    clear
    echo "════════════════════════════════════════════════════════════════"
    echo " 🤖 RSI DAY-TRADER BOT v4.0"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "   1) Portfolio Status"
    echo "   2) Performance vs Market"
    echo "   3) Market Analysis"
    echo "   4) Run Trading Check Now"
    echo "   5) Recent Trades & Reasoning"
    echo "   6) Paper vs Live Comparison"
    echo "   7) Compare Strategies"
    echo "   8) Simulate (Custom Backtest)"
    echo ""
    echo "   0) Exit"
    echo ""
    echo " ────────────────────────────────────────────────────────────────"
    echo "  Strategy: RSI Buy-Low / Sell-High | Leveraged ETFs | Daily Rebalance"
    echo "════════════════════════════════════════════════════════════════"
    echo -n " Select option: "
    read choice

    case $choice in
        1)
            echo ""
            python3 ~/autonomous_investor.py --status
            echo ""
            read -p " Press Enter to continue..."
            ;;
        2)
            echo ""
            python3 ~/autonomous_investor.py --benchmark
            echo ""
            read -p " Press Enter to continue..."
            ;;
        3)
            echo ""
            python3 ~/autonomous_investor.py --analysis
            echo ""
            read -p " Press Enter to continue..."
            ;;
        4)
            echo ""
            python3 ~/autonomous_investor.py --daily
            echo ""
            read -p " Press Enter to continue..."
            ;;
        5)
            echo ""
            python3 ~/autonomous_investor.py --trades
            echo ""
            read -p " Press Enter to continue..."
            ;;
        6)
            echo ""
            if [ ! -f ~/.autonomous_investor/paper_portfolio.json ]; then
                echo " Paper portfolio not initialized. Initializing now..."
                python3 ~/autonomous_investor.py --paper-init
            fi
            python3 ~/autonomous_investor.py --paper
            echo ""
            read -p " Press Enter to continue..."
            ;;
        7)
            echo ""
            echo -n " Enter number of days to compare (30-1500) [90]: "
            read cmp_days
            if [ -z "$cmp_days" ]; then
                cmp_days=90
            fi
            echo ""
            python3 ~/autonomous_investor.py --compare "$cmp_days"
            echo ""
            read -p " Press Enter to continue..."
            ;;
        8)
            echo ""
            echo -n " Enter number of days to simulate (30-1500) [90]: "
            read sim_days
            if [ -z "$sim_days" ]; then
                sim_days=90
            fi
            echo ""
            python3 ~/autonomous_investor.py --simulate "$sim_days"
            echo ""
            read -p " Press Enter to continue..."
            ;;
        0)
            clear
            echo " Goodbye!"
            exit 0
            ;;
        *)
            echo " Invalid option"
            sleep 1
            ;;
    esac
done
