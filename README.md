# Strategic Alpha Ledger: Multi-Agent Trading & Evolution System

这是一个基于多智能体（Multi-Agent）协作的加密货币交易预测与系统演化框架。它不仅能进行实时的市场预测，还能通过后置审计（Forensic Audit）不断自我进化。

---

## 🏗 项目架构：闭环演化系统

系统通过“对抗性决策 + 物理校验 + 周期性演化”构建了一个高度透明且具备自我进化能力的闭环：

| 阶段 | 核心组件 | 物理/逻辑动作 | 演化价值 |
| :--- | :--- | :--- | :--- |
| **1. 决策层 (Execution)** | Observer + Strategist | 宏微观测绘 -> 方案草拟 | 生成具备原始态势感知、带盈亏比预期的市场切片。 |
| **2. 校验层 (Verification)** | Middleware + Critic | 数学事实校验 (Math Fact Check) -> 对抗审计 | 消除 AI 逻辑幻觉，确保止损与时间窗口具备物理真实性。 |
| **3. 存档层 (Forensics)** | Forensic Repo | 全量决策（含被否决项）存档 | 提供完整的决策心理链路与 Veto (否决) 现场供事后追溯。 |
| **4. 审计层 (Audit)** | Reviewer | PnL / MFE / MAE 真实数据回溯 | 将理论决策与市场真实反馈进行对标，量化系统偏差。 |
| **5. 演化层 (Evolution)** | Coach | 批量诊断 (Batch Analysis) -> 逻辑突变 | 识别系统性偏向（如过于保守或冒险），生成 Prompt 补丁。 |

### 📡 实时通知与观测 (Observability)
系统不只是一个黑盒，它通过 **Email Notifier** 将每一场博弈的细节实时推送给用户：
*   **高保真 HTML 报告**：内置深度优化的排版（适配移动端与 Web），将复杂的策略参数（入场/止损/持仓时间）以表格形式直观呈现。
*   **物理校验透明化**：通知中会直接展示 **Math Fact Check** 的比对结果，让用户一眼识破 AI 是否在特定行情下产生了计算偏移。
*   **博弈现场还原**：每一份邮件都会包含审计员 (Critic) 的具体否决理由或硬化建议，帮助用户理解系统当前的风险偏好。

### 🔍 核心机制深度解析

#### A. 物理真实锚点 (The Middleware Gate)
这是系统中最关键的非 AI 模块。在每一份策略草案生成后，中间件会直接从底层 K 线提取 **ATR (波动率)**、**CVD (成交量累积)** 等硬性指标，并计算出该策略真实的 **盈亏比 (RR)** 和 **持仓时间 (Holding Time)**。这组数据被强制注入审计流程，作为衡量 AI 决策是否“脱离物理现实”的唯一标尺。

#### B. 双向决策博弈 (Bifurcation Protocol)
审计员 (Critic) 并不只是简单的“过滤器”。在面对高风险环境（如 LS Ratio 极端失衡）时，审计员会提出 **硬化（Hardening）** 建议，例如将传统的支撑位入场改为“深层限价单 (DLE)”。策略师必须采纳这些对抗性建议并重新计算数学逻辑；若修正后的 RR 无法达标，该单据将被强制转为 `NEUTRAL`。

#### C. 由于实战驱动的演化 (Evolutionary Mutation)
`Coach` 模块通过分析多份历史审计报告，对比 **“审计员的担忧”** 与 **“市场的真实走势”**。
*   如果市场并未发生审计员担心的风险（判读过严），Coach 会建议释放更多探索空间。
*   如果市场反复触发了被忽略的微观信号（判读过松），Coach 会生成对应的逻辑补丁，直接修改 Agent 的提示词（Prompts）或配置（Configs），实现系统的动态进化。

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
python3 backtest.py --sampling 12 --mode regime --start T-24d --data_root data/backtest
```
*`--mode regime` 会自动分析市场环境（震荡/趋势）进行分层抽样，确保策略在不同波段下的稳健性。*

```bash
python3 backtest.py --sampling 12 --mode spaced --start T-24d --data_root data/backtest
```
*`--mode spaced` 采用等距时间抽样，适合对系统每天的常规表现进行“体检”式扫描。*

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
