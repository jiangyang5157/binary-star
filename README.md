# 🚀 Crypto Trading Analysis System

> **基于 Google Gemini 多模态 AI 的闭环自进化交易分析系统**

本项目是一个模拟对冲基金决策链的 **多智能体 (Multi-Agent)** 系统。通过 **Predictor (预测)**、**Reviewer (审计)**、**Coach (战略调整)** 的协同工作，实现了从"实时决策"到"历史复盘"再到"策略自动进化"的全闭环。

---

## 📂 项目结构

```
crypto/
├── predictor.py          # 入口：运行 Trader (Agent A) 预测
├── review.py             # 入口：运行 Reviewer (Agent B) 复盘
├── coach.py              # 入口：运行 Coach (Agent C) 策略进化
├── apply_patches.py      # 补丁工具：自动应用补丁
├── scheduler.py          # 自动化调度器（定时运行 A 和 B）
├── simulator.py          # 历史回测采样器 (多市场环境采样)
├── samples/              # 🧪 磨刀石工作室 (Samples Workbench)
│   ├── extract_samples.py # 提取工具：将 data/ 中的真实案例提取到 samples/
│   ├── run_samples.py     # 运行入口：执行全自动 A->B->C 闭环测试
│   └── samples.log        #  workbench 运行日志
├── config/
│   └── config.yaml       # 🧠 核心配置（统一路径管理：base_dir）
├── src/
│   ├── agent/            # AI 代理模块 (Predictor, Reviewer, Coach)
│   ├── data_fetcher/     # 数据获取模块 (Binance API & 情绪数据)
│   ├── analyzer/         # 分析引擎 (Volume Profile, Chart Generator)
│   └── utils/            # 通用工具
├── tests/                # 测试套件 (Unit & Integration Tests)
├── data/                 # 生产数据 (base_dir='data')
└── .env                  # 环境变量 (API Key)
```

---

## 🏗 系统架构

本系统采用 **闭环自进化架构**。不同于传统单向脚本，它通过“生产-审计-复盘-注入”形成持续迭代的交易大脑。

### 技术生命周期 (Technical Lifecycle)

| 阶段 | 核心组件 | 输入数据 | 输出产物 | 核心目标 |
| :--- | :--- | :--- | :--- | :--- |
| **1. 预测 (Predict)** | **Agent A: Predictor** | 多周期 K线 + 情绪 + 图表 | `prediction.json` | 生成包含 Red Team 质疑的交易信号 |
| **2. 审计 (Review)** | **Agent B: Reviewer** | 历史预测 + 1m 真实市场数据 | `review.json` | 严谨判定 TP/SL 触碰情况与逻辑偏差 |
| **3. 指导 (Coach)** | **Agent C: Coach** | 批量 Review 报告 (Batch) | `coach.json` | 识别行为模式并生成 Master Patch |
| **4. 进化 (Evolve)** | **apply_patches.py** | Coach 报告 + 源码 | **Prompt/Config 更新** | 自动化将战略建议注入系统，实现进化 |

---

### 👤 Agent A (Predictor) — 执行大脑
*   **多模型协同**：利用 Gemini 多模态能力，同时分析 K 线图表和数值指标（OI, L/S Ratio, Squeeze Factor）。
*   **极致手册化 (Handbook factorization)**：核心决策逻辑已从硬性代码检查转变为“手册化”指令。Agent 像职业分析师一样阅读 `prompt_predictor.txt` 中的风险红线（如：Stop-Loss >= 1.8x ATR），并在多步推演中自我对齐，实现了“代码驱动数据，手册驱动规则”的解耦。
*   **三轮推演**：执行 `初步分析 (temp_initial)` -> `红队质疑 (temp_critique)` -> `最终决策 (temp_final)`。这种架构能有效识别陷阱，降低伪突破的诱惑。
*   **V3 动力引擎**：引入了 **TTM Squeeze (Volatility Compression)** 检测和 **Volume Breakout** 确权逻辑。系统仅在能量完成蓄积且有成交量配比的情况下才允许冲击远端目标。

### 🛡️ Agent B (Reviewer) — 审计法官
*   **事实驱动**：不看 Agent A 的主观分析，仅根据 `review_kline_interval` 的真实成交价来验证止损或止盈是否被触发。
*   **精准过滤**：自动识别预测文件中的 `config_context` 标识，仅复盘与 `config.yaml` 当前 `symbol` 匹配的记录，确保审计的一致性。
*   **深度复盘**：分析为什么预测失败（如："未能识别 POC 下方的成交量真空区"），为 Coach 提供高质量的底层数据。

### 🧠 Agent C (Coach) — 战略导师
*   **战略元分析**：不同于 A 和 B 关注单场胜负，Coach 通过批量分析（Batch Analysis）识别系统性的行为特征。例如：识别出高波环境下的止损过窄，或单边趋势中的止盈过早。
*   **闭环自进化**：根据分析结果直接生成 `Master Patch`。这些补丁包含对 `prompt_predictor.txt` 的逻辑指令重构（ADD/REPLACE/REMOVE）以及对 `config.yaml` 核心参数（如 `min_tp_sl_ratio`）的数值调优建议。
*   **双模式运行**：既可以对生产环境的真实报告进行“在线指导”，也可以在 `samples/` 隔离区驱动“靶向压力测试”实现暴力进化。

---

## 🛠 快速开始

### 前置要求
- **Python 3.11+**
- **Google AI API Key**（[在此申请](https://aistudio.google.com/app/apikey)）
- **Binance 账号**（可选，用于获取更丰富的盘口与情绪数据）

### 第一步：克隆 & 安装
```bash
git clone <your-repo-url>
cd crypto

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate      # macOS / Linux
# .\venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 第二步：配置环境变量
在项目根目录创建 `.env` 文件：
```env
GEMINI_API_KEY=your_gemini_api_key_here

# 可选配置
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
RECIPIENT_EMAIL=your_email@gmail.com
RECIPIENT_APP_PASSWORD=your_gmail_app_password
```

### 第三步：开始运行

#### 1. 单次预测
```bash
python predictor.py
```

#### 2. 定时自动化 (7x24h)
```bash
python scheduler.py
```

#### 3. 策略进化 (自循环核心)
当积累了一定数量的复盘报告后（例如 10 份）：
```bash
# 运行 Coach 分析并生成补丁
python coach.py --batch 10

# 应用补丁 (支持 Prompt 替换以及 Config 参数调优)
python apply_patches.py data/coach/coach_BTCUSDT_2026xxxx.json
```

---

## 🧪 磨刀石工作室 (Samples Workbench)

为了在不干扰生产环境的情况下快速迭代 Prompt，系统提供了隔离的 `samples/` 环境。

### 1. 案例提取 (Extract)
从生产环境 `data/` 中提取感兴趣的样本到 `samples/`（支持自动扫描子目录）：
```bash
# 在 extract_samples.py 中配置 sources=['data']
python samples/extract_samples.py
```

### 2. 全自动闭环测试 (Continuous Optimization)
在 `samples/` 目录下执行“预测 -> 审计 -> 指导”全自动化流程：
```bash
python samples/run_samples.py
```
*   **隔离性**：所有的图片 (`samples/images`) 和报告均保存在 `samples/` 目录下。
*   **全日志**：执行过程详尽记录在 `samples/samples.log`。
*   **自动 Coach**：流程结束后会自动触发 Coach 代理对本次 Workbench 的所有样本进行总结，生成优化补丁。

---

## 📊 关键字

| 关键字 | 全称 | 说明 |
|------|------|------|
| **POC** | Point of Control | 成交量最集中的价格区域，通常具有强大的吸引力/支撑力 |
| **VAH/VAL** | Value Area H/L | 价值区域上下界，主要的成交量在此区间完成 |
| **Squeeze** | BB vs KC Squeeze | 波动率挤压，当布林带进入肯特纳通道，预示着巨大的单边动能即将爆发 |
| **Volume Breakout** | 成交量确权 | 系统 V3 核心逻辑：突破时成交量必须 > 21日均值的 2 倍，否则视为低流动性陷阱 |
| **Trend Intensity** | 趋势强度 | 0.4 阈值判断：帮助 Agent 区分当前是在处理“均值回归”还是“顺势突破” |
| **prediction_horizon_days** | 预测周期 | 系统预期持仓/预测的有效天数，直接影响 ATR 计算的宏观参考 |

---

## 🔄 历史回测

系统内置了强大的模拟器，支持在历史任意时间点触发 Agent A 的逻辑：
```bash
# 采样过去 14 天的 8-10 个随机时间点进行模拟
python simulator.py --days 14 --sampling 10 --mode regime

# 指定模式：spaced 表示等间隔采样，regime 表示按行情分层采样（推荐用于调优）
python simulator.py --days 14 --sampling 10 --mode spaced

> [!TIP]
> **监控运行**：你可以通过 `tail -f simulator.log` 实时查看模拟进度，系统会输出每个样本的采样原因（市场状态判断）以及预测/审计的完成情况。
```

---

## 💎 核心开发流：Prompt 质量提升 (Standard Workflow)

当你发现预测准确率（如 SL 触发频繁）不理想时，请按照以下“磨刀石”标准流程进行针对性进化：

1.  **第一阶段：仿真与录制 (Record & Sample)**
    在回测模拟器中运行大样本，记录不同行情下的系统表现：
    ```bash
    python simulator.py --days 30 --sampling 20 --mode regime
    ```

2.  **第二阶段：全局策略注入 (Batch Coach & Patch)**
    运行 Coach 分析这 20 个样本的系统性偏差，并应用第一轮“基础补丁”：
    ```bash
    python coach.py --batch 20
    python apply_patches.py data/coach/coach_latest.json
    ```

3.  **第三阶段：弱点提取 (Extract Targets)**
    使用提取工具将刚才仍然失败（SL）、逻辑混乱或评分较低的案例移动到 `samples/` 磨刀石工作室：
    ```bash
    python samples/extract_samples.py
    ```

4.  **第四阶段：靶向压力测试与优化 (Workbench Iteration)**
    在 `samples/` 隔离区重新运行这些难题，利用“磨刀石”闭环进行暴力针对性演化：
    ```bash
    python samples/run_samples.py
    ```
    *注：此步骤结束后，系统会自动触发 Coach 基于这些工作区样本生成更高精度的二次优化补丁。*

5.  **第五阶段：生产环境注入 (Inject & Deploy)**
    当 workbench 中的样本评分大幅提升后，将最优补丁应用到生产 Prompt：
    ```bash
    python apply_patches.py samples/coach/coach_latest.json
    ```

6.  **第六阶段：回归验证 (Validation)**
    使用从未见过的最新数据运行一次回测验证，确保“进化”有效且没有产生负面退化。

### 💡 Coach 训练策略建议 (Training Strategy)
针对 Coach (Agent C) 的训练计划，建议如下最佳实践：

*   **训练规模 (Batch Size)**:
    *   **快速修复 (5-10 组)**: 适用于修复明显的单点逻辑漏洞，锁定痛点快。
    *   **系统进化 (20-30 组)**: **推荐**。最适合识别系统性偏差（如：Greedy Bias、Entry Buffer），具备统计意义。
*   **样本选择**:
    *   **磨刀石阶段 (生存训练)**: 优先选分低的 (SL Hit)，通过分析失败案例生成“Counter-Thesis”（反向修正案）。
    *   **混合训练 (生产稳健性)**: 采用 **80% 失败案例 + 20% 随机成功案例**，防止修复 Bug 时破坏原有盈利逻辑。
*   **迭代价值**: 同一数据集在 Apply Patch 后**非常有必要**再次 Coach。Apply Patch 后 Agent A 行为改变，在相同数据下会产生新决策。通常进行 **2-3 次迭代** 即可精修出该数据集对应的最优补丁。

### 📈 进化计划与收益预估 (Evolution Plan & Projection)
建议将训练分为 **日常维护** 与 **靶向演化** 两个层级：

*   **1. 核心训练工作流**:
    *   **A. 日常维护 (周一至周五)**: 每天 24:00 运行 `python coach.py --batch 24`，吸收全量市场噪音。
    *   **B. 靶向演化 (每 2-3 天或积累 10 个止盈/止损后)**: 
        1. 运行 `python samples/extract_samples.py` 提取难题。
        2. 运行 `python samples/run_samples.py` 在磨刀石工作室进行 **2-3 次密集 Coach 迭代**。
        3. 解决后清空 `samples/` 目录。
*   **2. 周期预估 (BTCUSDT 示例)**:
    *   **种子期 (1-3天)**: $2-$5 成本。修复基础逻辑错误。
    *   **生长期 (4-14天)**: $10-$25 成本。系统开始识别高阶形态（Squeeze, VP Gravity）。
    *   **自进化期 (15-30天)**: $30-$60+ 成本。WR 达到 60%+，进入稳定盈利信任区。
*   **3. “无脑跟随” 判定标准**:
    当你发现 **Adversarial Audit** 中的 `mae_stress_level` 持续控制在 **30% 以下**，且 `evaluation_score` 稳定在 **80 分以上** 持续至少 7 天时，系统已具备极高的实操信任度。

---

## 🧪 测试

```bash
pytest tests/
```

---

## 许可证
MIT
