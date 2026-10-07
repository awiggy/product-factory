"""AI 产品工厂控制台：本地运行的交互界面，状态与闸门复用 skills/product-factory/scripts/factory_gate.py。"""

import os

CONSOLE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PACKAGE_ROOT = os.path.abspath(os.path.join(CONSOLE_ROOT, ".."))
SKILLS_ROOT = os.path.join(PACKAGE_ROOT, "skills")
GATE_SCRIPT = os.path.join(SKILLS_ROOT, "product-factory", "scripts", "factory_gate.py")
INBOX_PROTOCOL = os.path.join(SKILLS_ROOT, "product-factory", "references", "inbox-protocol.md")
STATIC_ROOT = os.path.join(CONSOLE_ROOT, "static")
DATA_ROOT = os.path.join(CONSOLE_ROOT, "data")
