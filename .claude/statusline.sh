#!/bin/bash
# ─── Claude Code Status Line ──────────────────────────────────────────
#   crypto v26.6.27 +156/-23 │ ⏱ 2h ██████░░░░ │ deepseek-v4-pro ◆xhigh
# ──────────────────────────────────────────────────────────────────────

set -euo pipefail
input=$(cat)

# ── JSON 字段 ─────────────────────────────────────────────────────────
REPO=$(echo "$input" | jq -r '.workspace.repo.name // ""')
DIR=$(echo "$input" | jq -r '.workspace.current_dir')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
DUR_MS=$(echo "$input" | jq -r '.cost.total_duration_ms // 0')
ADDED=$(echo "$input" | jq -r '.cost.total_lines_added // 0')
REMOVED=$(echo "$input" | jq -r '.cost.total_lines_removed // 0')
EFFORT=$(echo "$input" | jq -r '.effort.level // ""')
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
EMPTY=$((10 - FILLED))
BAR=""
i=0; while [ $i -lt $FILLED ]; do BAR="${BAR}█"; i=$((i + 1)); done
i=0; while [ $i -lt $EMPTY ];  do BAR="${BAR}░"; i=$((i + 1)); done

if   [ "$PCT" -ge 90 ]; then BAR_COLOR="$C_RED"
elif [ "$PCT" -ge 70 ]; then BAR_COLOR="$C_YELLOW"
else BAR_COLOR="$C_GREEN"
fi

# ── 超 200k 标记 ───────────────────────────────────────────────────────
EXCEEDS_ICON=""
[ "$EXCEEDS" = "true" ] && EXCEEDS_ICON="⚡"

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

# ── 代码增删 ──────────────────────────────────────────────────────────
LINES=""
if [ "$ADDED" -gt 0 ] || [ "$REMOVED" -gt 0 ]; then
    LINES=" ${C_GREEN}+${ADDED}${C_RESET}/${C_RED}-${REMOVED}${C_RESET}"
fi

# ── Effort icon ────────────────────────────────────────────────────────
EFFORT_ICON=""
case "$EFFORT" in
  ultracode) EFFORT_ICON="⚡⚡ " ;;
  max)       EFFORT_ICON="⚡ " ;;
  xhigh)     EFFORT_ICON="◆ " ;;
  high)      EFFORT_ICON="◇ " ;;
  medium)    EFFORT_ICON="◦ " ;;
  low)       EFFORT_ICON="· " ;;
esac

# ── 构建第 1 段：身份 + 增删 ───────────────────────────────────────────
SEG1="${C_CYAN}${REPO}${C_RESET}"
[ -n "$BRANCH" ] && SEG1="${SEG1} ${C_MAGENTA}${BRANCH}${C_RESET}"
SEG1="${SEG1}${LINES}"

# ── 构建第 2 段：时长 + 上下文 ─────────────────────────────────────────
SEG2="⏱ ${DUR_FMT}  ${BAR_COLOR}${BAR}${EXCEEDS_ICON}${C_RESET}"

# ── 构建第 3 段：模型 + effort ─────────────────────────────────────────
SEG3="${MODEL}  ${EFFORT_ICON}${EFFORT}"

# ── 渲染 ──────────────────────────────────────────────────────────────
printf "%b" "${SEG1} │ ${SEG2} │ ${SEG3}"
echo
