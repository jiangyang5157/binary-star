# 加密货币双智能体交易分析系统 (Crypto Dual-Agent Trading System)

这是一个利用**双智能体架构**（交易员 Trader & 审查员 Reviewer）和**多模态 AI**（Gemini）构建的加密货币交易分析框架。它能够将复杂的市场数据和图表转化为可执行的波段交易逻辑。

---

## 🧠 核心原理

该系统模拟了专业交易室的工作流程，设置了两个互补的角色：

1.  **Agent A (交易员 Trader)**: 
    *   **数据富化**: 结合实时K线图、成交量分布 (Volume Profile: POC/VAH/VAL)、清算数据 (Liquidations) 以及情绪指标 (OI/LS Ratio)。
    *   **视觉逻辑分析**: 生成“增强型”图表，由 AI 直接读取图表中的视觉信号进行逻辑推演。
    *   **多轮推理**: 采用 3-Pass 推理流程（初步预测、红队审计、最终决议），通过自我博弈优化判断。
    *   **决策输出**: 提供包含信心值、详细中英文理由的交易建议。

2.  **Agent B (审查员 Reviewer)**:
    *   **事后审计**: 定期扫描历史预测，当交易窗口关闭（通常 7 天后）时进行评估。
    *   **盈亏复盘**: 对比 Trader 的预测逻辑与市场的实际走势，量化回撤和收益。
    *   **逻辑补丁**: 针对持续性的错误，生成具体的“提示词补丁”或配置调整建议，实现 Agent A 的逻辑自我进化。

---

## 🛠 安装与配置

### 1. 环境要求
*   Python 3.8+
*   Binance API Key (从币安官网申请，用于获取行情)
*   Gemini API Key (从 Google AI Studio 获取，用于 AI 逻辑分析)

### 2. 安装步骤
```bash
# 进入项目目录并创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 环境配置
在项目根目录创建 `.env` 文件，填入以下内容：
```env
# [必填] AI 逻辑分析核心 (Agent A & B 运行必须)
GEMINI_API_KEY=你的_Google_Gemini_Key

# [建议] 币安行情服务 (可选，填写后可获得更高频的 API 访问限额)
BINANCE_API_KEY=你的_币安_API_Key
BINANCE_API_SECRET=你的_币安_Secret

# [可选] 邮件通知配置 (填入以下两项后将自动开启邮件提醒)
RECIPIENT_EMAIL=接收信号的邮箱地址
RECIPIENT_APP_PASSWORD=你的_Gmail_应用专用密码
```
*注：系统会自动将 `RECIPIENT_EMAIL` 同时作为发送方和接收方。*

---

## 🚀 执行指南

### 1. 单次市场分析 (Agent A)
执行以下命令，系统将抓取当前市场数据并生成一份预测报告：
```bash
python main.py
```
*   **输入**: 实时行情与情绪数据。
*   **输出**: 预测 JSON 文件 (在 `data/raw/predictions/`) 以及标注后的技术图表 (在 `data/images/`)。

### 2. 运行交易复盘 (Agent B)
执行此命令对已结束的历史预测进行评分和缺陷分析：
```bash
python reviewer_main.py
```
*   **老化保护 (Aging Protection)**: 默认情况下，系统遵循 `config.yaml` 中的 `minimum_review_age_hours`（通常为 168 小时/7 天）。这是为了给交易留出足够的“平仓”或“趋势发展”时间。
*   **强制回顾 (--force)**: 如果需要立即复盘最近的预测（如环境测试），请加上 `--force` 标志。

### 3. 自动化调度器 (The Scheduler)
这是系统的“运维大脑”，能够全自动维持上述两套循环：
```bash
python scheduler.py
```
*   **自动化原理**: 
    - 启动后，调度器会周期性地检查并触发 Agent A 的分析任务。
    - 它同时会根据设定的回溯窗口，自动寻找符合复盘条件的旧预测，调用 `reviewer_main.py` 进行审计。
    - **休眠机制**: 每次执行任务后，它会自动进入静默期，防止 API 过频访问并节省 Token 成本。
*   **停止**: 使用 **`Ctrl + C`** 退出即可。

### 4. 历史回测模拟器 (The Simulator)
在不等待数周的情况下，测试您的提示词在不同市场环境下的表现：
```bash
python simulator.py --days 30 --sampling 15 --mode regime
```
*   **核心选项**:
    - `--symbol`: 模拟的资产 (例如 `BTCUSDT`)。
    - `--days`: 回测的历史深度。
    - `--start YYYY-MM-DD`: 起始日期（覆盖 `--days` 参数）。
    - `--sampling`: 期间采样的快照数量（建议 15-20）。
    - `--mode`: 采样策略。`regime` (按牛/熊/震荡分层随机采样) 或 `spaced` (等间隔采样)。

---

## 📊 结果解读

系统会为每笔交易分配一个 **信心分数 (Confidence Score)**：

*   **85% - 100% (高确信度)**: 🔥 **策略共振。** 宏观结构 (1d)、微观入口 (4h) 和情绪 (OI) 达成一致。
*   **75% - 84% (中等)**: ⚖️ **密切关注。** 方向正确，但时机或筹码分布支撑可能并非最优。
*   **75% 以下 (低信心值)**: 🧊 **保持观望/中立。** 市场可能处于震荡区域。

---
## 许可证
MIT
