import argparse
import json
import yaml
import os
import sys

def resolve_project_root():
    """Simple project root resolver for standalone script."""
    search_path = os.path.abspath(os.path.dirname(__file__))
    while search_path != os.path.dirname(search_path):
        if any(os.path.exists(os.path.join(search_path, marker)) for marker in [".git", "src", "config"]):
            return search_path
        search_path = os.path.dirname(search_path)
    return os.getcwd()

def calculate_sized_qty(equity, risk_per_trade, entry, sl, p_qty, min_qty=0.0):
    """Core calculation logic extracted for testing."""
    max_loss = equity * risk_per_trade
    price_delta = abs(entry - sl)
    
    if price_delta == 0:
        raise ValueError("Stop loss distance is zero. Cannot calculate quantity.")
        
    target_qty = max_loss / price_delta
    rounded_qty = round(target_qty, p_qty)
    
    # Floor to min_qty if necessary
    final_qty = max(rounded_qty, min_qty)
    return target_qty, final_qty

def main():
    parser = argparse.ArgumentParser(description="Calculate trading quantity from session file and manual balance.")
    parser.add_argument("-f", "--file", required=True, help="Path to the session JSON file.")
    parser.add_argument("-b", "--balance", type=float, required=True, help="Manual equity balance in USDT (e.g., 1000).")
    
    args = parser.parse_args()
    
    # 1. Load Configuration
    root = resolve_project_root()
    config_path = os.path.join(root, "config", "global_config.yaml")
    
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        sys.exit(1)
        
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        
    # 2. Load Session File
    if not os.path.exists(args.file):
        print(f"Error: Session file not found at {args.file}")
        sys.exit(1)
        
    with open(args.file, "r") as f:
        session = json.load(f)
        
    # 3. Extract Tactical Parameters
    try:
        symbol = session["observation"]["symbol"]
        tactical = session["final_decision"]["tactical_parameters"]
        entry = tactical["entry"]
        sl = tactical["stop_loss"]
        opinion = session["final_decision"]["opinion"]
    except KeyError as e:
        print(f"Error: Could not find required field {e} in session file.")
        sys.exit(1)
        
    # 4. Get Symbol Specific Config
    sys.path.insert(0, resolve_project_root())
    try:
        from src.config.symbol_resolver import get_symbol_trade_params, is_symbol_configured

        risk_per_trade = config["trade_management"]["risk_per_trade"]

        if not is_symbol_configured(symbol):
            print(f"Error: Symbol {symbol} not configured in symbol_config.yaml.")
            sys.exit(1)

        sym_cfg = get_symbol_trade_params(symbol)
        p_qty = sym_cfg["precision_qty"]
        min_qty = sym_cfg.get("min_order_qty", 0.0)
    except KeyError as e:
        print(f"Error: Could not find required field {e} in global_config.yaml.")
        sys.exit(1)
        
    # 5. Calculation Logic
    try:
        target_qty, final_qty = calculate_sized_qty(args.balance, risk_per_trade, entry, sl, p_qty, min_qty)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
        
    equity = args.balance
    max_loss = equity * risk_per_trade
    price_delta = abs(entry - sl)
    
    total_notional = final_qty * entry
    leverage = total_notional / equity if equity > 0 else 0
    
    # 6. Output Summary
    print("\n" + "="*50)
    print(f" QUANTITY CALCULATION: {symbol}")
    print("="*50)
    print(f" Session File: {os.path.basename(args.file)}")
    print(f" Opinion:      {opinion}")
    print(f" Entry Price:  {entry:,.2f}")
    print(f" Stop Loss:    {sl:,.2f}")
    print(f" Delta (Pts):  {price_delta:,.2f} ({ (price_delta/entry*100):.2f}%)")
    print("-" * 50)
    print(f" Equity (USDT): ${equity:,.2f}")
    print(f" Risk per Trade: {risk_per_trade*100:.2f}%")
    print(f" Max Allowed Loss: ${max_loss:,.2f}")
    print("-" * 50)
    print(f" RAW Target Qty:  {target_qty:.8f}")
    print(f" PRECISION (qty): {p_qty}")
    print(f" FINAL SIZED QTY: {final_qty:.{p_qty}f}")
    print("-" * 50)
    print(f" Total Notional: ${total_notional:,.2f}")
    print(f" Actual Leverage: {leverage:.2f}x")
    print("=" * 50 + "\n")

if __name__ == "__main__":
    main()
