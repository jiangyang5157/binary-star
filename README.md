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
├── apply_patches.py      # 补丁工具：自动应用 Coach 产生的优化建议
├── scheduler.py          # 自动化调度器（定时运行 A 和 B）
├── simulator.py          # 历史回测器 (模拟不同时间点的决策)
├── requirements.txt      # 项目依赖
├── config/
│   └── config.yaml       # 🧠 核心配置（唯一参数来源）
├── src/
│   ├── agent/            # AI 代理模块
│   │   ├── predictor_agent.py       # Agent A：多模态分析 & 三轮推演
│   │   ├── reviewer_agent.py     # Agent B：基于高频 K 线的盈亏审计
│   │   ├── coach_agent.py        # Agent C：系统性偏差识别与战略导师
│   │   └── prompts/              # AI 提示词模板 (Predictor, Reviewer, Coach)
│   ├── data_fetcher/     # 数据获取模块 (Binance API & 情绪数据)
│   ├── analyzer/         # 分析引擎 (Volume Profile, Chart Generator)
│   └── utils/            # 通用工具 (邮件通知等)
├── tests/                # 测试套件 (Unit & Integration Tests)
├── data/                 # 运行时数据 (持久化存储)
│   ├── raw/              # 原始 JSON 数据 (predictions, reviews, coach reports)
│   └── images/           # 生成的分析图表
└── .env                  # 环境变量 (API Key 等，不入 git)
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
*   **多模型协同**：利用 Gemini 多模态能力，同时分析 K 线图表和数值指标（OI, L/S Ratio）。
*   **三轮推演**：执行 `初步分析` -> `红队质疑 (Red Team Critique)` -> `最终决策`。这种架构能有效识别陷阱，降低伪突破的诱惑。

*   **事实驱动**：不看 Agent A 的主观分析，仅根据 `review_kline_interval` 的真实成交价来验证止损或止盈是否被触发。
*   **精准过滤**：自动识别预测文件中的 `config_context` 标识，仅复盘与 `config.yaml` 当前 `symbol` 匹配的记录，确保审计的一致性。
*   **深度复盘**：分析为什么预测失败（如："未能识别 POC 下方的成交量真空区"），为 Coach 提供高质量的底层数据。

### 🧠 Agent C (Coach) — 战略导师
*   **模式识别**：跳出单场胜负，观察全局。例如：如果最近 10 场失败中有 7 场是因为“右侧入场太晚”，Coach 会识别出这一系统性偏差。
*   **输出补丁**：产出具体的调整建议，包括对 `prompt_predictor.txt` 内的 `ADD/REPLACE/REMOVE` 和 `config.yaml` 中的参数。

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

# 应用补丁 (将建议自动注入 Prompt 和 Config)
python apply_patches.py data/raw/coach/coach_report_xxx.json
```

---

## 📊 术语速查

| 术语 | 全称 | 说明 |
|------|------|------|
| **POC** | Point of Control | 成交量最集中的价格区域，通常具有强大的吸引力/支撑力 |
| **VAH/VAL** | Value Area H/L | 价值区域上下界，主要的成交量在此区间完成 |
| **OI** | Open Interest | 未平仓合约，增加通常意味着趋势的持续或增强 |
| **Red Team** | 红队 | 专门负责寻找预测漏洞的逻辑环节，防止 AI 产生"证实偏差" |

---

## 🔄 历史回测

系统内置了强大的模拟器，支持在历史任意时间点触发 Agent A 的逻辑：
```bash
# 采样过去 30 天的 32 个随机时间点进行模拟
python simulator.py --days 30 --sampling 32 --mode regime

# 指定模式：spaced 表示等间隔采样，regime 表示按行情分层采样（推荐用于调优）
python simulator.py --days 30 --sampling 32 --mode spaced
```

---

## 💎 核心开发流：Prompt 质量提升 (Standard Workflow)

当你发现预测的准确率（尤其是止盈止损）不理想时，请按照以下标准流程进行一轮“进化”：

1.  **数据收集**：运行 30 天 32 个样本的制度化回测。
    ```bash
    python simulator.py --days 30 --sampling 32 --mode regime
    ```
    *注：`regime` 模式能确保在牛/熊/高低波动下都有足够样本。*

2.  **战略分析**：运行 Coach 处理这 32 个复盘报告。
    ```bash
    python coach.py --batch 32
    ```

3.  **自动注入**：应用生成的最新补丁。
    ```bash
    # 找到最新的 coach_report JSON 文件
    python apply_patches.py data/raw/coach/coach_BTCUSDT_2026xxxx.json
    ```

4.  **验证闭环**：使用新 Prompt 运行一个小规模（10个样本）的回测，对比胜率。
    ```bash
    python simulator.py --days 14 --sampling 10 --mode spaced
    ```

---

## 🧪 测试

```bash
pytest tests/
```

---

## 许可证
MIT
