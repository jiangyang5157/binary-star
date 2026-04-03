# 🌌 Singularity Session Engine (v6.1)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

> **"Trading is not a game of predicting the future; it is a game of surviving the present."**
> 
> Singularity is a multi-agent quantitative architecture that eliminates human bias through **Adversarial Reasoning**. It doesn't just "guess" where the price goes—it puts every trade on trial before a single dollar is risked.

---

## ⚖️ System Design: The Adversarial Courtroom

Singularity operates like a high-stakes courtroom trial. A trade only moves from an idea to an execution if it survives a rigorous cross-examination.

### 1. 📂 The Witness (Market Observer)
*   **Role**: Gathers the physical facts.
*   **Action**: Scans the market's "topography"—identifying where the big money is sitting (Volume Profile), how fast the price is moving (Volatility), and who is in control (CVD Sentiment).
*   **The Truth**: It generates a "Market Map" which is the only source of truth for the entire session.

### 2. 🛡️ The Defense (Session Analyst)
*   **Role**: Proposes a "Thesis" (The Trade).
*   **Action**: Looks at the facts and argues: *"We should go Long at 66,500 because we are at a major support level."*
*   **Creativity**: It uses tactical intelligence to find the best entry points (DLE) to maximize safety and profit.

### 3. 🔍 The Prosecution (Skeptical Critic)
*   **Role**: The Logical Auditor.
*   **Action**: Its only job is to **find holes** in the Session Analyst's plan. It looks for "Structural Traps," "Retail Squeezes," and "Math Failures."
*   **The Veto**: If the plan is unsafe, it issues a **TERMINAL VETO**, effectively killing the trade to protect capital.

### 4. 📐 The Evidence (Math Fact Check)
*   **Role**: The Immutable Law.
*   **Action**: A cold, Python-based calculator that checks the agents' work. It verifies Risk-Reward ratios and support-level shielding with 100% mathematical precision.
*   **The Verdict**: The agents CANNOT argue with the Math Fact Check. It is the final word on physical reality.

---

## 🚀 Key Innovations

### 🛰️ The Truth Bus (Context Caching)
To prevent the AIs from "drifting" or seeing different realities, they are plugged into a shared **Truth Bus**. They share the exact same snapshot of the market, ensuring 100% logical convergence.

### 🔄 Polarity Pivot (The Counter-Strike)
If the Critic identifies a "Retail Squeeze" (everyone is going one way and a trap is set), the Session Analyst is instructed to perform a **Polarity Pivot**. Instead of just canceling the trade, it flips sides to hunt the very traders who are about to be trapped.

### 🧬 Meta-Evolution (The Feedback Loop)
After every session, the **Evolver** agent performs a forensic audit. It asks: *"Why did we lose?"* or *"Why did we hesitate?"* It then updates the system's "DNA" (Strategy Config) to ensure the system is smarter for the next market cycle.

---

## 🛠 Operation Manual

### 0.
`source venv/bin/activate`

### 1. Market Session (Live Analysis)
Analyze a specific symbol in real-time.
```bash
python run_session.py once --symbol BTCUSDT --data_root once
```
*   `--mode live`: Continuous polling mode for autonomous discovery.
*   `--email`: Sends high-conviction alerts directly to your inbox.

### 2. Forensic Audit (Review)
Review a specific session to see exactly why it succeeded or failed.
```bash
python run_audit.py --file data/once/sessions/BTCUSDT_session_TIMESTAMP.json
```

---

## 📖 Glossary for Non-Experts

| Term | In Plain English | Technical Meaning |
| :--- | :--- | :--- |
| **Topography** | The "Lay of the Land" | The relationship between price and volume levels. |
| **POC (Point of Control)** | The fair price | The level where the most trading occurred. |
| **HVN (High Volume Node)** | A "Fortress" | A price area with heavy historical trading (Support/Resistance). |
| **ATR (Volatility)** | The "Wind Speed" | How much the price usually moves in a given time. |
| **Squeeze** | A "Coiling Spring" | When the market is quiet, anticipating a violent breakout. |
| **DLE (Deep Entry)** | Buying the "Dip" | Placing an entry deep into a support zone for safety. |

---