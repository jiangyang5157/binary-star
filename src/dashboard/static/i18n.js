// src/dashboard/static/i18n.js
// ── 翻译字典 ──
const TRANSLATIONS = {
  // 导航
  "nav.performance":    { en: "Performance",     zh: "绩效" },
  "nav.live":           { en: "Live",            zh: "实时" },
  "nav.development":    { en: "Development",     zh: "开发" },
  "nav.session":        { en: "Session Detail",  zh: "会话详情" },
  "nav.audit":          { en: "Audit Detail",    zh: "审计详情" },

  // KPI
  "kpi.net_pnl":        { en: "Net P&L",         zh: "净盈亏" },
  "kpi.win_rate":       { en: "Win Rate",        zh: "胜率" },
  "kpi.calmar":         { en: "Calmar Ratio",    zh: "卡玛比率" },
  "kpi.max_drawdown":   { en: "Max Drawdown",    zh: "最大回撤" },
  "kpi.executed":       { en: "Executed / Total",zh: "已执行 / 总计" },

  // Section 标题
  "section.trade_ledger":     { en: "Trade Ledger",           zh: "交易台账" },
  "section.decision_timeline":{ en: "Decision Timeline",      zh: "决策时间线" },
  "section.equity_curve":    { en: "Equity Growth Curve",    zh: "权益增长曲线" },
  "section.conf_optimizer":  { en: "Confidence Threshold Optimizer", zh: "置信度阈值优化" },
  "section.active_sessions": { en: "Active Sessions",         zh: "活跃会话" },
  "section.new_session":     { en: "New Session",             zh: "新建会话" },
  "section.sniper_control":  { en: "Sniper Control",          zh: "狙击控制" },
  "section.backtest":        { en: "Backtest",                zh: "回测" },

  // 表头
  "th.symbol":        { en: "Symbol",       zh: "交易对" },
  "th.observed_at":   { en: "Observed At",  zh: "观测时间" },
  "th.direction":     { en: "Direction",    zh: "方向" },
  "th.conf":          { en: "Conf",         zh: "置信度" },
  "th.entry":         { en: "Entry",        zh: "入场价" },
  "th.tp":            { en: "TP",           zh: "止盈" },
  "th.sl":            { en: "SL",           zh: "止损" },
  "th.rr":            { en: "RR",           zh: "盈亏比" },
  "th.result":        { en: "Result",       zh: "结果" },
  "th.pnl":           { en: "P&L",          zh: "盈亏" },
  "th.version":       { en: "Version",      zh: "版本" },
  "th.waiting":       { en: "Waiting",      zh: "等待" },
  "th.holding":       { en: "Holding",      zh: "持有" },
  "th.time_left":     { en: "Time Left",    zh: "剩余时间" },
  "th.orders":        { en: "Orders",       zh: "订单" },
  "th.status":        { en: "Status",       zh: "状态" },

  // 按钮
  "btn.run":          { en: "▶ Run",        zh: "▶ 运行" },
  "btn.stop":         { en: "⏹ Stop",      zh: "⏹ 停止" },
  "btn.audit":        { en: "▶ Audit",     zh: "▶ 审计" },
  "btn.refresh":      { en: "⟳ Refresh",   zh: "⟳ 刷新" },
  "btn.view":         { en: "View",         zh: "查看" },
  "btn.preview":      { en: "Preview Samples", zh: "预览采样点" },

  // 过滤器
  "filter.symbol":    { en: "Symbol",       zh: "交易对" },
  "filter.version":   { en: "Version",      zh: "版本" },
  "filter.show_neutral": { en: "Show Neutral", zh: "显示中性" },

  // 图表
  "chart.min_confidence": { en: "Min Confidence", zh: "最低置信度" },
  "chart.click_hint": { en: "Click a bubble to open the session audit report",
    zh: "点击气泡打开审计报告" },

  // Backtest
  "bt.single_ts":     { en: "Single Timestamp", zh: "单时间戳" },
  "bt.date_range":    { en: "Date Range",       zh: "日期范围" },
  "bt.trading_pair":  { en: "Trading Pair",     zh: "交易对" },
  "bt.timestamp":     { en: "Timestamp",        zh: "时间戳" },
  "bt.start":         { en: "Start",            zh: "开始" },
  "bt.end":           { en: "End",              zh: "结束" },
  "bt.samples":       { en: "Samples",          zh: "采样数" },
  "bt.samples_count": { en: "{n} selected",     zh: "已选 {n} 个" },
  "bt.hint":          { en: "Format: T-Nd, T-Nh, YYYY-MM-DD HH:MM:SS, or ISO-8601 · Valid window: last 28 days · Start must be before End",
    zh: "格式: T-Nd, T-Nh, YYYY-MM-DD HH:MM:SS 或 ISO-8601 · 有效窗口: 最近 28 天 · 开始时间须早于结束时间" },

  // 状态提示
  "msg.loading":       { en: "Loading...",                   zh: "加载中..." },
  "msg.loading_sessions": { en: "Loading sessions...",       zh: "加载会话中..." },
  "msg.no_records":    { en: "No records match filters",     zh: "无匹配记录" },
  "msg.no_records_active": { en: "No records — all clear",   zh: "无记录 — 一切正常" },
  "msg.load_failed":   { en: "Failed to load records",       zh: "加载失败" },

  // Sniper
  "sniper.enable_trading": { en: "Enable Trading", zh: "启用交易" },
  "sniper.balance":  { en: "Balance",     zh: "余额" },
  "sniper.watching": { en: "Watching {symbols}… · {time} since last pulse",
    zh: "监控 {symbols}… · 距上次脉冲 {time}" },
};

// ── 引擎函数 ──

/** 获取当前语言，优先级: URL 参数 → localStorage → 'en' */
function getLang() {
  const params = new URLSearchParams(location.search);
  const hl = params.get('hl');
  if (hl === 'zh' || hl === 'en') return hl;
  return localStorage.getItem('hl') || 'en';
}

/** 应用指定语言到所有 data-i18n 元素 */
function applyTranslations(lang) {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const text = TRANSLATIONS[key]?.[lang];
    if (text) el.textContent = text;
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

/** 设置语言（切换 + 持久化） */
function setLang(lang) {
  localStorage.setItem('hl', lang);
  const url = new URL(window.location);
  url.searchParams.set('hl', lang);
  window.history.replaceState({}, '', url);
  applyTranslations(lang);
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
