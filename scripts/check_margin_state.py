import os
import sys
import argparse
from dotenv import load_dotenv

# Ensure the project root is in the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from src.infrastructure.binance.margin_client import BinanceMarginClient
from src.utils.logger_utils import setup_logger
from src.utils.pipeline_utils import load_global_config

logger = setup_logger("check_margin")

def main():
    parser = argparse.ArgumentParser(description="Check Binance Spot Cross Margin Status")
    parser.add_argument("--symbol", type=str, required=True, help="Trading pair prefix (e.g. XAUT)")
    args = parser.parse_args()

    # Load environment variables from .env
    load_dotenv(os.path.join(project_root, ".env"))
    
    try:
        cfg = load_global_config()
        from src.utils.symbol_utils import resolve_symbol
        symbol = resolve_symbol(args.symbol)

        client = BinanceMarginClient()
        
        print("\n" + "="*50)
        print(" BINANCE SPOT CROSS MARGIN STATUS ")
        print("="*50)
        
        # 1. Account Summary
        account = client.get_cross_margin_account()
        print(f"\n[Account Overview]")
        print(f"- Total Net Asset (BTC): {account.total_net_asset_of_btc:.8f}")
        print(f"- Total Liability (BTC): {account.total_liability_of_btc:.8f}")
        print(f"- Margin Level: {account.margin_level:.4f}")
        print(f"- Status: {account.status}")
        
        # 1.5 Ticker Price
        current_price = client.get_ticker_price(symbol)
        print(f"\n[Market Monitor]")
        print(f"- {symbol} Current Price: {current_price:>10.2f}")
        
        # 2. Key Assets (Only show non-zero)
        print(f"\n[Asset Details]")
        for asset in account.assets:
            if asset.net_asset != 0 or asset.borrowed > 0:
                print(f"- {asset.asset:<6} | Net: {asset.net_asset:>12.6f} | Borrowed: {asset.borrowed:>12.6f} | Free: {asset.free:>12.6f}")

        # 3. Active Orders
        print(f"\n[Active Margin Orders]")
        orders = client.get_active_orders()
        if not orders:
            print("No active open orders.")
        for order in orders:
            trigger_str = ""
            if order.stop_price > 0:
                dist = ((order.stop_price / current_price) - 1) * 100 if current_price > 0 else 0
                trigger_str = f" | Trigger: {order.stop_price:>10.2f} ({dist:>+6.2f}%)"
            
            print(f"- {order.symbol:<10} | {order.side:<4} | {order.type:<10} | Qty: {order.orig_qty:>10.4f} | Price: {order.price:>10.2f}{trigger_str}")

        # 4. Symbol Specific Position
        print(f"\n[Focus: {symbol} Position]")
        symbol_pos = client.get_symbol_position(symbol)
        if symbol_pos:
            unpnl = (current_price - (current_price/(1+0))) # Not real PNL since we don't have entry price
            # But we can show effective value
            value = symbol_pos.net_qty * current_price
            side = "LONG" if symbol_pos.net_qty > 0 else "SHORT" if symbol_pos.net_qty < 0 else "FLAT"
            print(f"- Side: {side}")
            print(f"- Net Qty: {symbol_pos.net_qty:.6f}")
            print(f"- Net Value (USDT): {value:>10.2f}")
            print(f"- Borrowed: {symbol_pos.borrowed:.6f}")
        else:
            print(f"- No {symbol} position found.")

        print("\n" + "="*50)

    except Exception as e:
        logger.error(f"execution failed | error={e}")
        print(f"\n[ERROR] {e}")

if __name__ == "__main__":
    main()
