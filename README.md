# ⚖️ 真相 · 逻辑 · 审计

> **“不预测行情，只测绘逻辑。”**

这是一个基于 **物理真相** 与 **对抗性演化** 构建的多智能体交易系统。它通过“三路推理 (Reasoning Triad)”架构，将极度不确定的市场博弈转化为确定性的物理地形测�    %% 前向驱动：三路推理轴 (The Reasoning Triad)
    subgraph "前向驱动：三路推理轴 (The Reasoning Triad)"
        A["Observer: 测绘师"] -- "物理真相 (Truth Bus)" --> TB{{"真相总线 (Observation)"}}
        
        TB -- "注入背景" --> B1("Session Analyst: 架构师 (Phase A)")
        B1 -- "会话草案 (Draft)" --> C{{"Middleware: 物理公证层"}}
        TB -- "数据对齐" --> C
        C -- "数学事实 (Math Facts)" --> D["Critic: 对抗审判官"]
        TB -- "对抗审计" --> D
        D -- "审判报告 (Verdict)" --> B2("Session Analyst: 觉醒者 (Phase B)")
        TB -- "决策收敛" --> B2
        B2 -- "最终执行决议 (Decision)" --> F["Market Execution"]
    end

    %% 后向法医演化回路 (Recursive Loop)
    subgraph "后向演化：法医闭环 (The Evolution Loop)"
        F -->|"执行日志集 (Logs)"| G["Auditor: 法医鉴定师"]
        G -->|"法医审计报告 (Forensic Report)"| H["Evolution Engine: 演化分析师"]
        H -->|"逻辑补丁 (Patch)"| I[("Prompt & Config: 进化底座")]
        H -.->|"递归法典补丁意识"| G
    end
筋对抗审计" --> D
        D -- "审判报告 (Verdict)" --> B2("Session Analyst: 觉醒者 (Phase B)")
        TB -- "决策收敛" --> B2
        B2 -- "最终执行决议 (Decision)" --> F["Market Execution"]
    end

    %% 后向法医演化回路 (Recursive Loop)
    subgraph "后向演化：法医闭环 (The Evolution Loop)"
        F -->|"执行日志集 (Logs)"| G["Forensic Auditor: 法医鉴定师"]
        G -->|"法医审计报告 (Forensic Report)"| H["Evolution Engine: 演化合伙人"]
        H -->|"逻辑补丁 (Patch)"| I[("Prompt & Config: 进化底座")]
        H -.->|"递归法典补丁意识"| G
    end

    %% 关键进化路径映射：修复逻辑断裂
    I -.->|"注入地形感知"| A
    I -.->|"注入进化逻辑"| B1
    I -.->|"注入对抗约束"| D
    I -.->|"注入硬化策略"| B2

    %% 节点样式美化 (法务级配色)
    style C fill:#f96,stroke:#333,stroke-width:2px,color:#fff
    style TB fill:#ffd700,stroke:#b8860b,stroke-width:3px,stroke-dasharray: 5 5
    style F fill:#00ff00,stroke:#333,stroke-width:2px,color:#000
    style I fill:#f9f,stroke:#333,stroke-width:4px,color:#000
    style B1 fill:#e1f5fe,stroke:#01579b
    style B2 fill:#e1f5fe,stroke:#01579b
    style G fill:#ffcdd2,stroke:#b71c1c
    style H fill:#c8e6c9,stroke:#1b5e20
```

---

## 🧬 逻辑审计 · 共识协议

基于明确的物理地形边界与逻辑主权隔离，各组件在协作交接中始终维持着不可逾越的“法医级”逻辑严谨度：

| 智能实体 | 职能模型 | 枢纽逻辑 | 演化产物 |
| :--- | :--- | :--- | :--- |
| **Observer** | **测绘师** | **物理景观聚合**：识别宏微观地形共振，构建“真相总线” | 地形全景数据 |
| **Session Analyst (A)** | **架构师** | **交易蓝图构建**：锚定高成交量节点 (HVN) 并预设物理执行轨迹 | 逻辑草案 |
| **Middleware** | **真理校验门** | **物理解耦公证**：通过真相总线锁定 RR 与 ATR 参数，彻底消除幻觉 | 物理事实底座 |
| **Critic** | **对抗审判官** | **生存压力测试**：基于真相总线识别流动性陷阱，进行对抗性审计 | 审计判决书 |
| **Session Analyst (B)** | **觉醒者** | **风险硬化收敛**：整合审计意见，执行深度入场防御 (DLE) 或强制弃权 | 最终决议 |
| **Forensic Auditor** | **法医鉴定师** | **尸检溯源对比**：精准对齐成交事实，捕捉逻辑与现实的“真值偏离” | 法医复盘报告 |
| **Evolution Engine** | **演化合伙人** | **认知偏差修正**：诊断系统性盲区，合成多智能体进化的底层逻辑补丁 | 逻辑补丁 |

---

## 🚀 运行手册

### 0. 环境准备 (VENV)
在执行任何命令前，请确保处于项目的虚拟环境中：
*   **激活环境**: `source venv/bin/activate`
*   **直接运行 (推荐)**: 也可以直接使用 `./venv/bin/python` 代替 `python` 命令。


### Phase 1: 策略执行与回测验证 (The Session Analyst Axis)
*   **实时生产执行**: 捕获当前时刻的物理视角并生成决策。
    `python run_session.py prod`
*   **分层回测 (Regime-based Sampling)**: 在指定时间内按市场环境权重采样（过去24天到今天）。
    `python run_session.py --mode backtest backtest --start T-24d --end now --sampling 12 --mode regime`
    `python run_session.py --mode backtest backtest --start T-25d --end T-20d --sampling 5 --mode regime`
*   **等距回测 (Timeline Spaced)**: 在指定时间内按等距时间点均匀分布采样（过去24天到7天前）。
    `python run_session.py --mode backtest backtest --start T-24d --end T-7d --sampling 12 --mode spaced`

*   **Sample**:
```python
python run_session.py --mode backtest backtest --start T-14d --end T-7d --sampling 7 --mode regime
python run_forensic.py backtest
python run_evolution.py backtest
# tips: move dashboard from html/ to archived/ and renames archived/ to archived{n}
```

### Phase 2: 法医调查与看板分析 (The Forensic Axis)
*   **全量尸检**: 对所有已结束的单子进行法医级对齐与评分。
    `python run_forensic.py prod`
*   **定向法医复盘**: 针对特定失败/成功案例进行深度因果链回溯。
    `python run_forensic.py prod --file [STRATEGY_JSON_PATH]`
*   **策略逆向提取与还原**: 从法医复盘报告（Forensic Auditor Report）中反向提取原始策略会话，并自动还原至对应的 `strategies` 目录。
    `python export_strategy.py prod --file [REVIEW_JSON_PATH]`
    > **💡 核心用例**: 
    > 1. **数据恢复**: 当本地原始策略 JSON 文件丢失，但存有对应的法医复盘报告时，还原交易会话证据。
    > 2. **回测隔离**: 将法医报告中的某一特定策略片段剥离出来，生成标准的策略 JSON 文件，以便进行逻辑重放。
*   **可视化法医看板**: 可视化查看所有执行结果、MAE/MFE 回撤以及 **累计收益曲线 (v1.2.10)**。
    `python forensic_dashboard.py prod`
    > **💡 贴士**: 使用 **`-r / --recursive`** 开启全量扫描模式，自动合并所有 `archived` 文件夹中的历史数据，生成完整的资产增长曲线。


### Phase 3: 自动化演化循环 (The Evolutionary Axis)
*   **全自动化编排**: 开启循环扫描模式，自动执行从 Observer 到 Session Analyst 的全链路。
    `python run_session.py --mode live live --pulse 60 --mode scan`
*   **市场诊断服务 (静默监视)**: 仅在后台持续刷新真相总线，不消耗 Agent API 成本。
    `python run_market.py live --pulse 30`
*   **诊断与进化合成**: 开启系统“自我反思”模式，由 Evolution Engine 自动合成逻辑补丁。
    `python run_evolution.py live`
*   **应用逻辑补丁**: 将 Evolution Engine 生成的 `.patch` 物理硬化到 Prompt 或 Config 中。
    `python apply_patch.py --file [PATCH_PATH]`
