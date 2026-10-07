"""Codex 模型目录的协议、失败回退与页面选择器回归。不会调用真实模型。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from factory_console import executors  # noqa: E402


class CodexModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "requests.jsonl")
        self.fake = os.path.join(self.tmp, "codex")
        with open(self.fake, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' %
                    (sys.executable, os.path.join(HERE, "fake_codex.py")))
        os.chmod(self.fake, 0o755)
        self.env = mock.patch.dict(os.environ, {"CODEX_HOME": self.tmp, "FAKE_CODEX_LOG": self.log,
                                               "FAKE_CODEX_MODELS_MODE": "pages"})
        self.env.start()
        self.cfg = {"codex_path": self.fake, "codex_source": "account"}

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def cache(self, rows=None, provider=None):
        with open(os.path.join(self.tmp, "models_cache.json"), "w", encoding="utf-8") as f:
            json.dump({"fetched_at": "2026-10-07T12:00:00Z", "identity": "secret-test-token",
                       "models": rows if rows is not None else [
                           {"slug": "cached-model", "display_name": "Cached", "visibility": "list",
                            "token": "secret-test-token"},
                           {"slug": "hidden-model", "visibility": "hide"}]}, f)
        if provider:
            with open(os.path.join(self.tmp, "config.toml"), "w", encoding="utf-8") as f:
                f.write('model_provider = "%s"\n' % provider)

    def test_official_protocol_pagination_and_safe_output(self):
        self.cache()
        result = executors.codex_models(self.fake, self.cfg)
        self.assertEqual(result["models_source"], "app_server")
        self.assertEqual(result["models"], [{"value": "gpt-test-a", "label": "Test A"},
                                            {"value": "custom/provider-model", "label": "Custom"}])
        self.assertNotIn("secret-test-token", json.dumps(result))
        with open(self.log, encoding="utf-8") as f:
            requests = [r["request"] for r in map(json.loads, f) if "request" in r]
        self.assertEqual([r["method"] for r in requests],
                         ["initialize", "initialized", "model/list", "model/list"])
        self.assertFalse(requests[2]["params"]["includeHidden"])
        self.assertEqual(requests[3]["params"]["cursor"], "page-2")

    def test_detect_includes_models_without_other_installed_tools(self):
        with mock.patch.object(executors, "_which", side_effect=lambda p: self.fake if p == self.fake else None):
            info = executors.detect(self.cfg)["codex"]
        self.assertTrue(info["logged_in"])
        self.assertEqual(info["models_source"], "app_server")
        self.assertEqual(len(info["models"]), 2)

    def test_failure_uses_labelled_cache_and_never_raw_errors(self):
        self.cache()
        for mode in ("error", "invalid", "repeat_cursor"):
            with self.subTest(mode=mode), mock.patch.dict(os.environ, {"FAKE_CODEX_MODELS_MODE": mode}):
                result = executors.codex_models(self.fake, self.cfg)
                self.assertEqual(result["models_source"], "cache")
                self.assertEqual(result["models"], [{"value": "cached-model", "label": "Cached"}])
                self.assertEqual(result["models_fetched_at"], "2026-10-07T12:00:00Z")
                self.assertNotIn("secret-test-token", json.dumps(result))

    def test_empty_official_catalog_does_not_use_stale_cache(self):
        self.cache()
        with mock.patch.dict(os.environ, {"FAKE_CODEX_MODELS_MODE": "empty"}):
            result = executors.codex_models(self.fake, self.cfg)
        self.assertEqual(result["models_source"], "app_server")
        self.assertEqual(result["models"], [])

    def test_timeout_reaps_child(self):
        self.check_timeout("hang")

    @unittest.skipUnless(os.name == "posix", "包装器进程组回收用于 macOS/Linux")
    def test_timeout_reaps_wrapper_descendant_holding_stdout(self):
        self.check_timeout("descendant_hang")

    def check_timeout(self, mode):
        children = []
        real_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        started = time.monotonic()
        with mock.patch.dict(os.environ, {"FAKE_CODEX_MODELS_MODE": mode}), \
                mock.patch.object(executors.subprocess, "Popen", side_effect=spawn):
            result = executors._codex_app_server_models(self.fake, self.cfg, timeout=0.1)
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed and children[0].stdin.closed)

    def test_custom_provider_keeps_official_models_and_skips_openai_cache(self):
        self.cache(provider="my-gateway")
        self.assertEqual(executors.codex_models(self.fake, self.cfg)["models_source"], "app_server")
        with mock.patch.dict(os.environ, {"FAKE_CODEX_MODELS_MODE": "error"}):
            result = executors.codex_models(self.fake, self.cfg)
        self.assertEqual(result["models_source"], "unavailable")
        self.assertEqual(result["models"], [])

    def test_profile_and_custom_catalog_do_not_get_openai_cache(self):
        self.cache()
        for text in ('profile = "gateway"\n[profiles.gateway]\nmodel_provider = "custom"\n',
                     'model_catalog_json = "/my/catalog.json"\n',
                     'model_provider = """custom"""\n'):
            with self.subTest(text=text):
                with open(os.path.join(self.tmp, "config.toml"), "w", encoding="utf-8") as f:
                    f.write(text)
                with mock.patch.object(executors, "_codex_app_server_models", return_value=None):
                    self.assertEqual(executors.codex_models(self.fake, self.cfg)["models_source"], "unavailable")

    def test_api_key_catalog_query_does_not_read_or_inject_factory_key(self):
        with mock.patch.object(executors.secrets, "get_secret", side_effect=AssertionError("不应读取工厂 Key")):
            result = executors.codex_models(self.fake, dict(self.cfg, codex_source="api_key"))
        self.assertEqual(result["models_source"], "app_server")
        with open(self.log, encoding="utf-8") as f:
            calls = [r for r in map(json.loads, f) if "args" in r]
        self.assertFalse(calls[0]["has_key"])

    def test_missing_or_invalid_cache_preserves_manual_fallback(self):
        for raw in (None, "not json", "[]", '{"models": "bad"}'):
            with self.subTest(raw=raw):
                path = os.path.join(self.tmp, "models_cache.json")
                if raw is not None:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(raw)
                elif os.path.exists(path):
                    os.remove(path)
                with mock.patch.object(executors, "_codex_app_server_models", return_value=None):
                    result = executors.codex_models(self.fake, self.cfg)
                self.assertEqual(result["models_source"], "unavailable")
                self.assertIn("其他", result["models_message"])

    def test_cache_deduplication_validation_and_api_filter(self):
        self.cache(rows=[{"slug": "chatgpt-only", "visibility": "list", "supported_in_api": False},
                         {"slug": "api-model", "visibility": "list", "supported_in_api": True},
                         {"slug": "api-model", "visibility": "list"}, {"slug": "bad model", "visibility": "list"},
                         {"slug": "hidden", "visibility": "hide"}, None])
        with mock.patch.object(executors, "_codex_app_server_models", return_value=None):
            result = executors.codex_models(self.fake, dict(self.cfg, codex_source="api_key"))
        self.assertEqual(result["models"], [{"value": "api-model", "label": "api-model"}])


class ModelPickerTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "页面选择器回归需要 Node.js；后端测试只用标准库")
    def test_codex_options_default_custom_and_cache_hint(self):
        result = subprocess.run([shutil.which("node"), os.path.join(HERE, "test_settings_models.cjs")],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
