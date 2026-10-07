"""对 factory_gate.py 的进程内封装：读取用模块函数，写入走同一套命令行逻辑，保证界面与命令行行为一致。"""

import contextlib
import importlib.util
import io
import threading

from . import GATE_SCRIPT

_spec = importlib.util.spec_from_file_location("factory_gate", GATE_SCRIPT)
fg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fg)

# 同一产品的状态写入串行化
_locks = {}
_locks_guard = threading.Lock()


def lock_for(product_dir):
    with _locks_guard:
        if product_dir not in _locks:
            _locks[product_dir] = threading.RLock()
        return _locks[product_dir]


class GateError(Exception):
    def __init__(self, message, output=""):
        super().__init__(message)
        self.output = output


def run(argv):
    """执行 factory_gate 子命令，返回 (退出码, 输出)。不抛 SystemExit。"""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fg.main(argv)
        except SystemExit as e:  # die() 与 check 失败都会走这里
            code = e.code if isinstance(e.code, int) else 1
    text = (out.getvalue() + err.getvalue()).strip()
    return code, text


def must(argv):
    code, text = run(argv)
    if code != 0:
        raise GateError(text.replace("错误：", "").strip() or "操作失败", text)
    return text


def stage_config():
    cfg, order, defs = fg.stage_defs()
    return cfg, order, defs


def load_state(product_dir):
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return fg.load_state(product_dir)
    except SystemExit:
        raise GateError(err.getvalue().replace("错误：", "").strip() or "无法读取 state.json")


def problems(product_dir, state, stage_id):
    return fg.gate_problems(product_dir, state, stage_id)


def achieved_level(stage_state):
    cfg, _, _ = fg.stage_defs()
    i = fg.achieved_level(cfg, stage_state)
    return cfg["evidence_levels"][i] if i >= 0 else None


def has_approval(state, aid):
    return fg.has_approval(state, aid)


def validate(state):
    return fg.validate_state(state)


TEMPLATE_MARKER = fg.TEMPLATE_MARKER
