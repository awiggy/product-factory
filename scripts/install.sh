#!/usr/bin/env bash
# 把 skills/ 下的 Skill 复制到指定目录（不会自动修改任何配置）。
#
#   ./scripts/install.sh                       # 默认安装到 ~/.claude/skills（Claude Code 个人 Skill 目录）
#   ./scripts/install.sh /path/to/project/.claude/skills   # 安装到某个项目
#   ./scripts/install.sh ~/.codex/skills       # 其他支持 SKILL.md 的助手，按其文档指定目录
#
# 目标目录中已存在同名 Skill 时会先备份为 <name>.bak-<时间>，不直接覆盖。
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)/skills"
DEST="${1:-$HOME/.claude/skills}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$DEST"
for dir in "$SRC"/*/; do
  name="$(basename "$dir")"
  if [ -e "$DEST/$name" ]; then
    mv "$DEST/$name" "$DEST/$name.bak-$STAMP"
    echo "已备份旧版本：$DEST/$name.bak-$STAMP"
  fi
  cp -R "$dir" "$DEST/$name"
  find "$DEST/$name" -name '.DS_Store' -delete 2>/dev/null || true
  echo "已安装：$name"
done
echo "完成。安装位置：$DEST"
