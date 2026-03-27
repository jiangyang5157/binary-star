# Strategic Alpha Ledger: Multi-Agent Trading & Evolution System

这是一个基于多智能体（Multi-Agent）协作的加密货币交易预测与系统演化框架。它通过将“物理金融事实”与“对抗性逻辑审计”相结合，构建了一个具备自我进化能力的高度稳健交易系统。

---

## 🏗 项目架构：物理锚定与闭环演化

系统通过“观察、决策、审计、反馈”构建了一个严密的逻辑闭环，确保每一笔交易都具备深层的结构化支撑：

| 阶段 | 核心 Agent / 组件 | 物理/逻辑内涵 | 核心防御逻辑 |
| :--- | :--- | :--- | :--- |
| **1. 景观测绘** | **Observer (观察员)** | 宏微观 Topography 测绘 | 输出 `conviction_score` (信号汇聚度) 过滤低质量噪声。 |
| **2. 方案起草** | **Strategist (策略师)** | 结构化锚定 (Structural Anchoring) | 强制 SL 隐藏在 POC/VAH/VAL 之后，确保逻辑不处于“真空区”。 |
| **3. 物理校验** | **Middleware (计算网关)** | 确定性数学事实 (Math Fact Check) | 后端计算真实的 RR、ATR 距离与持仓时间，消除 LLM 幻觉。 |
| **4. 对抗审计** | **Critic (审计员)** | 对抗性风险侦测 | 检查 SL 缓冲区是否符合物理分布，识别吸收陷阱 (Absorption Trap)。 |
| **5. 绩效评价** | **Reviewer (复盘官)** | 真实 PnL 与效率审计 | 对比 MFE/MAE 与原始预期，量化系统预测的“溢价”。 |
| **6. 逻辑突变** | **Coach (教练)** | 批量诊断与 Prompt 补丁生成 | 识别持续性偏见，通过修改 Prompts 实现系统的动态进化。 |

---

## 🧬 核心硬化机制 (Hardening Protocols)

### A. 物理真实网关 (The Middleware Computation Gate)
这是系统防御“AI 幻觉”的核心。在策略草案生成后，中间件直接在后端计算物理数据并注入审计流程：
*   **确定性盈亏比 (RR)**：不再信任 Agent 自己的数学计算，而是以物理坐标点为准。
*   **结构化缓冲区 (Structural Buffer)**：强制审计止损位到最近结构墙（如 POC）的 ATR 距离。若止损位暴露在“流动性真空区 (LVN)”，则直接否决。
*   **动态时间窗口 (Temporal Gate)**：根据当前波动率 (ATR) 与趋势强度 (Trend Intensity) 自动投影合理的成交与持仓时长。

### B. 语义一致性协议 (Semantic Consistency Protocol)
为了确保多智能体协同不产生歧义，系统严格执行以下语义标准：
*   **影线偏好 (Wick Skewness)**：全系统统一方向——负值代表下长影线（看涨信号/吸筹），正值代表上长影线（看跌信号/派发）。
*   **属性对齐**：所有 Agent 使用相同的 `vol_breakout`、`ls_ratio` 和 `cvd_trend` 定义，确保决策链路中数据不因命名冲突而丢失。
*   **中性绕过 (Neutral Bypass)**：当系统选择 `NEUTRAL` (弃权) 时，会自动旁路所有数学审计规则，确保“清白且安全”的 surrenders 不产生误报。

### C. 双向对抗博弈 (Bifurcation Protocol)
审计员 (Critic) 拥有“一票否决权”和“方案硬化建议权”。如果审计员识别出潜在的流动性扫损风险，它会强制策略师采纳 **深层限价 (DLE)** 建议。策略师必须重新计算深层入场后的数学模型；若此时盈亏比不再达标，系统将不得不放弃该机会，实现真正的“宁可错过，不可投机”。

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

### 2. 实盘运行 (Live Pipeline)
使用编排器启动自动化预测和审计循环：
```bash
python3 pipeline_orchestrator.py --symbol BTCUSDT --data_root data/live --interval 1
```

### 3. 历史回测 (Backtest)
在历史数据上测试策略生成与审计链路的稳健性：
```bash
# Regime 模式：自动识别市场分层（震荡/趋势）进行均衡抽样
python3 backtest.py --sampling 12 --mode regime --start T-24d --data_root data/backtest

# Spaced 模式：采用等距时间抽样，适合对系统表现进行日常体检
python3 backtest.py --sampling 12 --mode spaced --start T-24d --data_root data/backtest
```

---

## 🔍 取证与可视化 (Forensics)

### 执行审计 (Manual Review)
手动触发对已生成策略的执行结果审核，量化 PnL 与 MFE/MAE 表现：
```bash
python3 reviewer.py --data_root data/live
```

### 生成可视化看板 (Forensic Dashboard)
生成交互式 HTML 看板，查看置信度分布、盈亏曲线及模型效能：
```bash
python3 forensic_dashboard.py --data_root data/live --symbol BTCUSDT
```
*结果保存在 `data/live/html/` 目录下。*

---

## 🛠 数据驱动演化 (The Coach Loop)

当积累了足够的审计报告后，可以让系统自我生成优化方案：

1.  **诊断并生成补丁 (Diagnosis & Patch)**：
    ```bash
    python3 coach.py --data_root data/live --symbol BTCUSDT
    ```
2.  **应用补丁 (Apply Patch)**：
    ```bash
    python3 apply_patch.py --file data/live/reviewers/archived/BTCUSDT_patches_YYYYMMDD_HHMMSS.json
    ```
    *注意：为保证安全，所有 Patch 必须经人确认后手动应用。*

---

## ⚖️ 核心理念
**“不预测行情，只测绘逻辑。”** 本项目坚持物理真相 (Physic Truth) 高于 AI 推理，通过确定性的数学网关为极其不确定的金融市场提供了一份可复用的“决策地图”。
