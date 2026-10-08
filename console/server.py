#!/usr/bin/env python3
"""启动 AI 产品工厂控制台：python3 console/server.py [--port 8765] [--no-browser]"""

import argparse
import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.version_info < (3, 9):
    sys.exit("需要 Python 3.9 或更高版本。当前是 %s。" % sys.version.split()[0])

from factory_console.app import make_server  # noqa: E402
from factory_console import preview  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="AI 产品工厂控制台")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        srv = make_server(port=a.port)
    except OSError:
        sys.exit("端口 %d 被占用了。可能控制台已经在运行，直接打开 http://localhost:%d ；或用 --port 换一个端口。"
                 % (a.port, a.port))
    url = "http://localhost:%d" % srv.server_address[1]
    print("AI 产品工厂控制台已启动：%s" % url)
    print("关闭这个窗口（或按 Ctrl+C）即可停止。")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    import signal

    def _quit(*_):
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):      # 关掉终端窗口时也停掉产品预览
        if sig is not None:
            signal.signal(sig, _quit)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        preview.stop_all()
        print("\n已停止。")


if __name__ == "__main__":
    main()
