# Crypto Dual-Agent Trading System

A cutting-edge crypto trading analysis framework utilizing a **Two-Agent Architecture** (Trader & Reviewer) and **Multimodal AI** to translate complex market data into actionable swing trading logic.

---

## 🧠 How it Works

The system replicates a professional trading desk with two distinct roles:

1.  **Agent A (The Trader)**: 
    *   **Data Enrichment**: Combines live price action with Volume Profile (POC/VAH/VAL), Liquidations, and Sentiment (OI/LS Ratio).
    *   **Visual Logic**: Generates "enhanced" charts where technical indicators are overlaid as visual cues for the AI.
    *   **Decision**: Outputs high-probability trade setups with detailed reasoning.

2.  **Agent B (The Reviewer)**:
    *   **Outcome Evaluation**: Scans past predictions once the trade window has closed.
    *   **Gap Analysis**: Compares what the Trader *thought* would happen against what *actually* happened.
    *   **Logic Patching**: Suggests specific "patches" (new prompt rules) or configuration tweaks to fix recurring mistakes.

---

## 🛠 Setup & Installation

### 1. Environment Requirements
*   Python 3.8+
*   Binance Account (API Keys required for full functionality)
*   Gemini API Key (Google AI Studio)

### 2. Installation
```bash
# Clone the repo and enter the directory
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration
1.  **API Keys**: Create a `.env` file in the root:
    ```env
    GEMINI_API_KEY=your_google_key
    BINANCE_API_KEY=your_binance_key
    BINANCE_API_SECRET=your_binance_secret

    # Notifications (Required for email alerts)
    SENDER_EMAIL=your_gmail_address
    SENDER_APP_PASSWORD=your_gmail_app_password
    ```
2.  **Strategy**: Centralized configuration is in `config/config.yaml`. This controls symbols, timeframes, and model selections.

---

## 🚀 Execution Guide

### 1. Run a Single Analysis (Agent A)
To generate a prediction for the current market state:
```bash
python main.py
```
*   **Input**: Real-time market data.
*   **Output**: JSON prediction in `data/raw/predictions/` and technical charts in `data/images/`.

### 2. Run Performance Review (Agent B)
To evaluate past trades and generate logic patches:
```bash
python reviewer_main.py
```
*   **Aging Protection**: By default, the system follows `minimum_review_age_hours` in `config.yaml` (defaulting to 168 hours/7 days). This ensures trades have time to "play out" before they are judged.
*   **Force Flag**: To bypass this protection and review all predictions immediately (e.g., for testing):
  ```bash
  python reviewer_main.py --force
  ```

### 3. Automated Operation (The Scheduler)
To run the analysis and review cycle automatically in the background:
```bash
python scheduler.py
```
*   **Cycle**: Triggers Trader analyses and Reviewer passes based on intervals set in `config.yaml`.
*   **How to stop**: Simply press **`Ctrl + C`** in your terminal.

### 4. Backtesting & History (The Simulator)
Test your prompts against historical market regimes without waiting weeks:
```bash
python simulator.py --days 30 --sampling 15 --mode regime
```
*   **Arguments**:
    *   `--symbol`: The asset to test (e.g., `BTCUSDT`). Defaults to config setting.
    *   `--days`: Number of days to look back (default: 30).
    *   `--start YYYY-MM-DD`: Start date for backtest (overrides `--days`).
    *   `--end YYYY-MM-DD`: End date for backtest (defaults to now).
    *   `--sampling`: Total number of historical snapshots to pick (default: 15).
    *   `--mode`: Sampling strategy.
        *   `regime` (default): Picks snapshots randomly across different market phases (Bull/Bear/Sideways).
        *   `spaced`: Picks snapshots at even intervals across the time range.

---

## 📊 Interpreting Results

The system assigns a **Confidence Score** (0-100) to each trade:

*   **85% - 100% (High Conviction)**: 🔥 **Strategic Alignment.** Macro structure (1d), Micro entry (4h), and Sentiment (OI) are all in agreement.
*   **75% - 84% (Moderate)**: ⚖️ **Monitor Closely.** Good direction, but timing or volume profile support might be sub-optimal.
*   **Below 75% (Low)**: 🧊 **Neutral/Avoid.** Market is likely in churn or consolidation within the Value Area.

---

## 📂 Project Roadmap
- [x] **Phase 1**: Core Two-Agent Cycle & Volume Profile.
- [x] **Phase 2**: Visual AR (Augmented Reality) Charts & Liquidation zones.
- [ ] **Phase 3**: Expert Gallery (Few-shot learning for AI).
- [ ] **Phase 4**: Multi-Model "Council of Judges" consensus.

---
## License
MIT

