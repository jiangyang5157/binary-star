# Strategic Alpha Ledger: Multi-Agent Trading & Evolution System

这是一个基于多智能体（Multi-Agent）协作的加密货币交易预测与系统演化框架。它通过将“物理金融事实”与“对抗性逻辑审计”相结合，构建了一个具备自我进化能力的高度稳健交易系统。

---

## 🏗 项目架构：物理锚定与闭环演化

系统通过“测绘、分相决策、对抗审计、复盘反馈”构建了一个严密的逻辑闭环。全线 Agent 基于统一的 `BaseAgent` 基类构建，确保了多模态数据处理、JSON 解析与错误处理的高度一致性：

| 阶段 | 核心 Agent / 组件 | 物理/逻辑内涵 | 核心防御逻辑 |
| :--- | :--- | :--- | :--- |
| **1. 景观测绘** | **Observer (观察员)** | 宏微观 Topography 多模态测绘 | 结合 K 线图与量价指标，输出 `conviction_score` (信号汇聚度) 过滤低质量噪声。 |
| **2. 分相决策** | **Strategist (策略师)** | **PHASE A: DRAFTING** (初始方案) | 静态 Prompt 状态检测。强制 SL 隐藏在 POC/VAH/VAL 之后，确保逻辑不处于“真空区”。 |
| **3. 物理校验** | **Middleware (计算网关)** | 确定性数学事实 (Math Fact Check) | 后端计算真实的 RR、ATR 距离与持仓时间，消除 LLM 幻觉，注入后续审计。 |
| **4. 对抗审计** | **Critic (审计员)** | 对抗性风险侦测 (Adversarial Audit) | 基于物理因子校验止损缓冲区，识别吸收陷阱 (Absorption Trap) 与扫损风险。 |
| **5. 决策合成** | **Strategist (策略师)** | **PHASE B: SYNTHESIS** (决策收敛) | 结合审计反馈进行风险硬化，根据 `CONFIDENCE CALIBRATION LAW` 调整最终信心分。 |
| **6. 复盘进化** | **Reviewer (复盘官)** | 离线取证与 PnL 效率审计 | 通过历史多模态资产比对，量化“逻辑溢价”与“确定性偏见”。 |

---

## 🧬 核心硬化机制 (Hardening Protocols)

### A. 物理真相网关 (The Middleware Computation Gate)
这是系统防御“AI 幻觉”的核心。代理不再负责复杂的金融计算，所有关键指标在后端计算并注入：
*   **确定性盈亏比 (RR)**：不再信任 Agent 的自我计算，以物理坐标点为唯一准则。
*   **结构化缓冲区 (Structural Buffer)**：强制审计止损位到最近结构墙（如 POC）的有效距离。
*   **动态时间窗口 (Temporal Gate)**：根据波动率 (ATR) 与趋势强度自动投影成交有效时长，防止过度持仓。

### B. 高分辨率信心评分 (Precision Scoring Protocol)
系统强制要求 Agent 进行“精细化打分”：
*   **去整数化偏见**：禁止使用粗颗粒度的 50/65/75 分，要求根据信号共振程度给出如 67% 或 72% 的确切分数。
*   **加权负向反馈**：通过 `CONFIDENCE CALIBRATION LAW`，任何为规避风险而采取的“深层挂单 (DLE)”必须同步导致信心分的折损。

### C. 多模态视觉证伪 (Visual Counter-Evidence)
系统不只听取数据，更“看见”市场：
*   **图表注入**：Observer、Strategist 与 Reviewer 共享一致的图表快照 (Visual Assets)，AI 必须在 Reasoning 中引用图表的视觉特征（如阻力位、影线长度）进行证伪，确立“单点真实来源”。

### D. 无状态感知侦测 (Recursive State Detection)
Strategist 放弃了脆弱的正则匹配逻辑，通过上下文数据（`draft_plan` 是否为 null）自动感知执行相位。这使得 Prompt 永远保持 static，极大地增强了系统的鲁棒性与可维护性。

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

### 执行复盘 (Reviewer Pipeline)
量化历史决策的 MFE/MAE 表现与真实盈亏：
```bash
python3 reviewer.py --data_root data/live
```

### 取证回放 (Forensic Replay)
对特定历史观测点进行全链路推理复现：
```bash
python3 strategist_replay.py --data_root data/test --file data/test/observations/your_file.json
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
