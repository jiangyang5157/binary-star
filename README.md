# Crypto Dual-Agent Trading System

A sophisticated crypto trading analysis system using a Two-Agent architecture (Trader & Reviewer) powered by Gemini's Multimodal AI and Volume Profile analysis.

## Overview

The system operates in a feedback loop:
1.  **Agent A (The Trader)**: Analyzes real-time market data and Volume Profile charts to make periodic swing trading predictions (window configurable in `config/config.yaml`).
2.  **Agent B (The Reviewer)**: Periodically reviews past predictions against actual market outcomes, identifying logical flaws and suggesting "Logic Patches" or configuration tweaks.

## Features

- **Volume Profile Analysis**: Automatic calculation of POC (Point of Control), VAH (High), and VAL (Low).
- **Dual-Timeframe Analysis**: Simultaneous analysis of **4h (Macro)** for structure and **1h (Micro)** for entry precision.
- **Multimodal AI**: High-resolution dual-chart analysis using Gemini Flash.
- **Automated Alerts**: Email notifications for high-confidence signal (>85%).
- **Centralized Scheduler**: Orchestrates periodic prediction and review runs.
- **Historical Backtesting**: Sampling-based simulator that identifies market regimes and runs backtests without hitting API quotas.
- **Prompt Versioning**: Tracks "Logic Drift" by hashing prompt state in results.

## Installation

1.  **Clone the repository**.
2.  **Create a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
3.  **Setup Environment Variables**:
    Create a `.env` file in the root directory:
    ```env
    GEMINI_API_KEY=your_api_key_here
    ```

## Usage

### 1. Generate a Prediction (Agent A)
```bash
python main.py
```
- **Behavior**: Fetches real-time data, generates Volume Profile charts, and invokes the Gemini model.
- **Output**: JSON prediction in `data/raw/predictions/` and charts in `data/images/`.

### 2. Review Past Performance (Agent B)
```bash
python reviewer_main.py
```
- **Behavior**: Scans all predictions that haven't been reviewed yet. Fetches the *actual* market movement and evaluates performance.
- **Review Aging**: By default, it skips predictions less than 24 hours old (`reviewer_interval_hours` in config) to ensure the trade has played out.
- **Manual Force**: To bypass the 24-hour protection and test immediately:
  ```bash
  python reviewer_main.py --force
  ```

### 3. Historical Backtesting (Simulator)
```bash
python simulator.py [options]
```
- **Goal**: Rapidly iterate on prompts and configuration by sampling past market regimes.
- **Parameters**:
    - `--days <int>`: Lookback window in days (default: 365).
    - `--sampling <int>`: Number of distinct points to test (default: 20).
    - `--start <YYYY-MM-DD>`: Explicit start date (overrides --days).
    - `--end <YYYY-MM-DD>`: Explicit end date (defaults to now).
- **Example**: `python simulator.py --start 2024-01-01 --sampling 10`

### 4. Automated Scheduler (Orchestrator)
```bash
python scheduler.py
```
- **Behavior**: Runs in an infinite loop. Triggers `main.py` every 1 hour and `reviewer_main.py` every 24 hours (configurable in `config/config.yaml`).
- **Startup**: It **immediately** runs both scripts once upon startup to ensure your data is fresh.
- **How to Stop**: Press `Ctrl + C` in the terminal to terminate the scheduler.
- **Logs**: View `automation.log` for execution history.

## Project Structure

- `src/agent/`: AI Agent implementations and prompts.
- `src/analyzer/`: Technical indicators (Volume Profile) and chart generation.
- `src/data_fetcher/`: Binance API integration and data storage.
- `config/`: Main system configuration.
- `data/`: Local storage for raw market data, images, and AI records.

## How to Interpret Decisions

Agent A outputs a `confidence` score (0-100) representing the alignment of multiple signals.

### Confidence Thresholds
- **85% - 100% (High Conviction)**: 🔥 **High Trade Quality.** Major confluences reached: 4h structure alignment, 1h entry confirmation (retests/wicks), and sentiment backing (OI/LS Ratio).
- **75% - 84% (Moderate)**: ⚖️ **Wait for better entry.** Trend is likely correct, but micro-timing or sentiment may be slightly misaligned. Consider limit orders at key VAH/VAL/POC levels.
- **Below 75% (Low)**: 🧊 **Noise/Consolidation.** Mixed signals or price is churning inside the Value Area without a clear edge.

> [!TIP]
> **The Golden Setup**: Look for `confidence > 88%` where the price is within **0.5%** of a major Volume Profile level (VAH/VAL/POC). This offers the highest Risk/Reward ratio.

## Maintenance & Prompt Iteration

To keep the system evolving without logic conflicts, follow these guidelines when applying Agent B's suggestions:

### 1. Managing Prompt Patches
When Agent B suggests a `prompt_patch_suggestion`:
- **Don't just Append**: Instead of blindly adding to the end, read the existing rules in `src/agent/prompts/prompt_trader.txt` under the `## Refined Execution Logic` section.
- **Merge or Replace**: If a new suggestion clarifies an old one (e.g., "Always buy breakouts" vs "Buy breakouts ONLY if Volume is high"), **replace** the old rule with the more specific one.
- **Add Context**: Ensure every rule has a condition (e.g., "In low volatility...", "When OI is dropping...").

### 2. Cleaning up the Prompt
- **The "肌肉记忆" Rule**: If Agent A has made 5 correct decisions in a row following a specific rule, you can consider moving that rule from the `Refined` section to the core `Instructions` or deleting it if the AI seems to have "learned" the pattern.
- **Keep it Lean**: Aim to keep the `Refined Execution Logic` section under 10 bullet points to avoid overwhelming the model's context window.

### 3. Updating Configuration
- If Agent B suggests a `config_update_suggestion` (e.g., changing timeframe or `value_area_pct`), manually update `config/config.yaml`. 
- **Tip**: Change only one parameter at a time and run for a few days to see the impact.

## License
MIT
