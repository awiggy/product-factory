#!/bin/bash
# 双击打开 AI 产品工厂控制台（macOS）。关闭这个终端窗口即可停止。
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 python3。请先安装 Python 3（https://www.python.org/downloads/），再双击本文件。"
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi
python3 console/server.py "$@"
