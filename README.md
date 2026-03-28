# 🛡️ Strategic Alpha Ledger: The Forensic Trading Machine

> **“不预测行情，只测绘逻辑。”**

这是一个基于 **物理真相 (Physic Truth)** 与 **对抗性演化 (Adversarial Evolution)** 构建的多智能体交易系统。它通过“三路推理 (Reasoning Triad)”架构，将极度不确定的市场博弈转化为确定性的物理地形测绘与逻辑审计。每一笔交易都是对市场脆弱性的精确爆破。

---

## 🌐 物理地形与多向演化全景 (The Physical & Evolutionary Panorama)

系统通过 **前向逻辑推理 (Forward Reasoning)** 与 **后向法医演化 (Backward Forensic Evolution)** 构建了一个具备自我修复能力的闭环生态：

```mermaid
graph TD
    subgraph "Forward Logic: The Reasoning Triad"
        A["Observer: Map Maker"] -->|"Topographical Map"| B("Strategist: Architect")
        B -->|"Draft Plan"| C{"Middleware: Math Gate"}
        C -->|"Physical Fact Check"| D["Critic: Adversary"]
        D -->|"Audit Verdict"| E("Strategist: Awakened")
        E -->|"Hardened Decision"| F("Actionable Strategy")
    end

    subgraph "Backward Evolution: The Forensic Loop"
        F -->|"Execution Log"| G["Reviewer: Coroner"]
        G -->|"Forensic Report"| H["Coach: Geneticist"]
        H -->|"Diagnosis & Patch"| I["Prompt Evolution"]
        I -->|"Inject Intelligence"| B
        I -->|"Inject Constraints"| D
    end

    style C fill:#f96,stroke:#333,stroke-width:2px
    style F fill:#00ff00,stroke:#333,stroke-width:2px
    style I fill:#f9f,stroke:#333,stroke-width:4px
```

---

## 🧬 逻辑博弈：多智能体审计与共识协议 (Multi-Agent Consensus & Audit Protocol)

系统各组件通过确定的物理边界与逻辑主权，确保每一棒交接都具备“法医级”的严谨性：

| 角色 | 职能 (Identity) | 核心生产逻辑 (Core Logic) | 产出物 (Output) |
| :--- | :--- | :--- | :--- |
| **Observer** | **测绘师** | **景观聚合**：识别宏微观地形 Confluence，计算趋势强度。 | 物理地形快照 (Observation) |
| **Strategist (A)** | **设计师** | **构思逻辑**：寻找 HVN 锚点，根据地形初步设计入场轨迹。 | 决策草案 (Draft Plan) |
| **Middleware** | **校验门** | **物理公证**：计算确定性 RR 与 ATR 距离，强制抹除 LLM 幻觉。 | 数学事实 (Math Fact Check) |
| **Critic** | **审判官** | **对抗审计**：基于《怀疑论》进行压力测试，识别吸收陷阱。 | 审计标签 (Audit Verdict) |
| **Strategist (B)** | **觉醒者** | **风险收敛**：融合审计意见，执行 DLE 硬化或强制 NEUTRAL。 | 最终执行方案 (Final Decision) |
| **Reviewer** | **复盘官** | **尸检对比**：量化 PnL 效率，捕捉“逻辑与现实”的偏离。 | 法医复盘报告 (Forensic Report) |
| **Coach** | **遗传学家** | **进化合成**：识别系统性偏见，生成指令集 (Prompt) 优化方案。 | 演化补丁 (Prompt Patch) |

---

## 📊 跨域硬化：多尺度演化与缩放准则 (Spatio-Temporal Hardening & Scaling)

> [!IMPORTANT]
> **“持仓周期 (Holding Period)” 是系统的核心权重，而非简单的环境参数。** 调整持仓目标会导致系统产生“多阶维度”的偏移，必须配套以下硬化逻辑。

### 1. 缩放路线图 (Strategy Scaling Logic)
针对系统在 **“时间跨度周期对齐” (Temporal Alignment)** 上的局限性，提供如下缩放配置：

| 目标策略 | Macro / Micro | 核心改动 (Config) | 核心改动 (Prompt) |
| :--- | :--- | :--- | :--- |
| **Swing (1周内)** | 1h / 15m | `funding_lookback`: 168h | `min_temporal_efficiency`: 0.3 |
| **Position (1月内)**| **4h / 1h** | `resolution_bins`: 800+ | `Dynamic RR`: Trend >= 3.0x |
| **Logic (Scalp)** | 15m / 1m | `wick_skew_period`: 1 | `confidence`: High Fill Priority |

### 2. 多维审计要点 (Deep Audit Points)
*   **物理几何崩溃**: 当 `macro_interval` 拉长至周/月级别时，分桶数 (Bins) 必须呈 **对数级增加**。否则，高成交量节点（墙）的厚度会吞没系统预留的止损缓冲区。
*   **线性公式失效**: `holding_time_hours` 的线性算法在月度持仓中会导致预测值脱靶。长线策略必须在 Prompt 中引入 **“波动率预期衰减”** 的权重。
*   **数据孤岛风险**: 对于长线级别，`fetch_liquidations` 无法捕获数周前的关键强平簇，必须通过本地持久化来对抗 API 数据丢失。

---

## 🛡️ 法医级防御：多维逻辑硬化盾牌 (The Forensic Hardening Shields)

为了确保系统在极高波动的加密市场中生存，我们部署了三层“逻辑护甲”：

### 第一层：物理事实真理网关 (Hallucination Killer)
禁止 AI 进行任何关键数学计算。由后端 Python 逻辑注入确定性的 RR (盈亏比)、ATR 距离与 Temporal Efficiency (时间效率)，作为 Critic 审计的唯一法定依据。

### 第二层：多模态视觉证伪体系 (Visual Anchoring)
所有的推理必须引用视觉快照 (Snapshot) 中的特征。AI 必须回答：“我看到了 K 线影线在 X 位置的阻力”，而非盲目信任数字，确立“单点真实来源”。

### 第三层：无状态递归相位侦测 (Deterministic State Machine)
策略师不再通过复杂的 Context 管理状态，而是直接递归检测 `Draft` 的存在。这使得 Prompt 保持静态且可预测，提升了分布式部署的稳定性。

---

## 🚀 运行手册 (Operational Manual)

项目采用模块化设计，覆盖从地形探测到演化修补的全流程。

### Phase 0: 部署与核心环境
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# 在 .env 中配置 API Keys
```

### Phase 1: 策略执行与回测验证
*   **单点实时预测**: `python3 strategist.py --symbol BTCUSDT prod`
*   **历史抽样回测**: `python3 backtest.py --sampling 12 --mode regime --start T-24d backtest`
*   **策略演化回放**: `python3 strategist_replay.py backtest --file [JSON_PATH]`

### Phase 2: 法医调查与看板分析
*   **法医报告生成**: `python3 reviewer.py prod`
*   **盲测复盘回放**: `python3 reviewer_replay.py prod --file [JSON_PATH]`
*   **策略逆向导出**: `python3 export_strategy.py [env] --file [REVIEW_JSON_PATH]`
*   **可视化看板**: `python3 forensic_dashboard.py --symbol BTCUSDT [env]`

### Phase 3: 自动化演化循环
*   **全自动化编排**: `python3 pipeline_orchestrator.py --symbol BTCUSDT --interval 1 live`
*   **诊断与进化合成**: `python3 coach.py --symbol BTCUSDT [prod|live|backtest]`
*   **应用逻辑补丁**: `python3 apply_patch.py --file [PATCH_JSON_PATH]`

---

## ⚖️ 我们的哲学

系统不通过“预测”未来获利，而是通过“**精确测绘当前的逻辑陷阱**”获利。每一张单子都是物理事实与对抗性逻辑的结晶。
