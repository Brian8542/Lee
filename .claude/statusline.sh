#!/usr/bin/env bash
# Claude Code status line: model | folder | git branch | context usage | cost
input=$(cat)

model=$(echo "$input" | jq -r '.model.display_name // "Claude"')
dir=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // "."')
pct=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
cost=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')

branch=""
if git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then
  branch=" | $(git -C "$dir" branch --show-current 2>/dev/null)"
fi

printf '[%s] %s%s | ctx %s%% | $%.2f\n' "$model" "${dir##*/}" "$branch" "$pct" "$cost"
