# 🚀 Crypto Triple-Agent Trading Analysis System

> **基于 Google Gemini 多模态 AI 的闭环自进化交易分析系统**

本项目是一个模拟对冲基金决策链的 **三智能体 (Triple-Agent)** 系统。通过 **Trader (交易)**、**Reviewer (审计)**、**Coach (战略调整)** 的协同工作，实现了从"实时决策"到"历史复盘"再到"策略自动进化"的全闭环。

---

## 📂 项目结构

```
crypto/
├── main.py              # 入口：运行 Trader (Agent A) 预测
├── review.py             # 入口：运行 Reviewer (Agent B) 复盘
├── coach.py              # 入口：运行 Coach (Agent C) 策略进化
├── scheduler.py          # 自动化调度器（定时运行 A 和 B）
├── simulator.py          # 历史回测器
├── config/
│   └── config.yaml       # 🧠 核心配置（唯一参数来源）
├── src/
│   ├── agent/            # AI 代理模块
│   │   ├── trader_agent.py       # Agent A：多模态分析
│   │   ├── reviewer_agent.py     # Agent B：复盘审计
│   │   ├── coach_agent.py        # Agent C：战略导师
│   │   ├── prompt_manager.py     # 动态提示词补丁引擎
│   │   └── prompts/              # AI 提示词模板
│   ├── data_fetcher/     # 数据获取
│   │   ├── binance_client.py     # Binance API 客户端
│   │   ├── sentiment.py          # 情绪数据（OI、多空比）
│   │   └── storage.py            # JSON 存储工具
│   ├── analyzer/          # 分析引擎
│   │   ├── volume_profile.py     # 成交量分布分析
│   │   └── chart_generator.py    # 图表生成器
│   └── utils/
│       └── notifier.py           # 邮件通知
├── tests/                # 测试套件（20 个测试）
├── data/                 # 运行时数据（预测、图表等）
└── .env                  # 环境变量（API Key 等，不入 git）
```

---

## 🏗 系统架构

本系统采用 **Triple-Agent (三方代理) 闭环自进化架构**。不同于传统单向脚本，它通过“生产-审计-复盘-注入”形成持续迭代的交易大脑。

### 技术生命周期 (Technical Lifecycle)

| 阶段 | 核心组件 | 输入数据 | 输出产物 | 核心目标 |
| :--- | :--- | :--- | :--- | :--- |
| **1. 预测 (Trade)** | **Agent A: Trader** | 多周期（Macro/Micro）K线 + 情绪数据 | `prediction.json` | 生成三轮推演交易信号 |
| **2. 审计 (Review)** | **Agent B: Reviewer** | 历史预测 + 真实市场数据 | `review.json` | 判定 TP/SL 触碰与逻辑偏差 |
| **3. 指导 (Coach)** | **Agent C: Coach** | 批量 Review 报告 (Batch) | `prompt_patch` | 识别系统性弱点与交易偏见 |
| **4. 进化 (Evolve)** | **Prompt Manager** | Base Prompt + Coach 补丁 | **动态补丁指令** | 将新规则实时注入下一次交易 |

---

### 👤 Agent A (Trader) — 执行大脑
*   **核心逻辑**：基于双周期（Macro/Micro）Volume Profile 和订单流（Delta）进行分析。
*   **三轮推演**：`初始分析` -> `红队质疑 (Red Team)` -> `最终决策`。有效降低 AI 幻觉和冲动交易。

### ⚖️ Agent B (Reviewer) — 铁面审计
*   **核心逻辑**：在预设持仓周期结束后，根据 `review_kline_interval` 定义的高精度 K 线进行盈亏判定。
*   **职责**：对比 AI 预测的止盈/止损与市场真实的高低点，生成包含“经验教训”的技术性 post-mortem。

### 🧠 Agent C (Coach) — 战略策略师
*   **核心逻辑**：扫描最近 N 场交易的审计报告。
*   **职责**：发现 Agent A 的行为模式（如“仓位管理过于保守”或“对 POC 回测反应过度”），生成 `ADD/REPLACE` 指令，通过 Prompt Manager 实现“策略自进化”。

---

## 🛠 快速开始（从零到运行）

### 前置要求
- **Python 3.11+**（因为用到了 `datetime.fromisoformat()` 的新特性 和 `zoneinfo`）
- **Binance 账号**（免费，用于 API Key 获取更多数据权限，非必须）
- **Google AI API Key**（[在此申请](https://aistudio.google.com/app/apikey)）

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
# 必须：Google Gemini API Key
GEMINI_API_KEY=your_gemini_api_key_here

# 可选：Binance API（没有也能跑，但部分数据不可用）
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret

# 可选：邮件通知（不填则不发邮件）
RECIPIENT_EMAIL=your_email@gmail.com
RECIPIENT_APP_PASSWORD=your_gmail_app_password
```

> [!TIP]
> Gmail 的 App Password 需要在 Google 账号安全设置中生成，不能用 Gmail 登录密码。

### 第三步：检查配置
核心配置文件是 `config/config.yaml`，所有运行参数都在这里定义：
```yaml
symbol: "BTCUSDT"                 # 交易对
prediction:
  trade_horizon_days: <N>         # 预期持仓周期（见 config.yaml）
review:
  minimum_review_age_hours: <N>   # 最小复盘等待时间（见 config.yaml）
```

### 第四步：开始使用
```bash
# 1. 生成预测（Trader）
python main.py

# 2. 复盘（Reviewer）— 等预测到期后运行
python review.py

# 3. 策略进化（Coach）— 有多份复盘后运行，必须指定 batch
python coach.py --batch 10

# 可选：强制复盘（跳过时间保护）
python review.py --force
```

---

## 📊 术语速查

| 术语 | 全称 | 说明 |
|------|------|------|
| **POC** | Point of Control | 成交量最集中的价格区域，相当于"市场共识价" |
| **VAH** | Value Area High | 成交量密集区的上边界，通常是阻力位 |
| **VAL** | Value Area Low | 成交量密集区的下边界，通常是支撑位 |
| **OI** | Open Interest | 持仓量，反映市场参与者的持仓总量 |
| **L/S Ratio** | Long/Short Ratio | 多空比，大于 1 表示市场偏多 |
| **Red Team** | — | 模拟"对手方"来自我质疑，防止盲目自信 |

---

## 🧪 测试

运行完整测试套件（20 个测试，大部分使用 mock 数据）：
```bash
# 使用虚拟环境运行
./venv/bin/pytest tests/

# 或在激活 venv 后
pytest tests/
```

> [!NOTE]
> `test_data_fetcher.py` 和 `test_analyzer.py` 是集成测试，会调用真实的 Binance API。其余测试完全使用 mock 数据，可离线运行。

---

## ⚙️ 自动化

使用 `scheduler.py` 定时运行 Trader 和 Reviewer：
```bash
python scheduler.py
```
调度间隔由 `config.yaml` 中的 `automation` 配置控制。Coach 需要手动运行。

---

## 🔄 回测

使用 `simulator.py` 对历史数据进行回测：
```bash
# 过去 30 天的 15 个采样点
python simulator.py --days 30 --sampling 15

# 指定日期范围
python simulator.py --start 2026-01-01 --end 2026-03-01 --mode spaced
```

---

## 许可证
MIT © 2026 Crypto Triple-Agent Team
