// 使用页面的真实渲染函数验证目录刷新后“默认”和自定义型号不会丢失。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
const functions = source.slice(source.indexOf("function modelPicker("), source.indexOf("\nfunction readSettingsForm("));
const target = { innerHTML: "" };
const context = {
  App: {},
  $: () => target,
  esc: (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
  statusPill: () => "",
  timeShort: (stamp) => "TIME " + stamp,
};
vm.createContext(context);
vm.runInContext(functions, context);

const models = [{ value: "gpt-test", label: "Test <Model>" }, { value: "gateway/my-model", label: "Gateway" }];
function render(value, details = {}) {
  context.App = {
    config: { executor: "codex", codex_source: "account", codex_model: value, model: "", pi_model: "" },
    execInfo: { detected: { codex: { models, models_source: "app_server", models_message: "读取目录", ...details } },
      clis: [], providers: [], provider_keys: {}, claude_models: [], pi_thinking: [], secret_store: "test" },
  };
  vm.runInContext("paintExecCards()", context);
  return target.innerHTML;
}
function picker(html) {
  return html.match(/<select[^>]*data-target="codex_model"[\s\S]*?<\/select>\s*<input[^>]*>/)[0];
}

let html = render("gpt-test");
assert.match(picker(html), /value="gpt-test" selected/);
assert.match(picker(html), /Test &lt;Model&gt;/);
assert.match(picker(html), /name="codex_model" value="gpt-test"[^>]*hidden/);
assert.match(html, /模型目录不保证当前账号或 API Key 的调用权限/);

html = render("");
assert.match(picker(html), /<option value="" selected>默认/);
assert.equal(context.App.config.codex_model, "");

html = render("private/model");
assert.match(picker(html), /value="__custom__" selected/);
assert.match(picker(html), /name="codex_model" value="private\/model"/);
assert.doesNotMatch(picker(html), /<input[^>]* hidden/);
assert.equal(context.App.config.codex_model, "private/model");

html = render("gateway/my-model", { models_source: "cache", models_fetched_at: "2026-10-07T12:00:00Z" });
assert.match(picker(html), /value="gateway\/my-model" selected/);
assert.match(html, /缓存时间：TIME 2026-10-07T12:00:00Z/);

html = render("private/model", { models: [], models_source: "unavailable", models_message: "目录读取失败" });
assert.match(picker(html), /value="__custom__" selected/);
assert.match(picker(html), /<option value="" >默认/);
assert.match(html, /目录读取失败/);
console.log("模型选择器回归通过。");
