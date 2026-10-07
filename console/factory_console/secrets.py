"""API Key 保存：macOS 存钥匙串（security 命令），其他系统存用户目录下权限 600 的文件。Key 不进项目文件夹，也不返回给网页。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SERVICE = "product-factory"
FILE_PATH = os.environ.get("FACTORY_SECRETS_FILE") or os.path.join(
    os.path.expanduser("~"), ".config", "product-factory", "secrets.json")


def _use_keychain():
    return sys.platform == "darwin" and shutil.which("security") and not os.environ.get("FACTORY_SECRETS_FILE")


def _read_file():
    try:
        with open(FILE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_file(data):
    d = os.path.dirname(FILE_PATH)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".s.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, FILE_PATH)


def set_secret(account, value):
    value = (value or "").strip()
    if not value:
        raise ValueError("Key 不能为空")
    if _use_keychain():
        r = subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", account, "-w", value],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("写入钥匙串失败：%s" % (r.stderr.strip() or r.returncode))
        return
    data = _read_file()
    data[account] = value
    _write_file(data)


def get_secret(account):
    if _use_keychain():
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return _read_file().get(account)


def delete_secret(account):
    if _use_keychain():
        subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", account], capture_output=True)
        return
    data = _read_file()
    if account in data:
        del data[account]
        _write_file(data)


def masked(account):
    v = get_secret(account)
    if not v:
        return None
    return "已保存（尾号 %s）" % v[-4:] if len(v) >= 8 else "已保存"


def where():
    return "macOS 钥匙串" if _use_keychain() else FILE_PATH
