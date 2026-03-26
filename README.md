# Strategic Alpha Ledger: Multi-Agent Trading & Evolution System

这是一个基于多智能体（Multi-Agent）协作的加密货币交易预测与系统演化框架。它不仅能进行实时的市场预测，还能通过后置审计（Forensic Audit）不断自我进化。

---

## 🏗 项目架构：闭环演化系统

系统由四大核心模块构成，形成了一个可持续改进的“决策-审计-进化”闭环：

1.  **观察与决策 (Observer & Strategist)**: 捕捉市场瞬时状态，生成带置信度的交易策略。
2.  **法医审计 (Reviewer)**: 在交易完成后（或到达预定时间），自动回溯市场数据，判定预测准确度并记录 MAE/MFE 等核心指标。
3.  **系统反馈 (Forensic Dashboard)**: 将审计结果可视化，展示置信度与胜率的关联，帮助定位系统薄弱环节。
4.  **自我进化 (Coach & Evolution)**: Coach 智能体分析审计报告，提炼优化方案并生成补丁（Patches）；补丁应用后直接更新 Agent 的 Prompt 或配置。

---

## 🚀 快速开始

### 1. 环境准备
确保已安装 Python 3.9+ 并配置虚拟环境：
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
在 `.env` 文件中配置您的 `GEMINI_API_KEY` 和 `BINANCE_API_KEY`。

### 2. 实盘预测任务 (Live Pipeline)
使用编排器启动自动化预测和审计循环：
```bash
python3 pipeline_orchestrator.py --symbol BTCUSDT --data_root data/live --interval 1
```
*`--interval` 指定每隔多少小时运行一次。*

### 3. 历史回测 (Backtest)
在历史数据上测试策略生成能力：
```bash
python3 backtest.py --sampling 10 --mode regime --start T-30d --data_root data/backtest
```
*`--mode regime` 会自动分析市场环境（震荡/趋势）进行分层抽样。*

---

## 🔍 审计与可视化 (Forensics)

### 执行审计
手动触发对已生成策略的执行结果审核：
```bash
python3 reviewer.py --data_root data/live
```

### 查看看板
生成交互式 HTML 看板，查看置信度分布、PnL 趋势及模型效能：
```bash
python3 forensic_dashboard.py --data_root data/live --symbol BTCUSDT
```
*结果保存在 `data/live/html/` 目录下。*

---

## 🛠 系统进化 (The Coach Loop)

当积累了足够的审计报告后，可以让系统自我优化：

1.  **生成优化补丁**：
    ```bash
    python3 coach.py --data_root data/live --symbol BTCUSDT
    ```
    生成的补丁文件将保存在 `reviewers/archived/` 目录下，带有时戳。

2.  **应用补丁**：
    ```bash
    python3 apply_patch.py --file data/live/reviewers/archived/BTCUSDT_patches_YYYYMMDD_HHMMSS.json
    ```
    *注意：必须手动指定补丁文件路径以确保安全。*

---

## 📂 数据结构说明

*   `strategies/`: 存放 Strategist 生成的原始决策。
*   `reviewers/`: 存放 Reviewer 生成的审计报告。
*   `reviewers/archived/`: 存放已处理过的历史报告及演化补丁（Patches）。
*   `html/`: 存放可视化看板。
*   `config/`: 存放智能体核心提示词（Prompts）与全局配置。

---

## ⚖️ 核心理念：确定性演化
本项目坚持**手动应用补丁**的原则，所有 Coach 生成的优化方案必须经人确认后方可应用，确保系统演化方向受控、安全、透明。
