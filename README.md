# Crypto Dual-Agent Trading System

A sophisticated crypto trading analysis system using a Two-Agent architecture (Trader & Reviewer) powered by Gemini's Multimodal AI and Volume Profile analysis.

## Overview

The system operates in a feedback loop:
1.  **Agent A (The Trader)**: Analyzes real-time market data and Volume Profile charts to make 1-14 day swing trading predictions.
2.  **Agent B (The Reviewer)**: Periodically reviews past predictions against actual market outcomes, identifying logical flaws and suggesting "Logic Patches" or configuration tweaks.

## Features

- **Volume Profile Analysis**: Automatic calculation of POC (Point of Control), VAH (Value Area High), and VAL (Value Area Low).
- **Multimodal AI**: High-resolution chart analysis using Gemini Flash.
- **Sentiment Integration**: Fetches Open Interest, Long/Short ratios, and Funding Rates.
- **Self-Optimization**: Agent B provides actionable feedback to improve Agent A's prompts over time.

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

## License
MIT
