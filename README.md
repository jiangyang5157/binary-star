# 🌌 Singularity 跨代交易会话引擎 (v6.5)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

> **"交易不是预测未来的游戏，而是生存于当下的博弈。"**
> 
> Singularity 是一个高保真、多智能体的量化架构，旨在通过 **对抗式推理 (Adversarial Reasoning)** 消除人类偏见。它能将复杂的市场混沌状态转化为冷静、确定性的执行指令。

---

## ⚖️ 系统设计：对抗式法庭

Singularity 的运作逻辑类似于一场高风险的法庭审判。一个交易提案只有在通过严苛的“交叉盘问”后，才能从假设变为实际执行。

### 🛡️ 推理三元组 (The Reasoning Triad)
1.  **📂 证人 (Market Observer)**：负责收集“物理事实”（成交量分布、ATR 波动率、CVD 情绪）。
2.  **🤺 辩方 (Session Analyst)**：提出“交易假设”（Temp 0.7 - 寻找创意 Alpha）。
3.  **🔍 控方 (Skeptical Critic)**：执行“否定审计”（Temp 0.2 - 逻辑硬化与风险识别）。

---

## 🛠 核心功能与技术模块

该平台提供了一套完整的端到端取证与优化流水线：

*   **⚡ 实时市场取证 (High-Fidelity Forensics)**：深度分析市场拓扑结构（支撑/阻力节点）和情绪强度（CVD/清算簇），构建确定性的分析语境。
*   **🔄 对抗式博弈协议 (Adversarial Debate)**：通过 Critic 智能体自动识别 Analyst 提案中的数学逻辑漏洞、结构性风险和情绪化偏见。
*   **🧪 自动化后期取证审计 (Post-Mortem)**：交易结束后，系统会自动比对“交易假设”与“实际市场物理走势”，识别是“合理的放弃”还是“灾难性的遗漏”。
*   **🧬 元进化 DNA 引擎 (Meta-Evolution)**：基于后期审计的反馈，由 Evolver 智能体自动更新系统的“DNA”（配置参数与提示词逻辑），实现自我进化。
*   **📊 专业级可视化报告**：生成交互式 HTML 仪表盘和执行账本，包含卡玛比率 (Calmar)、最大回撤 (MDD) 和权益增长曲线。

---

## 🌟 双子星系统 (Binary Star System): 深度逻辑与收敛机制

双子星系统是 Singularity 的心脏，旨在通过多智能体的对抗博弈，将模糊的市场状态收敛为高质量、高确定性的执行方案。

### 1. 核心架构：共享真理总线 (Shared Truth Bus)
为了防止智能体在推理过程中产生“逻辑漂移”，系统引入了 **Truth Bus**：
- **物理锚定**：基于 `observed_at` 的高精度时间戳（ISO-8601 Zulu），确保所有智能体共享同一秒的物理现实快照。
- **视觉一致性**：所有智能体同时观察完全相同的 Macro/Micro K 线图资产，消除数据非对称性。

### 2. 熵减过程：从混沌到高品质结果 (The Convergence Engine)
系统的决策逻辑是一个通过迭代不断硬化（Hardening）的过程：

```mermaid
graph TD
    A[市场原始状态: 波动率, 拓扑, 订单流] --> B{共享真理总线}
    B --> C[创意规划: Temp 0.7]
    C --> D[提案: 止损/止盈/切入点]
    D --> E[数学事实检查: 物理审计]
    E --> F[对抗审计: Critic 质疑]
    F --> G{质疑分阈值?}
    G -- 未通过 --> H[逻辑硬化: 回退到 C 重新精炼]
    G -- 通过 --> I[纪律合成: Temp 0.3]
    I --> J[高质量执行指令]
```

### 3. 温度差策略 (Temperature-Shift Strategy)
这是实现逻辑收敛的关键：
- **Planning (0.7)**：在博弈初期允许“创造性 Alpha”，激发寻找隐藏模式的潜能。
- **Synthesis (0.3)**：在达成逻辑共识后，强制进入“冷合成”模式，消除修辞干扰，只输出绝对确定的执行指令。

---

## 🌀 收敛引擎：从混沌到精准 (The Convergence Engine)

系统收敛是一个将庞大的市场熵提纯为单一、低风险执行点的过程，通过三层同步实现：

### 🔬 高保真时间锚定 (Temporal Anchoring)
通过标准化的 `observed_at` 时间戳体系，系统消除了“锚点漂移”。辩论中的每个智能体都清楚地知道彼此引用的具体 K 线、CVD 峰值或成交量节点，防止逻辑混乱。

### 🛡️ 质疑一票否决权 (The Quality Floor)
系统的目标不是“更多的交易”，而是“无可争议的交易”。如果在经过最大辩论轮次后，Critic 的 **质疑分 (Skepticism Score)** 仍高于阈值，系统将以 **Veto (否决)** 状态中止会话，从而在低确定性的环境下保护资本。

### 📐 物理真实性高于 AI 修辞 (Truth over Rhetoric)
系统对 AI 的数学计算实施 **零信任** 政策。每一轮提案中的盈亏比 (RR)、ATR 距离、止损缓冲区都会被 **Python 原生数学工具集** 重新审计。逻辑只有在物理细节与推理完全吻合时才会收敛。

---

## 🚀 核心创新

### 🛰️ 真理总线 (Context Caching)
防止智能体产生逻辑“漂移”，通过共享真理总线确保所有参与博弈的 AI 观察到的是完全同一维度的市场现实。

### 🧬 元进化反馈环 (Genetic Loop)
交易不再是孤立的。Evolver 智能体通过对审计报告的深度学习，动态调整策略参数，确保系统在下一个市场周期中更加聪明。

---

## 🛠 安装与操作手册

### 0. 环境准备
在运行任何脚本之前，请确保你的虚拟环境已激活：
```bash
source venv/bin/activate
```

### 1. 市场分析会话 (Live Session)
实时分析特定品种。
```bash
python run_session.py once --symbol BTCUSDT --data_root once
```

### 2. 取证审计 (Forensic Audit)
回顾特定会话，查明其成功或失败的深层原因。
```bash
python run_audit.py --file data/once/sessions/BTCUSDT_session_时间戳.json
```

### 3. 元进化 (DNA 进化)
分析取证报告，对系统逻辑和参数进行“基因突变”更新。
```bash
python run_evolution.py --samples 20
```

### 🏆 渐变式进化工作流 (The Triple Hardening Workflow)
推荐的高保真策略进化路径，分为三个阶段：

*   **阶段 A：宏观基准训练 (Baseline)**
    *   **目标**：建立跨越 14 天的宏观稳定性。
    *   **操作**：`python run_session.py backtest --start T-28d --end T-14d --sampling 12` -> 运行 `run_evolution.py`。
*   **阶段 B：近期律动适配 (Recency Adaptation)**
    *   **目标**：对齐最新的市场波动特性。
    *   **操作**：`python run_session.py backtest --start T-14d --end now --sampling 12` -> 在阶段 A 补丁基础上再次进化。
*   **阶段 C：极端案例加固 (Adversarial Hardening)**
    *   **目标**：针对前两个阶段所有的 **失败审计 (Failures)** 进行专项逻辑闭合。
    *   **操作**：筛选 `/audits` 中所有 `SL_HIT` 报告 -> 运行 `run_evolution.py --samples 10`。

### 4. 战术权益账本 (Strategy Ledger)
生成特定品种的交互式 HTML 表现看板。
```bash
python tools/session_ledger.py --symbol BTCUSDT --recursive
```

---

## 🏗 数据架构：黑盒目录

| 目录 | 用途 | 保留期限 |
| :--- | :--- | :--- |
| `data/once/sessions` | 原始智能体辩论日志及最终决策。 | 30 天 |
| `data/once/audits` | 针对止损或未触发机会的高保真取证报告。 | 永久 |
| `data/once/html` | 交互式表现仪表盘与权益曲线。 | 永久 |
| `data/once/evolution/proposals` | 生成的逻辑更新候选项 (JSON)。 | 永久 |
| `data/once/evolution/applied_patches` | 已成功合并并验证的逻辑补丁。 | 版本化 |

---

## 📖 术语库 (非专家指南)

| 术语 | 通俗解释 | 技术含义 |
| :--- | :--- | :--- |
| **拓扑 (Topography)** | “地形图” | 价格水平与成交量分布之间的空间关系。 |
| **POC (Point of Control)** | “公允价值” | 特定时间内成交量最密集的价位。 |
| **HVN (High Volume Node)** | “堡垒” | 具有重成交量支撑/阻力的价位区域。 |
| **Squeeze (挤压)** | “蓄势待发” | 市场进入低波动期，预示着即将发生剧烈突破。 |
| **DLE (Deep Entry)** | “黄金切入” | 在支撑区深处挂单，以提高安全边际。 |

---