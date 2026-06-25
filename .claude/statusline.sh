#!/bin/bash
# ─── Claude Code Status Line ──────────────────────────────────────────
#   crypto v26.6.27  │  ██░░░░░░░░  ⇣43.0k/200k ⇡665  ⏱ 40m  │  deepseek-v4-pro ◆ xhigh
# ──────────────────────────────────────────────────────────────────────

set -euo pipefail
input=$(cat)

# ── JSON 字段 ─────────────────────────────────────────────────────────
REPO=$(echo "$input" | jq -r '.workspace.repo.name // ""')
DIR=$(echo "$input" | jq -r '.workspace.current_dir')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
DUR_MS=$(echo "$input" | jq -r '.cost.total_duration_ms // 0')
EFFORT=$(echo "$input" | jq -r '.effort.level // ""')
TOTAL_IN=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
TOTAL_OUT=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')
WIN_SIZE=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
EXCEEDS=$(echo "$input" | jq -r '.exceeds_200k_tokens // false')

# ── 模型名：优先从环境变量取真实名称，回退到 display_name ────────────
MODEL="${ANTHROPIC_MODEL:-}"
[ -z "$MODEL" ] && MODEL=$(echo "$input" | jq -r '.model.display_name')

# ── 回退 ──────────────────────────────────────────────────────────────
[ -z "$REPO" ] && REPO="${DIR##*/}"

# ── Git 分支（非 repo 则隐藏）─────────────────────────────────────────
BRANCH=$(git branch --show-current 2>/dev/null || echo "")

# ── ANSI 颜色 ─────────────────────────────────────────────────────────
C_RESET='\033[0m'
C_DIM='\033[2m'
C_GREEN='\033[32m'
C_YELLOW='\033[33m'
C_RED='\033[31m'
C_CYAN='\033[36m'
C_MAGENTA='\033[35m'

# ── 进度条 ────────────────────────────────────────────────────────────
FILLED=$((PCT / 10))
[ "$FILLED" -gt 10 ] && FILLED=10
EMPTY=$((10 - FILLED))
BAR=""
i=0; while [ $i -lt $FILLED ]; do BAR="${BAR}█"; i=$((i + 1)); done
i=0; while [ $i -lt $EMPTY ];  do BAR="${BAR}░"; i=$((i + 1)); done

# 4 档：绿(<70%) → 黄(70-89%) → 红(≥90%) → 洋红(超出 200k 窗口)
if   [ "$EXCEEDS" = "true" ]; then BAR_COLOR="$C_MAGENTA"
elif [ "$PCT" -ge 90 ]; then BAR_COLOR="$C_RED"
elif [ "$PCT" -ge 70 ]; then BAR_COLOR="$C_YELLOW"
else BAR_COLOR="$C_GREEN"
fi

# ── 时长格式化 ────────────────────────────────────────────────────────
DUR_SEC=$((DUR_MS / 1000))
DUR_MIN=$((DUR_SEC / 60))
DUR_H=$((DUR_MIN / 60))
DUR_M=$((DUR_MIN % 60))
if [ "$DUR_H" -gt 0 ]; then
    DUR_FMT="${DUR_H}h"
    [ "$DUR_M" -gt 0 ] && DUR_FMT="${DUR_H}h${DUR_M}m"
else
    DUR_FMT="${DUR_M}m"
fi

# ── Effort icon ────────────────────────────────────────────────────────
EFFORT_ICON=""
case "$EFFORT" in
  ultracode) EFFORT_ICON="⚡⚡" ;;
  max)       EFFORT_ICON="⚡" ;;
  xhigh)     EFFORT_ICON="◆ " ;;
  high)      EFFORT_ICON="◇ " ;;
  medium)    EFFORT_ICON="◦ " ;;
  low)       EFFORT_ICON="· " ;;
esac

# ── 构建第 1 段：身份 ──────────────────────────────────────────────────
SEG1="${C_CYAN}${REPO}${C_RESET}"
[ -n "$BRANCH" ] && SEG1="${SEG1} ${C_MAGENTA}${BRANCH}${C_RESET}"

# ── Token 格式化（12500 → 12.5k；prec=0 → 200k）───────────────────────
fmt_tok() {
    local n=$1
    local prec=${2:-1}
    if [ "$n" -ge 1000000 ]; then
        printf "%.*fM" "$prec" "$(echo "scale=$prec; $n/1000000" | bc)"
    elif [ "$n" -ge 1000 ]; then
        printf "%.*fk" "$prec" "$(echo "scale=$prec; $n/1000" | bc)"
    else
        printf "%d" "$n"
    fi
}

# ── 构建第 2 段：时长 + 上下文 ─────────────────────────────────────────
TOK_IN_FMT=$(fmt_tok "$TOTAL_IN")
TOK_OUT_FMT=$(fmt_tok "$TOTAL_OUT")
TOK_MAX_FMT=$(fmt_tok "$WIN_SIZE" 0)
SEG2="${BAR_COLOR}${BAR}${C_RESET}  ${C_CYAN}⇣${TOK_IN_FMT}/${TOK_MAX_FMT}${C_RESET} ${C_GREEN}⇡${TOK_OUT_FMT}${C_RESET}  ⏱ ${DUR_FMT}"

# ── 构建第 3 段：模型 + effort ─────────────────────────────────────────
SEG3="${MODEL} ${EFFORT_ICON}${EFFORT}"

# ── 渲染 ──────────────────────────────────────────────────────────────
printf "%b" "${SEG1}  │  ${SEG2}  │  ${SEG3}"
echo
