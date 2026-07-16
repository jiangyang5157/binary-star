// src/dashboard/static/i18n.js
// ── 翻译字典 ──
const TRANSLATIONS = {
  // 导航
  "nav.performance": { en: "Performance", zh: "绩效" },
  "nav.live": { en: "Live", zh: "实时" },
  "nav.development": { en: "Development", zh: "开发" },
  "nav.session": { en: "Session Detail", zh: "会话详情" },
  "nav.audit": { en: "Audit Detail", zh: "审计详情" },

  // 锁横幅
  "lock.read_only": {
    en: "🔒 Read-only",
    zh: "🔒 只读"
  },

  // KPI
  "kpi.net_pnl": { en: "Net P&L", zh: "净盈亏" },
  "kpi.win_rate": { en: "Win Rate", zh: "胜率" },
  "kpi.win_loss": { en: "Win / Loss", zh: "盈亏比" },
  "kpi.max_drawdown": { en: "Max Drawdown", zh: "最大回撤" },
  "kpi.fill_rate": { en: "Fill Rate", zh: "成交率" },
  "kpi.mfe_efficiency": { en: "MFE Efficiency", zh: "MFE 效率" },
  "kpi.mae_stress": { en: "MAE Stress", zh: "MAE 压力" },

  // Section 标题
  "section.trade_ledger": { en: "Trade Log", zh: "交易日志" },
  "section.decision_timeline": { en: "Trade Timeline", zh: "交易时间线" },
  "section.active_sessions": { en: "Active Sessions", zh: "活跃会话" },
  "section.new_session": { en: "New Session", zh: "新建会话" },
  "section.sniper": { en: "Signal Monitor", zh: "信号监控" },
  "section.backtest": { en: "Backtest", zh: "回测" },

  // 表头
  "th.symbol": { en: "Symbol", zh: "交易对" },
  "th.observed_at": { en: "Observed At", zh: "观测时间" },
  "th.direction": { en: "Direction", zh: "方向" },
  "th.conf": { en: "Conf", zh: "置信度" },
  "th.entry": { en: "Entry", zh: "入场价" },
  "th.tp": { en: "TP", zh: "止盈" },
  "th.sl": { en: "SL", zh: "止损" },
  "th.rr": { en: "RR", zh: "盈亏比" },
  "th.result": { en: "Result", zh: "结果" },
  "th.pnl": { en: "P&L", zh: "盈亏" },
  "th.version": { en: "Version", zh: "版本" },
  "th.waiting": { en: "Waiting", zh: "等待" },
  "th.holding": { en: "Holding", zh: "持有" },
  "th.time_left": { en: "Time Left", zh: "剩余时间" },
  "th.orders": { en: "Orders", zh: "订单" },
  "th.status": { en: "Status", zh: "状态" },

  // 按钮
  "btn.run": { en: "▶ Run", zh: "▶ 运行" },
  "btn.stop": { en: "⏹ Stop", zh: "⏹ 停止" },
  "btn.refresh": { en: "⟳ Refresh", zh: "⟳ 刷新" },
  "btn.refreshing": { en: "⟳ Refreshing...", zh: "⟳ 刷新中..." },
  "btn.auditing": { en: "⟳ Auditing...", zh: "⟳ 审计中..." },
  "btn.audit": { en: "⟳ Audit", zh: "⟳ 审计" },
  "btn.refresh.title": { en: "Refresh active sessions", zh: "刷新活跃会话" },
  "btn.audit.title": { en: "Run forensic audit against all un-audited sessions", zh: "对所有未审计会话执行审计" },
  "btn.view": { en: "View", zh: "查看" },
  "btn.scout": { en: "◎ Scout", zh: "◎ 勘探" },

  // 过滤器
  "filter.symbol": { en: "Symbol", zh: "交易对" },
  "filter.version": { en: "Version", zh: "版本" },

  // 图表
  "chart.min_confidence": { en: "Min Confidence", zh: "最低置信度" },
  "chart.click_hint": {
    en: "Click a bubble to open the session audit report",
    zh: "点击气泡打开审计报告"
  },
  "chart.conf_tooltip": { en: "Conf", zh: "置信度" },
  "chart.pnl_tooltip": { en: "P&L", zh: "盈亏" },
  "chart.holding_tooltip": { en: "Holding:", zh: "持有:" },
  "chart.equity_tooltip": { en: "Equity", zh: "权益" },
  "chart.conf_threshold_hint": {
    en: "Cumulative P&L if only signals >= threshold are traded",
    zh: "仅交易置信度≥阈值的信号的累计盈亏"
  },

  // Backtest
  "bt.single_ts": { en: "Single Timestamp", zh: "单时间戳" },
  "bt.date_range": { en: "Date Range", zh: "日期范围" },
  "bt.trading_pair": { en: "Trading Pair", zh: "交易对" },
  "bt.trading_pairs": { en: "Trading Pairs", zh: "交易对" },
  "bt.timestamp": { en: "Timestamp", zh: "时间戳" },
  "bt.start": { en: "Start", zh: "开始" },
  "bt.end": { en: "End", zh: "结束" },
  "bt.samples": { en: "Samples", zh: "采样数" },
  "bt.samples_count": { en: "{n} selected", zh: "已选 {n} 个" },
  "bt.hint": {
    en: "Format: T-Nd, T-Nh, YYYY-MM-DD HH:MM:SS · Valid window: last 28 days · Start must be before End",
    zh: "格式: T-Nd, T-Nh, YYYY-MM-DD HH:MM:SS · 有效窗口: 最近 28 天 · 开始时间须早于结束时间"
  },

  // 状态提示
  "msg.loading": { en: "Loading...", zh: "加载中..." },
  "msg.loading_sessions": { en: "Loading sessions...", zh: "加载会话中..." },
  "msg.no_records_active": { en: "No records — all clear", zh: "无记录 — 一切正常" },
  "msg.no_records_match": { en: "No records match filters", zh: "无匹配记录" },
  "msg.load_failed": { en: "Failed to load records", zh: "加载失败" },
  "msg.invalid_session": { en: "Invalid session data", zh: "无效会话数据" },

  // Sniper
  "sniper.trade_mode_label": { en: "Mode", zh: "模式" },
  "sniper.mode_observe": { en: "Observe", zh: "观察" },
  "sniper.mode_trade": { en: "Trade", zh: "交易" },
  "sniper.cap_label": { en: "Cap (optional)", zh: "上限（可选）" },
  "sniper.risk_label": { en: "Risk", zh: "风险" },
  "sniper.confidence_label": { en: "Confidence", zh: "置信度" },

  // 状态徽章
  "status.filled": { en: "FILLED", zh: "已成交" },
  "status.unfilled": { en: "UNFILLED", zh: "未成交" },
  "status.tp_hit": { en: "TP HIT", zh: "止盈触发" },
  "status.sl_hit": { en: "SL HIT", zh: "止损触发" },
  "status.expired": { en: "EXPIRED", zh: "已过期" },
  "status.long": { en: "LONG", zh: "多头" },
  "status.short": { en: "SHORT", zh: "空头" },
  "status.protected": { en: "Protected", zh: "受保护" },
  "status.naked": { en: "Naked", zh: "裸仓" },
  "status.idle": { en: "Idle", zh: "闲置" },
  "status.connected": { en: "Connected", zh: "已连接" },
  "status.disconnected": { en: "Disconnected", zh: "已断开" },
  "status.retrying": { en: "Retrying...", zh: "重试中..." },

  // 方向 (opinion badge)
  "opinion.bullish": { en: "BULLISH", zh: "看涨" },
  "opinion.bearish": { en: "BEARISH", zh: "看跌" },
  "opinion.neutral": { en: "NEUTRAL", zh: "中性" },
  "opinion.unknown": { en: "UNKNOWN", zh: "未知" },

  // Session / Audit 详情页
  "detail.final_decision": { en: "Final Decision", zh: "最终决策" },
  "detail.confidence": { en: "Confidence", zh: "置信度" },
  "detail.current_price": { en: "Current Price", zh: "当前价格" },
  "detail.entry": { en: "Entry", zh: "入场价" },
  "detail.take_profit": { en: "Take Profit", zh: "止盈" },
  "detail.stop_loss": { en: "Stop Loss", zh: "止损" },
  "detail.rr_ratio": { en: "RR Ratio", zh: "盈亏比" },
  "detail.waiting_hours": { en: "Waiting Hours", zh: "等待时间" },
  "detail.holding_hours": { en: "Holding Hours", zh: "持有时间" },
  "detail.reasoning_chain": { en: "Reasoning Chain", zh: "推理链" },
  "detail.critic_impact": { en: "Critic Impact", zh: "批判影响" },
  "detail.debate_rounds": { en: "Debate Rounds", zh: "辩论轮次" },
  "detail.round": { en: "Round", zh: "第轮" },
  "detail.critic_review": { en: "Critic Review", zh: "批判审查" },
  "detail.audit_evidence": { en: "Audit Evidence", zh: "审计证据" },
  "detail.math_fact_check": { en: "Math Fact Check", zh: "数学验证" },
  "detail.charts": { en: "Charts", zh: "图表" },
  "detail.chart_macro": { en: "Macro (1h)", zh: "宏观 (1h)" },
  "detail.chart_micro": { en: "Micro (15m)", zh: "微观 (15m)" },
  "detail.chart_unavailable": { en: "Chart image not available via server", zh: "图表不可用" },
  "detail.metadata": { en: "Metadata", zh: "元数据" },
  "detail.project_version": { en: "Project Version", zh: "项目版本" },
  "detail.git_commit": { en: "Git Commit", zh: "Git 提交" },
  "detail.session_hash": { en: "Session Hash", zh: "会话哈希" },
  "detail.critic_hash": { en: "Critic Hash", zh: "批判哈希" },
  "detail.bs_hash": { en: "Binary Star Hash", zh: "双星哈希" },
  "detail.config_hash": { en: "Config Hash", zh: "配置哈希" },

  // Audit 交易结果
  "audit.trade": { en: "Trade:", zh: "交易:" },
  "audit.trade_outcome": { en: "Trade Outcome", zh: "交易结果" },
  "audit.exit_price": { en: "Exit Price (T1)", zh: "出场价 (T1)" },
  "audit.mfe": { en: "Max Favorable Excursion", zh: "最大有利偏移" },
  "audit.mfe_efficiency": { en: "MFE Efficiency", zh: "MFE 效率" },
  "audit.mae": { en: "Max Adverse Excursion", zh: "最大不利偏移" },
  "audit.mae_stress": { en: "MAE Stress Level", zh: "MAE 压力等级" },
  "audit.projected_holding": { en: "Projected Holding", zh: "预期持有" },
  "audit.actual_holding": { en: "Actual Holding", zh: "实际持有" },
  "audit.justified_surrender": { en: "Justified Surrender", zh: "合理退出" },
  "audit.catastrophic_miss": { en: "Catastrophic Miss", zh: "灾难性错过" },

  // Session 页面
  "session.title_suffix": { en: "Session", zh: "会话" },
  "session.back_to_live": { en: "← Back to Live", zh: "← 返回实时" },
  "audit.back_to_sessions": { en: "← Back to Sessions", zh: "← 返回会话列表" },

  // 错误信息
  "error.heading": { en: "Error", zh: "错误" },
  "error.request_failed": { en: "Request failed", zh: "请求失败" },
  "error.stop_failed": { en: "stop failed", zh: "停止失败" },
  "error.unknown": { en: "Unknown error", zh: "未知错误" },

  // 验证错误
  "err.enter_symbol": { en: "Enter at least one symbol (e.g. BTC)", zh: "请输入至少一个交易对 (如 BTC)" },
  "err.invalid_symbol": {
    en: "is not a valid symbol — use letters and numbers only",
    zh: "不是有效交易对 — 仅可使用字母和数字"
  },
  "err.cap_positive": { en: "Cap must be a positive number", zh: "上限必须为正数" },
  "err.risk_range": { en: "Risk must be between 0% and 1%", zh: "风险必须在 0% 到 1% 之间" },
  "err.min_chars": { en: "Enter at least 2 characters (e.g. BTC)", zh: "请输入至少 2 个字符 (如 BTC)" },
  "err.letters_numbers": { en: "Only letters and numbers", zh: "仅可使用字母和数字" },
  "err.single_symbol": { en: "Only one symbol allowed", zh: "仅支持单个交易对" },
  "err.timestamp_required": { en: "Timestamp is required", zh: "时间戳为必填" },
  "err.start_required": { en: "Start date is required", zh: "开始日期为必填" },
  "err.end_required": { en: "End date is required", zh: "结束日期为必填" },
  "err.samples_required": { en: "Number of samples is required", zh: "采样数为必填" },
  "err.samples_min": { en: "Must be ≥ 1", zh: "最少为 1" },
  "err.samples_max": { en: "Max 200 samples", zh: "最多 200 个采样点" },

  // Development 页面
  "dev.completed": { en: "Completed", zh: "已完成" },
  "dev.failed": { en: "Failed", zh: "失败" },
  "dev.preview_failed": { en: "preview failed", zh: "预览失败" },

  // 格式/单位
  "fmt.records": { en: "records", zh: "条记录" },
};

// ── 引擎函数 ──

/** 获取当前语言，优先级: URL 参数 → localStorage → 'en' */
function getLang() {
  const params = new URLSearchParams(location.search);
  const hl = params.get('hl');
  if (hl === 'zh' || hl === 'en') return hl;
  return localStorage.getItem('hl') || 'en';
}

/** 从 TRANSLATIONS 获取翻译文本，fallback 到英文 key 本身 */
function t(key, fallback) {
  const lang = getLang();
  const entry = TRANSLATIONS[key];
  if (entry && entry[lang]) return entry[lang];
  if (entry && entry.en) return entry.en;
  return fallback || key;
}

/** 应用指定语言到所有 data-i18n 元素 */
function applyTranslations(lang) {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const text = TRANSLATIONS[key]?.[lang];
    if (text) el.textContent = text;
  });
  // 同步 data-i18n-title 属性 (tooltips)
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.dataset.i18nTitle;
    const text = TRANSLATIONS[key]?.[lang];
    if (text) el.title = text;
  });
  // 同步 toggle 按钮高亮
  document.querySelectorAll('.lang-toggle .lang-en, .lang-toggle .lang-zh')
    .forEach(el => {
      el.classList.toggle('active', el.classList.contains('lang-' + lang));
    });
  // 同步内部链接 ?hl= 参数，确保切换语言后 nav 链接立即更新
  document.querySelectorAll('a').forEach(a => {
    try {
      const url = new URL(a.href);
      if (url.origin === location.origin && !url.hash) {
        url.searchParams.set('hl', lang);
        a.href = url.toString();
      }
    } catch (e) { /* 忽略无效链接 */ }
  });
}

/** 设置语言 — 客户端切换，不刷新页面 */
function setLang(lang) {
  localStorage.setItem('hl', lang);
  // 更新 URL query param without navigation (for bookmark consistency)
  const url = new URL(window.location);
  url.searchParams.set('hl', lang);
  history.replaceState(null, '', url.toString());
  // 更新所有静态 data-i18n 元素
  applyTranslations(lang);
  // 通知各页面重新渲染动态内容
  document.dispatchEvent(new CustomEvent('langchange', { detail: { lang } }));
}

/** 切换中/英 */
function toggleLang() {
  const current = getLang();
  setLang(current === 'en' ? 'zh' : 'en');
}

// ── 页面加载时初始化 ──
(function initI18n() {
  function apply() {
    const lang = getLang();
    applyTranslations(lang);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', apply);
  } else {
    apply();
  }
})();
