# Crypto Dual-Agent Trading System

A sophisticated crypto trading analysis system using a Two-Agent architecture (Trader & Reviewer) powered by Gemini's Multimodal AI and Volume Profile analysis.

## Overview

The system operates in a feedback loop:
1.  **Agent A (The Trader)**: Analyzes real-time market data and Volume Profile charts to make 1-14 day swing trading predictions.
2.  **Agent B (The Reviewer)**: Periodically reviews past predictions against actual market outcomes, identifying logical flaws and suggesting "Logic Patches" or configuration tweaks.

## Features

- **Volume Profile Analysis**: Automatic calculation of POC (Point of Control), VAH (High), and VAL (Low).
- **Dual-Timeframe Analysis**: Simultaneous analysis of **4h (Macro)** for structure and **1h (Micro)** for entry precision.
- **Multimodal AI**: High-resolution dual-chart analysis using Gemini Flash.
- **Automated Alerts**: Email notifications for high-confidence signal (>85%).
- **Centralized Scheduler**: Orchestrates periodic prediction and review runs.
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
Outputs are saved to `data/raw/predictions/` and charts to `data/images/`.

### 2. Review Past Performance (Agent B)
```bash
python reviewer_main.py
```
Analyzes all pending predictions and saves reviews to `data/raw/reviews/`.

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
