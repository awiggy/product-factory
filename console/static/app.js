import { renderMarkdown, esc } from "./md.js";

// ------------------------------------------------------------------ 基础

const $ = (sel, root = document) => root.querySelector(sel);
const main = () => $("#main");

async function req(method, path, body) {
  const opt = { method, headers: { "X-Factory": "1" } };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opt);
  } catch (e) {
    throw new Error("连不上控制台。确认启动窗口还开着，然后刷新页面。");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "操作失败（" + res.status + "）");
  return data;
}
const get = (p) => req("GET", p);
const post = (p, b = {}) => req("POST", p, b);

function toast(msg, isErr = false) {
  const z = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.setAttribute("role", isErr ? "alert" : "status");
  el.textContent = msg;
  z.appendChild(el);
  setTimeout(() => el.remove(), isErr ? 7000 : 3200);
}

const App = {
  config: null,
  guides: null,
  pid: null,
  detail: null,
  sigs: {},
  docTab: null,
  check: {},          // 验收清单进度：key -> {idx, results}
  feedSince: 0,
  feedRun: null,
  timers: [],
  open: {},           // 侧栏展开的表单
};

function clearTimers() {
  App.timers.forEach((t) => clearTimeout(t));
  App.timers = [];
}
function later(fn, ms) {
  App.timers.push(setTimeout(fn, ms));
}

function term(word, shown) {
  const g = App.guides && App.guides.glossary[word];
  if (!g) return esc(shown || word);
  return `<span class="term" tabindex="0" data-term="${esc(word)}">${esc(shown || word)}</span>`;
}
function timeShort(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const now = new Date();
  const hm = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === now.toDateString() ? hm : d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" }) + " " + hm;
}
function fmtTokens(t) {
  const n = (t.input || 0) + (t.output || 0);
  return n >= 10000 ? (n / 10000).toFixed(1) + " 万 token" : n + " token";
}
function list(items, cls = "") {
  if (!items || !items.length) return "";
  return `<ul class="${cls}">` + items.map((x) => "<li>" + esc(String(x)) + "</li>").join("") + "</ul>";
}

// ------------------------------------------------------------------ 顶栏

function renderTopbar() {
  const mode = (App.config && App.config.executor) || "demo";
  const label = (App.config && App.config.executor_label) || "演示模式";
  const b = $("#exec-badge");
  b.dataset.mode = mode;
  b.innerHTML = `<span class="dot"></span><span class="label">AI 执行方式：</span>${label}`;
  const r = location.hash.split("/")[1] || "";
  document.querySelectorAll(".nav a").forEach((a) => {
    a.toggleAttribute("aria-current", (a.dataset.nav === "home" && (r === "" || r === "p")) || a.dataset.nav === r);
    if (a.hasAttribute("aria-current")) a.setAttribute("aria-current", "page");
  });
}

// ------------------------------------------------------------------ 首页

const EXAMPLES = [
  ["论文阅读助手", "帮研究生读英文论文：上传 PDF 后得到中英对照和术语解释，术语能积累成个人词库。"],
  ["面试陪练", "求职者上传岗位描述，AI 扮演面试官进行语音模拟面试，结束后给出逐题点评。"],
  ["门店周报", "连锁店长每周上传销售表格，自动生成带图表的周报和三条改进建议。"],
];

async function renderHome() {
  const data = await get("/api/products");
  const items = data.products || [];
  const startBox = `
    <section class="home-start">
      <h1>你想做个什么产品？</h1>
      <p class="lead">说说你的想法，AI 会一轮轮把它问清楚，再从 ${term("PRD")} 一路推进到上线。每到需要你决定的地方，它会停下来等你。</p>
      <form class="sheet idea-box" id="new-form">
        <label class="field"><span>产品名</span><input type="text" name="name" required maxlength="40" placeholder="比如：论文阅读助手"></label>
        <label class="field"><span>一两句话说说你的想法</span>
          <textarea name="idea" required placeholder="给谁用、解决什么麻烦、最后能得到什么"></textarea></label>
        <div class="examples" aria-label="示例想法">${EXAMPLES.map((e, i) => `<button type="button" class="example" data-action="example" data-i="${i}">${esc(e[0])}</button>`).join("")}</div>
        <details><summary class="small muted" style="cursor:pointer">补充材料（可选）</summary>
          <label class="field" style="margin-top:10px"><span>竞品、草稿、要求……想到什么都可以贴进来</span><textarea name="notes"></textarea></label>
        </details>
        <div class="btn-row" style="margin-top:14px"><button class="btn btn-primary" type="submit">开始，进入 PRD 访谈</button>
          <span class="small muted">产品文件会放在 ${esc((App.config && App.config.workspace) || "")}</span></div>
      </form>
      <div class="home-alt">
        <button class="btn-quiet btn" data-action="demo">先看看演示产品（不调用 AI）</button>
        <button class="btn-quiet btn" data-action="toggle-import">打开已有产品文件夹</button>
      </div>
      <form id="import-form" class="sheet idea-box" hidden style="margin-top:12px">
        <label class="field"><span>产品文件夹的完整路径（里面有 factory/state.json）</span><input type="text" name="path" placeholder="/Users/你的名字/Product factory/products/某个产品"></label>
        <button class="btn" type="submit">打开</button>
      </form>
    </section>`;
  if (!items.length) {
    main().innerHTML = startBox;
    return;
  }
  const rows = items.map((p) => {
    if (p.error) return `<li class="product-row"><span>${esc(p.path)}</span><span class="err">${esc(p.error)}</span></li>`;
    const idx = p.stages.findIndex((s) => s.id === p.current_stage);
    const dots = p.stages.map((s, i) => (i ? `<i class="${i <= idx ? "done" : ""}"></i>` : "") +
      `<b class="${s.id === p.current_stage ? "current" : s.status}" title="${esc(App.guides.stages[s.id].short)}"></b>`).join("");
    const na = p.next_action;
    let pill = "";
    if (p.busy) pill = `<span class="pill pill-ai">AI 正在工作</span>`;
    else if (na) {
      const due = ["answer", "actions", "checklist", "approve", "release_go", "blocked", "fix"].includes(na.kind);
      pill = `<span class="pill ${due ? "pill-due" : ""}">${due ? "待你处理：" : ""}${esc(na.title)}</span>`;
    }
    return `<li class="product-row">
      <div><a class="name" href="#/p/${p.id}">${esc(p.name)}</a>
        <div class="small muted">v${p.version}${p.demo ? "，演示产品" : ""}</div></div>
      <div><div class="mini-line" aria-label="当前在 ${esc(p.current_title)}">${dots}</div>
        <div class="small muted" style="margin-top:6px">${esc(p.current_title)}</div></div>
      <div>${pill}</div>
      <a class="btn" href="#/p/${p.id}">打开</a></li>`;
  }).join("");
  main().innerHTML = `
    <div class="section-head"><h2>我的产品</h2><button class="btn btn-primary" data-action="show-new">新建产品</button></div>
    <ul class="product-list sheet">${rows}</ul>
    <div id="new-wrap" hidden>${startBox}</div>`;
}

// ------------------------------------------------------------------ 产品页

const DUE_KINDS = ["answer", "actions", "checklist", "approve", "release_go", "blocked", "fix", "manual_wait"];

async function loadProduct(pid, force = false) {
  const d = await get("/api/products/" + pid);
  if (App.pid !== pid) return;
  App.detail = d;
  paintProduct(force);
  const busy = d.active_run && d.active_run.status === "running";
  later(() => loadProduct(pid).catch(() => {}), busy ? 1500 : 5000);
}

function paintProduct(force) {
  const d = App.detail;
  if (!$("#p-root") || force) {
    App.sigs = {};
    main().innerHTML = `<div id="p-root">
      <div class="p-head" id="p-head"></div>
      <div class="line-wrap"><ol class="line" id="p-line" aria-label="生产线"></ol></div>
      <div class="bench">
        <div><div id="p-brief"></div><div id="p-task"></div><div id="p-docs"></div></div>
        <aside class="sheet inspect" id="p-side" aria-label="质检单"></aside>
      </div></div>`;
  }
  part("head", JSON.stringify([d.product, d.demo, d.path]), "#p-head", headHTML);
  part("line", JSON.stringify([d.stages, d.current_stage, d.active_run, d.next_action.kind]), "#p-line", lineHTML, (el) => {
    const cur = el.querySelector("li.current");
    const wrap = el.parentElement;
    if (cur && wrap.scrollWidth > wrap.clientWidth) wrap.scrollLeft = cur.offsetLeft - wrap.clientWidth / 2 + cur.offsetWidth / 2;
  });
  part("brief", JSON.stringify([d.current_stage, d.inbox && d.inbox.summary, d.stage.status]), "#p-brief", briefHTML);
  const taskSig = JSON.stringify([d.current_stage, d.next_action, d.inbox && d.inbox.round, d.active_run && d.active_run.id,
    d.active_run && d.active_run.status, d.checklist_results, d.actions_done, d.approvals_needed, d.release_go]);
  if (!editing("#p-task")) part("task", taskSig, "#p-task", taskHTML, afterTask);
  const pick = $("#doc-pick");
  if (!(pick && document.activeElement === pick)) {
    part("docs", JSON.stringify([d.current_stage, d.stage.artifacts, d.inbox && d.inbox.round, d.docs]), "#p-docs", docsHTML, afterDocs);
  }
  if (!editing("#p-side")) part("side", JSON.stringify([d.stage, d.problems, d.approvals, d.waivers, d.runs, d.cost_total_usd, App.open]), "#p-side", sideHTML);
  if (d.active_run && d.active_run.status === "running") pollFeed();
}

function editing(sel) {
  const root = $(sel);
  if (!root) return false;
  const a = document.activeElement;
  if (a && root.contains(a) && (a.tagName === "TEXTAREA" || (a.tagName === "INPUT" && (a.type === "text" || a.type === "password")))) return true;
  if (root.querySelector(".inline-form:not([hidden])")) return true;
  return !!root.querySelector("[data-dirty]");
}

function resetEditing() {
  document.querySelectorAll("[data-dirty]").forEach((x) => x.removeAttribute("data-dirty"));
  document.querySelectorAll(".inline-form").forEach((x) => { x.hidden = true; });
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
}

function part(key, sig, sel, fn, after) {
  if (App.sigs[key] === sig) return;
  App.sigs[key] = sig;
  const el = $(sel);
  if (!el) return;
  el.innerHTML = fn(App.detail);
  if (after) after(el);
}

function headHTML(d) {
  return `<div><h1>${esc(d.product.name)}</h1>
      <div class="meta">v${d.product.version}　${esc(d.path)}</div></div>
    <div class="btn-row">${d.demo ? `<span class="pill pill-due">演示产品：不会调用 AI</span>` : ""}
      <a class="btn btn-quiet" href="#/">返回产品列表</a></div>`;
}

function lineHTML(d) {
  const idx = d.stages.findIndex((s) => s.id === d.current_stage);
  const running = d.active_run && d.active_run.status === "running";
  const due = DUE_KINDS.includes(d.next_action.kind);
  return d.stages.map((s, i) => {
    const cur = s.id === d.current_stage;
    const cls = [cur ? "current" : s.status, i <= idx ? "reached" : "", cur && running ? "running" : "",
      cur && s.blockers ? "blocked" : "", cur && due ? "due" : ""].join(" ");
    const mark = s.status === "passed" ? "✓" : s.status === "skipped" ? "–" : i + 1;
    let sub = "";
    if (cur) sub = running ? "AI 工作中" : due ? "待你处理" : s.blockers ? "有阻塞" : "进行中";
    else if (s.status === "skipped") sub = "已跳过";
    return `<li class="${cls}" ${cur ? 'aria-current="step"' : ""}>
      <span class="station" aria-hidden="true">${mark}</span>
      <span class="st-name">${esc(App.guides.stages[s.id].short)}</span>
      <span class="st-sub">${sub}</span></li>`;
  }).join("");
}

function briefHTML(d) {
  const g = d.stage.guide;
  const box = d.inbox;
  return `<section class="sheet brief">
      <h2>${esc(d.stage.title)}</h2>
      <dl><dt>这一步</dt><dd>${esc(g.what)}</dd><dt>你要做</dt><dd>${esc(g.you)}</dd><dt>会得到</dt><dd>${esc(g.get)}</dd></dl>
    </section>
    ${box && box.summary ? `<div class="ai-says"><span class="who">AI 说</span><div>${esc(box.summary)}</div></div>` : ""}
    ${d.inbox_problems && d.inbox_problems.length ? `<div class="ai-says" style="border-color:var(--due)"><span class="who" style="color:var(--due)">注意</span><div>${list(d.inbox_problems)}</div></div>` : ""}`;
}

// ---------- 任务区

function taskShell(cls, kicker, title, detail, body) {
  return `<section class="sheet task ${cls}"><div class="task-kicker">${kicker}</div><h3>${esc(title)}</h3>
    ${detail ? `<p class="detail">${esc(detail)}</p>` : ""}${body}</section>`;
}

function taskHTML(d) {
  const na = d.next_action;
  const box = d.inbox || {};
  switch (na.kind) {
    case "running":
      return taskShell("ai", "AI 正在工作", na.title, na.detail,
        `<div class="working"><span class="bar"></span><span id="elapsed">进行中</span></div>
         <ul class="feed" id="feed" aria-live="polite"></ul>
         <button class="btn" data-action="stop">停止</button>`);
    case "manual_wait":
      return taskShell("due", "手动模式", na.title, na.detail, `<div id="manual-box"><p class="muted">正在准备指令…</p></div>`);
    case "answer":
      return taskShell("due", "待你处理", na.title, na.detail, answerForm(box, d.answers));
    case "actions":
      return taskShell("due", "待你处理", na.title, na.detail, actionsForm(box, d.actions_done));
    case "checklist":
      return taskShell("due", "待你处理", na.title, na.detail, checklistHTML(d));
    case "fix": {
      const fails = box.checklist.filter((c) => (d.checklist_results[c.id] || {}).result === "fail");
      return taskShell("bad", "验收没通过", na.title, na.detail,
        `<ul>${fails.map((c) => `<li><b>${esc(c.do)}</b><br><span class="muted">你看到的：${esc(d.checklist_results[c.id].note)}</span></li>`).join("")}</ul>
         <div class="btn-row"><button class="btn btn-primary" data-action="run" data-mode="fix">让 AI 修复</button>
         <button class="btn btn-quiet" data-action="recheck">重新验收</button></div>`);
    }
    case "blocked":
      return taskShell("bad", "遇到阻塞", na.title, na.detail,
        `${list(d.stage.blockers)}
         <label class="field"><span>补充信息或你的决定</span><textarea id="fb-text" placeholder="比如：先不用接入微信登录，用邀请码就行"></textarea></label>
         <div class="btn-row"><button class="btn btn-primary" data-action="feedback" data-kind="info">补充信息，让 AI 再试</button></div>`);
    case "approve":
      return approvalCard(d);
    case "release_go":
      return releaseGoCard(d);
    case "advance": {
      const last = d.current_stage === "release";
      return taskShell("ai", "可以往下走了", na.title, na.detail,
        `<label class="ack"><input type="checkbox" id="autostart" checked> 进入后让 AI 直接开始下一阶段</label>
         <div class="btn-row"><button class="btn btn-primary" data-action="advance">${last ? "进入运营阶段" : "进入下一阶段"}</button></div>`);
    }
    case "operate":
      return taskShell("ai", "上线之后", na.title, na.detail,
        `<div class="btn-row" style="margin-bottom:16px"><button class="btn" data-action="run" data-mode="${box.round ? "continue" : "start"}">让 AI 整理反馈</button></div>
         <label class="field"><span>下一版要做什么？</span><textarea id="iterate-reason" placeholder="比如：支持批量上传，修复长表格对齐"></textarea></label>
         <button class="btn btn-primary" data-action="iterate">开始 v${d.product.version + 1}</button>
         <p class="hint">当前版本的全部记录会归档到 factory/history/v${d.product.version}/，然后从 PRD 的修订开始。</p>`);
    default: {
      const label = na.kind === "start" ? na.title : na.kind === "deploy" ? "开始部署" : na.title;
      const fb = d.pending_feedback && d.pending_feedback.length
        ? `<p class="small muted">会附上你的 ${d.pending_feedback.length} 条留言。</p>` : "";
      const skip = d.stage.skippable && na.kind === "start"
        ? `<button class="btn btn-quiet" data-action="toggle" data-target="skip-form">这个产品不需要这一步</button>` : "";
      return taskShell(na.kind === "deploy" ? "due" : "ai", "下一步", label, na.detail,
        `${fb}${problemsHint(d)}
         <div class="btn-row"><button class="btn btn-primary" data-action="run" data-mode="${na.mode || "continue"}">${esc(label)}</button>
           <button class="btn btn-quiet" data-action="toggle" data-target="note-form">先给 AI 留言</button>${skip}</div>
         <div class="inline-form" id="note-form" hidden>
           <label class="field"><span>写给 AI 的话（会附在这次任务里）</span><textarea id="note-text"></textarea></label>
           <button class="btn" data-action="feedback" data-kind="info" data-src="note-text">附上留言并开始</button></div>
         <div class="inline-form" id="skip-form" hidden>
           <label class="field"><span>为什么不需要？</span><input type="text" id="skip-reason" placeholder="比如：纯 API 产品，没有界面"></label>
           <button class="btn" data-action="skip">跳过这一阶段</button></div>`);
    }
  }
}

function problemsHint(d) {
  const ps = d.problems.filter((p) => !p.startsWith("缺少用户审批") && !p.startsWith("需声明"));
  if (!ps.length || d.next_action.kind === "start") return "";
  return `<div class="small muted" style="margin-bottom:12px">还没完成：${list(ps)}</div>`;
}

function answerForm(box, answers) {
  const qs = box.questions.map((q) => {
    let input;
    if (q.type === "choice") {
      input = q.options.map((o) => `<label class="choice"><input type="radio" name="${esc(q.id)}" value="${esc(o)}" ${answers[q.id] === o ? "checked" : ""}><span>${esc(o)}</span></label>`).join("") +
        `<label class="choice"><input type="radio" name="${esc(q.id)}" value="__other"><span>其他：<input type="text" data-other="${esc(q.id)}" style="margin-top:4px" aria-label="其他答案"></span></label>`;
    } else if (q.type === "multi") {
      const cur = Array.isArray(answers[q.id]) ? answers[q.id] : [];
      input = q.options.map((o) => `<label class="choice"><input type="checkbox" name="${esc(q.id)}" value="${esc(o)}" ${cur.includes(o) ? "checked" : ""}><span>${esc(o)}</span></label>`).join("");
    } else {
      input = `<textarea name="${esc(q.id)}" placeholder="${esc(q.example ? "比如：" + q.example : "")}" aria-label="${esc(q.text)}">${esc(answers[q.id] || "")}</textarea>`;
    }
    return `<div class="q"><div class="q-text">${esc(q.text)}${q.required ? "" : ' <span class="small muted">（可选）</span>'}</div>
      ${q.why ? `<div class="q-why">为什么问：${esc(q.why)}</div>` : ""}${input}</div>`;
  }).join("");
  return `<form id="answer-form">${qs}<div class="btn-row" style="margin-top:12px">
    <button class="btn btn-primary" type="submit">提交回答，让 AI 继续</button>
    <span class="small muted">答不上来可以写“不确定”，AI 会把它记为待确认。</span></div></form>`;
}

function envFieldsHTML(a, done) {
  const field = (f) => {
    const name = `env:${a.id}:${f.key}`;
    const lab = `${esc(f.label)}${f.required ? "" : "（可选）"}${f.label !== f.key ? ` <code>${esc(f.key)}</code>` : ""}`;
    const state = f.filled ? ` <span class="pill pill-ok">已填写</span>` : "";
    let input;
    if (f.secret) {
      input = `<input type="password" name="${esc(name)}" autocomplete="new-password" spellcheck="false"
        placeholder="${f.filled ? "已填写；粘贴新值可替换，留空保持不变" : "粘贴到这里"}">`;
    } else if (f.options && f.options.length) {
      input = `<input type="text" name="${esc(name)}" list="dl-${esc(a.id + f.key)}" value="${esc(f.value || "")}">
        <datalist id="dl-${esc(a.id + f.key)}">${f.options.map((o) => `<option value="${esc(o)}">`).join("")}</datalist>`;
    } else {
      input = `<input type="text" name="${esc(name)}" value="${esc(f.value || "")}" spellcheck="false">`;
    }
    const help = f.help && f.help !== f.key ? `<div class="hint">${esc(f.help)}</div>` : "";
    return `<label class="field"><span>${lab}${state}</span>${input}${help}</label>`;
  };
  return `<div class="env-fields">${a.fields.map(field).join("")}
    <div class="hint">保存后由控制台写入产品文件夹的 <code>${esc(a.file)}</code>（已加入 .gitignore，不会上传到 Git）。保密内容不会发给 AI，也不会再显示在页面上。</div>
    ${done.includes(a.id) ? `<div class="small ok-text">已写入</div>` : ""}</div>`;
}

function actionsForm(box, done) {
  return `<form id="actions-form">${box.user_actions.map((a) => `
    <div class="action-card"><h4>${esc(a.title)}</h4>
      ${a.fields && a.fields.length
        ? envFieldsHTML(a, done) + (a.steps.length ? `<details class="small"><summary class="muted">AI 写的原始说明</summary><ol>${a.steps.map((s) => "<li>" + esc(s) + "</li>").join("")}</ol></details>` : "")
        : `${a.steps.length ? "<ol>" + a.steps.map((s) => "<li>" + esc(s) + "</li>").join("") + "</ol>" : ""}
      ${a.done_when ? `<div class="small muted" style="margin-bottom:8px">${esc(a.done_when)}</div>` : ""}
      <label class="check-done"><input type="checkbox" name="done" value="${esc(a.id)}" ${done.includes(a.id) ? "checked" : ""}> 已完成</label>`}
    </div>`).join("")}
    <div class="btn-row"><button class="btn btn-primary" type="submit">保存${box.user_actions.some((a) => a.fields && a.fields.length) ? "并继续" : ""}</button>
    <span class="small muted">全部完成后，AI 才能继续往下做。</span></div></form>`;
}

function checkKey(d) {
  return d.id + ":" + d.current_stage + ":" + d.inbox.round;
}

function checklistHTML(d) {
  const box = d.inbox;
  const key = checkKey(d);
  if (!App.check[key]) App.check[key] = { idx: 0, results: Object.assign({}, d.checklist_results) };
  const st = App.check[key];
  const items = box.checklist;
  const i = Math.min(st.idx, items.length);
  const dots = items.map((c, k) => `<span class="${st.results[c.id] ? st.results[c.id].result : k === i ? "now" : ""}"></span>`).join("");
  if (i >= items.length) {
    const fails = items.filter((c) => st.results[c.id] && st.results[c.id].result === "fail").length;
    return `<div class="step-dots" aria-hidden="true">${dots}</div>
      <p>${fails ? `有 ${fails} 步没通过。提交后可以把问题交给 AI 修复。` : "全部通过。提交后就可以签字了。"}</p>
      <div class="btn-row"><button class="btn btn-primary" data-action="submit-check">提交验收结果</button>
      <button class="btn btn-quiet" data-action="check-back">回到上一步</button></div>`;
  }
  const c = items[i];
  const r = st.results[c.id] || {};
  return `<div class="step-dots" aria-hidden="true">${dots}</div>
    <div class="step-count">第 ${i + 1} 步，共 ${items.length} 步</div>
    <div class="step-box"><div class="do">${esc(c.do)}</div>
      ${c.expect ? `<div class="expect">应该看到：<b>${esc(c.expect)}</b></div>` : ""}</div>
    <div class="btn-row"><button class="btn btn-pass" data-action="check-pass">和预期一样，通过</button>
      <button class="btn btn-fail" data-action="toggle" data-target="fail-form">不对</button>
      ${i > 0 ? `<button class="btn btn-quiet" data-action="check-back">上一步</button>` : ""}</div>
    <div class="inline-form" id="fail-form" ${r.result === "fail" ? "" : "hidden"}>
      <label class="field"><span>你看到了什么？（越具体，AI 越好修）</span><textarea id="fail-note">${esc(r.note || "")}</textarea></label>
      <button class="btn btn-fail" data-action="check-fail">记为不通过，下一步</button></div>`;
}

function approvalCard(d) {
  const ap = d.approvals_needed[0];
  const s = (d.inbox && d.inbox.approval_summary) || { done: "", verified: [], unverified: [], new_costs: [], questions: [], next: "" };
  const risky = s.unverified.length || s.new_costs.length;
  const sealWord = { prd_signoff: "确认", blueprint_signoff: "确认", adaptation_confirm: "确认", build_acceptance: "验收", frontend_acceptance: "验收", launch_acceptance: "上线" }[ap.id] || "批准";
  return `<section class="sheet task due approval" id="approval">
    <div class="seal-stamp" id="stamp" aria-hidden="true">${sealWord}</div>
    <div class="task-kicker">待你签字</div><h3>${esc(ap.name)}</h3>
    <p class="detail">${esc(ap.ask)}</p>
    ${s.done ? `<div class="ap-sec"><h4>这一步做成了什么</h4><div>${esc(s.done)}</div></div>` : ""}
    ${s.verified.length ? `<div class="ap-sec"><h4>已验证</h4>${list(s.verified)}</div>` : ""}
    ${s.unverified.length ? `<details class="ap-sec" data-must><summary>未验证（${s.unverified.length} 项）</summary>${list(s.unverified)}</details>` : ""}
    ${s.new_costs.length ? `<details class="ap-sec" data-must><summary>新增费用、外部平台或数据外传（${s.new_costs.length} 项）</summary>${list(s.new_costs)}</details>` : ""}
    ${s.questions.length ? `<div class="ap-sec warn"><h4>需要你回答</h4>${list(s.questions)}<div class="hint">在下面的签字意见里一并回答。</div></div>` : ""}
    ${s.next ? `<div class="ap-sec"><h4>批准后</h4><div>${esc(s.next)}</div></div>` : ""}
    <div class="ap-sec">
      <label class="field"><span>签字意见（会作为你的原话保存）</span>
        <textarea id="quote">${esc(ap.name)}，可以进入下一步。</textarea></label>
      ${risky ? `<label class="ack"><input type="checkbox" id="ack" disabled> 我已展开并看过“未验证”和“新增费用”</label>` : ""}
      <div class="seal-row"><button class="btn btn-seal" data-action="approve" data-id="${esc(ap.id)}" ${risky ? "disabled" : ""}>盖章批准</button>
        <button class="btn" data-action="toggle" data-target="revise-form">要求修改</button>
        <button class="btn btn-quiet" data-action="toggle" data-target="ask-form">先问个问题</button></div>
      <div class="inline-form" id="revise-form" hidden>
        <label class="field"><span>希望 AI 改什么？</span><textarea id="revise-text"></textarea></label>
        <button class="btn" data-action="feedback" data-kind="revise" data-src="revise-text">交给 AI 修改</button></div>
      <div class="inline-form" id="ask-form" hidden>
        <label class="field"><span>你想问什么？AI 会在这里回答，不会改文件。</span><textarea id="ask-text"></textarea></label>
        <button class="btn" data-action="feedback" data-kind="question" data-src="ask-text">提问</button></div>
    </div></section>`;
}

function releaseGoCard(d) {
  const r = (d.inbox && d.inbox.release_request) || {};
  const f = (k, label, ph) => `<label class="field"><span>${label}</span><input type="text" id="rg-${k}" value="${esc(r[k] || "")}" placeholder="${esc(ph)}"></label>`;
  return `<section class="sheet task due approval" id="approval">
    <div class="seal-stamp" id="stamp" aria-hidden="true">授权</div>
    <div class="task-kicker">待你签字</div><h3>授权部署</h3>
    <p class="detail">${esc(d.release_go.ask)} AI 只会在你写下的范围内操作；超出范围会停下来问你。</p>
    <div class="grid-2">${f("platform", "平台与账号", "比如：火山引擎 veFaaS")}${f("environment", "环境", "比如：生产（邀请码访问）")}
      ${f("cost", "费用上限", "比如：每月不超过 150 元")}${f("visibility", "公开范围", "比如：公网，凭邀请码登录")}
      ${f("data_migration", "数据迁移", "比如：首次上线，无历史数据")}${f("rollback", "回滚方式", "比如：保留上一版本")}</div>
    <label class="field"><span>签字意见</span><textarea id="quote">同意按以上范围部署。</textarea></label>
    <div class="seal-row"><button class="btn btn-seal" data-action="approve" data-id="release_go">盖章授权</button>
      <button class="btn" data-action="toggle" data-target="revise-form">先不部署，提意见</button></div>
    <div class="inline-form" id="revise-form" hidden>
      <label class="field"><span>你的意见</span><textarea id="revise-text"></textarea></label>
      <button class="btn" data-action="feedback" data-kind="revise" data-src="revise-text">交给 AI</button></div>
  </section>`;
}

function afterTask(el) {
  const d = App.detail;
  if (d.next_action.kind === "manual_wait" && d.active_run) {
    get(`/api/products/${d.id}/runs/${d.active_run.id}`).then(({ run }) => {
      const box = $("#manual-box");
      if (!box) return;
      box.innerHTML = `<div class="prompt-box"><pre id="prompt-text">${esc(run.prompt || "")}</pre></div>
        <ol class="small muted" style="padding-left:20px;margin:0 0 14px">
          <li>点“复制指令”，粘贴到你的 AI 编程助手（比如 Claude Code、Cursor）里执行。</li>
          <li>AI 会把问题、清单或审批摘要写进产品文件夹的 factory/inbox/。</li>
          <li>它说做完了，回来点“AI 已完成”。</li></ol>
        <div class="btn-row"><button class="btn btn-primary" data-action="copy-prompt">复制指令</button>
          <button class="btn" data-action="manual-done">AI 已完成</button>
          <button class="btn btn-quiet" data-action="stop">取消</button></div>`;
    }).catch((e) => toast(e.message, true));
  }
  if (d.next_action.kind === "running") {
    App.feedSince = 0;
    App.feedRun = null;
    pollFeed(true);
  }
  el.querySelectorAll("details[data-must]").forEach((det) => det.addEventListener("toggle", () => {
    const all = [...el.querySelectorAll("details[data-must]")].every((x) => x.dataset.seen || x.open);
    if (det.open) det.dataset.seen = "1";
    const ack = $("#ack");
    if (ack && all) ack.disabled = false;
  }));
  const ack = $("#ack");
  if (ack) ack.addEventListener("change", () => { $('[data-action="approve"]').disabled = !ack.checked; });
}

// ---------- 实时进度

let feedTimer = null;
async function pollFeed(reset) {
  const d = App.detail;
  if (!d || !d.active_run) return;
  if (feedTimer && !reset) return;
  clearTimeout(feedTimer);
  const rid = d.active_run.id;
  if (App.feedRun !== rid) { App.feedRun = rid; App.feedSince = 0; }
  try {
    const { run } = await get(`/api/products/${d.id}/runs/${rid}?since=${App.feedSince}`);
    const feed = $("#feed");
    if (feed && run.activity) {
      for (const a of run.activity) {
        const li = document.createElement("li");
        li.dataset.kind = a.kind;
        li.innerHTML = `<time>${esc(timeShort(a.t))}</time><span>${esc(a.text)}</span>`;
        feed.appendChild(li);
      }
      if (run.activity.length) feed.scrollTop = feed.scrollHeight;
      App.feedSince = run.activity_total;
    }
    const el = $("#elapsed");
    if (el && run.started) el.textContent = "已进行 " + Math.max(1, Math.round((Date.now() - new Date(run.started)) / 1000)) + " 秒";
    if (run.status === "running" && App.pid === d.id) {
      feedTimer = setTimeout(() => { feedTimer = null; pollFeed(); }, 900);
    } else {
      feedTimer = null;
      if (run.status === "failed") toast("AI 运行失败：" + (run.error || ""), true);
      else if (run.notes && run.notes.length) toast(run.notes.join(" "));
      loadProduct(d.id, false);
    }
  } catch (e) {
    feedTimer = null;
  }
}

// ---------- 文档

function docsHTML(d) {
  const arts = d.stage.artifacts.filter((a) => /\.(md|jsonl)$/.test(a.path));
  const others = d.docs.filter((p) => !arts.some((a) => a.path === p));
  const short = (p) => p.replace(/^factory\//, "");
  if (App.docStage !== d.current_stage + d.product.version) {
    App.docStage = d.current_stage + d.product.version;
    App.docTab = null;
  }
  if (!App.docTab || (!arts.some((a) => a.path === App.docTab) && !others.includes(App.docTab))) {
    App.docTab = (arts.find((a) => a.exists) || arts[0] || {}).path || others[0] || null;
  }
  const opt = (p, label) => `<option value="${esc(p)}" ${p === App.docTab ? "selected" : ""}>${esc(label)}</option>`;
  const options = (arts.length ? `<optgroup label="本阶段">${arts.map((a) => opt(a.path, short(a.path) + (a.exists ? "" : "（未生成）"))).join("")}</optgroup>` : "") +
    (others.length ? `<optgroup label="其他阶段">${others.map((p) => opt(p, short(p))).join("")}</optgroup>` : "");
  return `<section class="sheet docs" aria-label="文档">
    <div class="doc-bar"><span class="doc-bar-label">文档</span>
      ${options ? `<select id="doc-pick" aria-label="选择要查看的文档">${options}</select>` : ""}
    </div><div class="doc-body" id="doc-body"><div class="doc-empty">还没有文档</div></div></section>`;
}

async function afterDocs() {
  const sel = $("#doc-pick");
  if (sel) sel.addEventListener("change", () => { App.docTab = sel.value; App.sigs.docs = null; paintProduct(); });
  const body = $("#doc-body");
  const d = App.detail;
  if (!App.docTab || !body) return;
  const want = App.docTab;
  const token = (App.docToken = (App.docToken || 0) + 1);
  const art = d.stage.artifacts.find((a) => a.path === want);
  if (art && !art.exists) {
    body.innerHTML = `<div class="doc-empty">AI 还没写这份文档。</div>`;
    return;
  }
  if (App.docCache && App.docCache.path === want) body.innerHTML = App.docCache.html;   // 先显示上次的内容，避免闪烁
  try {
    const { text } = await get(`/api/products/${d.id}/doc?path=${encodeURIComponent(want)}`);
    if (token !== App.docToken || App.docTab !== want) return;                           // 已经切到别的文档
    if (App.docTab.endsWith(".jsonl")) {
      const rows = text.trim().split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
      body.innerHTML = `<div class="md"><table><thead><tr><th>用例</th><th>验收标准</th><th>类型</th><th>预期</th><th>结果</th></tr></thead><tbody>` +
        rows.map((r) => `<tr><td>${esc(r.id || "")}</td><td>${esc((r.ac || []).join("、"))}</td><td>${esc(r.type || "")}</td><td>${esc(String(r.expected || ""))}</td><td>${esc(r.result || "")}</td></tr>`).join("") + "</tbody></table></div>";
    } else {
      body.innerHTML = `<article class="md">${renderMarkdown(text)}</article>`;
    }
    App.docCache = { path: want, html: body.innerHTML };
  } catch (e) {
    if (token !== App.docToken) return;
    body.innerHTML = `<div class="doc-empty">${esc(e.message)}</div>`;
  }
}

// ---------- 质检单

function sideHTML(d) {
  const L = d.level_names;
  const got = d.levels.indexOf(d.stage.level);
  const need = d.levels.indexOf(d.stage.min_evidence);
  const ladder = d.levels.map((lv, i) => `<li class="${i <= got ? "got" : ""} ${i === need ? "need" : ""}"><i></i><span>${esc(L[lv])}</span>
      <span class="tag">${i === need ? "本阶段需要" : ""}</span></li>`).join("");
  const probs = d.problems;
  const checks = probs.length
    ? probs.map((p) => `<li><span class="${p.startsWith("缺少用户审批") ? "s" : "x"}">${p.startsWith("缺少用户审批") ? "○" : "✗"}</span><span>${esc(p.split("：")[0])}</span></li>`).join("")
    : `<li><span class="y">✓</span><span>全部通过</span></li>`;
  const evShort = probs.some((p) => p.startsWith("证据等级不足"));
  const blockers = d.stage.blockers.map((b, i) => `<li><span class="x">!</span><span>${esc(b)}
      <button class="btn-quiet btn small" style="min-height:0;padding:0 6px" data-action="clear-blocker" data-i="${i}">已解决</button></span></li>`).join("");
  const signs = d.approvals.length ? d.approvals.map((a) => `<div class="sign"><span class="mini-seal" aria-hidden="true">印</span>
      <div><b>${esc((App.guides.approvals[a.id]) || a.id)}</b><div class="small muted">${esc(a.by)}，${esc(timeShort(a.at))}</div>
      <q class="small">${esc(a.quote)}</q>${a.scope ? `<div class="small muted">范围：${esc(a.scope)}</div>` : ""}</div></div>`).join("")
    : `<div class="empty-note">这一版还没有签字。</div>`;
  const runs = d.runs.length ? d.runs.map((r) => `<li><span>${esc(timeShort(r.started))} ${esc({ start: "开始", continue: "继续", fix: "修复", deploy: "部署" }[r.mode] || r.mode)}</span>
      <span class="${r.status === "failed" ? "err" : ""}">${esc({ succeeded: "完成", failed: "失败", stopped: "已停止", running: "进行中", waiting_manual: "等待手动" }[r.status] || r.status)}${r.cost_usd != null ? "，$" + r.cost_usd : r.tokens ? "，" + fmtTokens(r.tokens) : ""}</span></li>`).join("")
    : `<li class="empty-note">还没有运行过</li>`;
  const ev = d.stage.evidence.length ? d.stage.evidence.map((e) => `<div class="ev"><span class="pill ${e.result === "pass" ? "pill-ok" : e.result === "fail" ? "pill-bad" : ""}">${esc(L[e.level] || e.level)}</span>
      ${esc(e.what)}${e.resolved ? '<span class="small muted">（已处理）</span>' : ""}<div class="small muted">${esc(e.how)}</div></div>`).join("")
    : `<div class="empty-note">还没有记录。</div>`;
  const waivers = d.waivers.map((w) => `<div class="small"><span class="pill pill-due">已豁免</span> ${esc(w.reason)}</div>`).join("");
  return `<h3>质检单</h3>
    <section><h4>成熟度</h4><ul class="ladder">${ladder}</ul></section>
    <section><h4>进入下一阶段前</h4><ul class="checks">${checks}</ul>
      ${evShort ? `<button class="btn btn-quiet small" data-action="toggle" data-target="waive-form">条件暂时不具备？</button>
        <div class="inline-form" id="waive-form" hidden><p class="small">豁免后可以先往下走，但报告里会一直标注“已豁免”。</p>
        <label class="field"><span>原因</span><input type="text" id="waive-reason" placeholder="比如：还没申请到模型 Key"></label>
        <label class="field"><span>你的确认</span><input type="text" id="waive-quote" value="接受先用假数据测试结果推进"></label>
        <button class="btn" data-action="waive">确认豁免</button></div>` : ""}${waivers}</section>
    <section><h4>${term("阻塞")}</h4>${blockers ? `<ul class="checks">${blockers}</ul>` : `<div class="empty-note">没有阻塞。</div>`}
      <button class="btn btn-quiet small" data-action="toggle" data-target="blocker-form">记一个阻塞</button>
      <div class="inline-form" id="blocker-form" hidden><input type="text" id="blocker-text" placeholder="必须先解决的问题">
        <div style="margin-top:8px"><button class="btn" data-action="add-blocker">记下</button></div></div></section>
    <section><h4>签字记录</h4>${signs}</section>
    <section><h4>${term("证据")}</h4>${ev}</section>
    <section><h4>运行记录</h4><ul class="runs">${runs}</ul>
      <div class="small muted" style="margin-top:6px">累计模型费用约 $${d.cost_total_usd}（估算）</div></section>
    <section><button class="btn btn-quiet small btn-danger" data-action="forget">从列表移除（不删文件）</button></section>`;
}

// ------------------------------------------------------------------ 设置

function statusPill(info) {
  if (!info) return `<span class="pill">检测中…</span>`;
  if (!info.found) return `<span class="pill pill-bad">未安装</span>`;
  if (info.logged_in) return `<span class="pill pill-ok">已登录${info.version ? "，" + esc(info.version.replace(/\s*\(.*\)/, "")) : ""}</span>`;
  return `<span class="pill pill-due">已安装，未登录</span>`;
}

async function renderSettings() {
  const { config: c } = await get("/api/config");
  App.config = c;
  main().innerHTML = `<div class="settings"><h1>设置</h1><form id="settings-form" autocomplete="off">
    <section class="sheet"><h2>你的名字</h2><p class="small muted">签字时记录为签字人。</p>
      <input type="text" name="user_name" value="${esc(c.user_name || "")}" placeholder="产品负责人"></section>
    <section class="sheet" id="exec-section"><h2>AI 执行方式</h2>
      <p class="small muted">控制台负责流程、闸门和审批，具体的活交给你电脑上的 AI 命令行工具来干。</p>
      <div id="exec-cards"><div class="muted small">正在检测电脑上的 AI 工具…</div></div>
    </section>
    <section class="sheet"><h2>安全与预算</h2>
      <div class="grid-2">
        <label class="field"><span>单次运行预算上限（美元，仅 Claude 账号）</span><input type="number" step="0.5" min="0.5" name="budget_per_run_usd" value="${esc(String(c.budget_per_run_usd))}"></label>
        <label class="field"><span>单次运行最长时间（分钟）</span><input type="number" min="5" name="max_minutes_per_run" value="${esc(String(c.max_minutes_per_run))}"></label>
      </div>
      <label class="ack"><input type="checkbox" name="allow_shell_in_build" ${c.allow_shell_in_build ? "checked" : ""}>
        <span>开发、前端、评测阶段允许 AI 在产品文件夹里运行命令（装依赖、跑测试）。对 Claude Code 和 pi 生效；Codex 始终在沙箱里运行命令。</span></label>
      <p class="hint">无论怎么设置：AI 不能修改工厂状态、不能替你签字；部署只能在你授权后进行。</p>
    </section>
    <section class="sheet"><h2>产品存放位置</h2><input type="text" name="workspace" value="${esc(c.workspace || "")}"></section>
    <div class="btn-row"><button class="btn btn-primary" type="submit">保存设置</button>
      <button class="btn" type="button" data-action="test-exec">保存并测试连接</button>
      <span id="test-result" class="small" role="status"></span></div>
  </form></div>`;
  App.execInfo = null;
  paintExecCards();
  try { App.execInfo = await get("/api/executors"); } catch (e) { toast(e.message, true); }
  paintExecCards();
}

// 模型下拉：已知选项 + “默认” + “其他（手动填写）”。真正提交的是同名文本框。
function modelPicker(name, value, groups, defaultLabel) {
  const flat = groups.flatMap((g) => g.items);
  const known = !value || flat.some((o) => o.value === value);
  const opt = (o) => `<option value="${esc(o.value)}" ${o.value === value ? "selected" : ""}>${esc(o.label || o.value)}</option>`;
  const body = groups.map((g) => g.group ? `<optgroup label="${esc(g.group)}">${g.items.map(opt).join("")}</optgroup>` : g.items.map(opt).join("")).join("");
  return `<div class="model-picker">
    <select data-action-change="modelsel" data-target="${name}" aria-label="选择模型">
      ${defaultLabel !== null ? `<option value="" ${!value ? "selected" : ""}>${esc(defaultLabel)}</option>` : ""}
      ${body}
      <option value="__custom__" ${known ? "" : "selected"}>其他（手动填写）</option>
    </select>
    <input type="text" name="${name}" value="${esc(value || "")}" placeholder="填写模型名" ${known ? "hidden" : ""}>
  </div>`;
}

function cliList(info) {
  if (!info) return "";
  const clis = info.clis || [];
  if (!clis.length) return `<p class="small muted">没有在这台电脑上找到 AI 命令行工具。</p>`;
  return `<div class="cli-scan"><span class="small muted">本机检测到：</span>${clis.map((c) => `<span class="cli-chip ${c.supported ? "ok" : ""}" title="${esc(c.path)}">
      <b>${esc(c.name)}</b>${c.version ? ` <span class="muted">${esc(c.version.replace(/^[^0-9]*/, "").split(" ")[0])}</span>` : ""}
      <span class="tag">${c.supported ? "可全自动" : "可复制指令"}</span></span>`).join("")}</div>`;
}

function paintExecCards() {
  const c = App.config;
  const info = App.execInfo;
  const det = info ? info.detected : {};
  const providers = info ? info.providers : [];
  const pkeys = info ? info.provider_keys : {};
  const pv = providers.find((p) => p.id === c.provider_id) || providers[0] || { models: [] };
  const card = (v, title, desc, extra, pill) => `<div class="exec-opt-wrap"><label class="exec-opt">
      <input type="radio" name="executor" value="${v}" ${c.executor === v ? "checked" : ""} data-action-change="exec">
      <span><span class="exec-title"><b>${title}</b>${pill || ""}</span><span class="small muted">${desc}</span></span></label>
      <div class="exec-detail" data-for="${v}" ${c.executor === v ? "" : "hidden"}>${extra || ""}</div></div>`;
  const keyRow = (kind, masked, idAttr) => `<div class="key-row">
      <input type="password" id="key-${kind}" placeholder="${masked ? esc(masked) + "，粘贴新 Key 可替换" : "粘贴 API Key"}" autocomplete="new-password" ${idAttr || ""}>
      <button type="button" class="btn" data-action="save-key" data-kind="${kind}">保存 Key</button>
      ${masked ? `<button type="button" class="btn btn-quiet btn-danger" data-action="delete-key" data-kind="${kind}">删除</button>` : ""}</div>
      <div class="hint">Key 保存在${esc(info ? info.secret_store : "本机")}，不会写进项目文件，也不会显示在页面上。</div>`;
  const claudeExtra = `
    <div class="sub-choice">
      <label class="choice"><input type="radio" name="claude_source" value="account" ${c.claude_source !== "provider" ? "checked" : ""} data-action-change="source">
        <span><b>Claude 账号</b><br><span class="small muted">用你在终端登录的 Claude 订阅或 Console 账号。${det.claude && det.claude.found && !det.claude.logged_in ? "现在还没登录：在终端运行 claude 按提示登录。" : ""}</span></span></label>
      <label class="choice"><input type="radio" name="claude_source" value="provider" ${c.claude_source === "provider" ? "checked" : ""} data-action-change="source">
        <span><b>国内或第三方模型 API</b><br><span class="small muted">DeepSeek、Kimi、智谱 GLM、MiniMax 等提供 Claude 兼容接口的厂商，填它们的 API Key 即可，不需要 Claude 账号。</span></span></label>
    </div>
    <div data-source="account" ${c.claude_source === "provider" ? "hidden" : ""}>
      <div class="field"><span class="field-label">模型</span>
        ${modelPicker("model", c.model, [{ items: (info && info.claude_models) || [] }],
          det.claude && det.claude.default_model ? `默认（Claude Code 设置里的 ${det.claude.default_model}）` : "默认（跟随 Claude Code 的设置）")}
        <div class="hint">opus、sonnet、haiku 这类别名始终指向最新版本；固定版本不会自动升级。</div></div>
    </div>
    <div data-source="provider" ${c.claude_source === "provider" ? "" : "hidden"}>
      <div class="grid-2">
        <label class="field"><span>厂商</span><select name="provider_id" data-action-change="provider">
          ${providers.map((p) => `<option value="${esc(p.id)}" ${p.id === c.provider_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
        <div class="field"><span class="field-label">模型</span>
          ${modelPicker("provider_model", c.provider_model, [{ items: (pv.models || []).map((m) => ({ value: m })) }], null)}</div>
      </div>
      <label class="field"><span>接口地址</span><input type="text" name="provider_base_url" value="${esc(c.provider_base_url || "")}" placeholder="https://…/anthropic"></label>
      <div class="field"><span class="field-label">API Key${pv.site ? `（在 <a href="${esc(pv.site)}" target="_blank" rel="noopener">${esc(pv.name)} 开放平台</a>创建）` : ""}</span>
        ${keyRow("provider", pkeys[c.provider_id])}</div>
      <details class="small"><summary class="muted" style="cursor:pointer">高级</summary>
        <label class="field" style="margin-top:8px"><span>轻量任务用的模型（留空和上面相同）</span><input type="text" name="provider_small_model" value="${esc(c.provider_small_model || "")}"></label></details>
      <p class="hint">接口地址和型号来自资料整理，以厂商文档为准。第三方模型的费用以厂商账单为准，控制台只显示 token 用量。</p>
    </div>
    <details class="small"><summary class="muted" style="cursor:pointer">命令路径</summary>
      <label class="field" style="margin-top:8px"><span>Claude Code 命令</span><input type="text" name="claude_path" value="${esc(c.claude_path || "claude")}"></label></details>`;
  const codexExtra = `
    <div class="sub-choice">
      <label class="choice"><input type="radio" name="codex_source" value="account" ${c.codex_source !== "api_key" ? "checked" : ""} data-action-change="csource">
        <span><b>ChatGPT 账号</b><br><span class="small muted">用你在终端登录的 ChatGPT 账号。${det.codex && det.codex.found && !det.codex.logged_in ? "现在还没登录：在终端运行 codex 按提示登录。" : ""}</span></span></label>
      <label class="choice"><input type="radio" name="codex_source" value="api_key" ${c.codex_source === "api_key" ? "checked" : ""} data-action-change="csource">
        <span><b>OpenAI API Key</b><br><span class="small muted">按调用量付费，不需要 ChatGPT 账号。</span></span></label>
    </div>
    <div data-csource="api_key" ${c.codex_source === "api_key" ? "" : "hidden"}><div class="field">${keyRow("openai", info && info.openai_key)}</div></div>
    <div class="field"><span class="field-label">模型</span>
      ${modelPicker("codex_model", c.codex_model, [{ items: (det.codex && det.codex.models) || [] }],
        det.codex && det.codex.default_model ? `默认（Codex 设置里的 ${det.codex.default_model}）` : "默认（跟随 Codex 的设置）")}
      <div class="hint">${det.codex && det.codex.models_message ? esc(det.codex.models_message) : ""}${det.codex && det.codex.models_source === "cache" && det.codex.models_fetched_at ? `（缓存时间：${esc(timeShort(det.codex.models_fetched_at))}）` : ""}
        模型目录不保证当前账号或 API Key 的调用权限；不确定时选“默认”，列表里没有的选“其他”手动填写。</div></div>
    <p class="hint">Codex 在沙箱里工作：只能改产品文件夹；开发、评测、上线阶段才允许联网。它不能按文件细分权限，所以需求和架构阶段也能改到代码文件，控制台会在每次运行后检查状态文件。</p>
    <details class="small"><summary class="muted" style="cursor:pointer">命令路径</summary>
      <label class="field" style="margin-top:8px"><span>Codex 命令</span><input type="text" name="codex_path" value="${esc(c.codex_path || "codex")}"></label></details>`;
  const piModels = (det.pi && det.pi.models) || [];
  const piGroups = [];
  piModels.forEach((m) => {
    let g = piGroups.find((x) => x.group === m.provider);
    if (!g) piGroups.push(g = { group: m.provider, items: [] });
    g.items.push({ value: m.value, label: m.id });
  });
  const piExtra = `
    ${det.pi && det.pi.found && !piModels.length ? `<p class="small err">${esc(det.pi.message)}</p>` : ""}
    <div class="grid-2">
      <div class="field"><span class="field-label">模型${piModels.length ? `（${piModels.length} 个可用）` : ""}</span>
        ${modelPicker("pi_model", c.pi_model, piGroups, det.pi && det.pi.default_model ? `默认（pi 设置里的 ${det.pi.default_model}）` : "默认（跟随 pi 的设置）")}</div>
      <label class="field"><span>思考强度</span><select name="pi_thinking">
        <option value="" ${!c.pi_thinking ? "selected" : ""}>默认</option>
        ${((info && info.pi_thinking) || []).map((t) => `<option value="${t}" ${c.pi_thinking === t ? "selected" : ""}>${t}</option>`).join("")}</select></label>
    </div>
    <p class="hint">列表来自 pi 里已登录的订阅和已配置的 API Key，在 pi 里登录新厂商后点“重新检测”即可刷新。pi 没有沙箱，控制台用工具白名单限制它：需求、架构、选型阶段不能运行命令；每次运行后照常检查状态文件。pi 没有单次预算上限，只有时长上限。</p>
    <details class="small"><summary class="muted" style="cursor:pointer">命令路径</summary>
      <label class="field" style="margin-top:8px"><span>pi 命令</span><input type="text" name="pi_path" value="${esc(c.pi_path || "pi")}"></label></details>`;
  const manualOpen = c.executor === "manual";
  $("#exec-cards").innerHTML = cliList(info) +
    card("claude", "Claude Code", "全自动。可以用 Claude 账号，也可以用国内模型的 API Key。", claudeExtra, info ? statusPill(det.claude) : statusPill(null)) +
    card("codex", "Codex", "全自动。用 ChatGPT 账号或 OpenAI API Key。", codexExtra, info ? statusPill(det.codex) : statusPill(null)) +
    card("pi", "pi", "全自动。用 pi 里已登录的订阅或已配置的 Key，可以选任意厂商的模型。", piExtra, info ? statusPill(det.pi) : statusPill(null)) +
    card("demo", "演示模式", "不调用 AI，用示例内容走完整流程，适合先熟悉界面。") +
    `<details class="exec-advanced" ${manualOpen ? "open" : ""}><summary>其他 AI 工具（不推荐）</summary>
      <p class="small muted">电脑上没有 Claude Code、Codex 或 pi，只有别的 AI 编程助手（比如上面标着“可复制指令”的）时用：控制台照常管理流程、问题、验收和审批，只是每一步需要你把指令复制给那个助手执行。</p>
      ${card("manual", "复制指令给其他 AI 助手", "每一步手动复制粘贴，适合临时使用。")}</details>
    <div class="btn-row" style="margin-top:8px"><button type="button" class="btn btn-quiet small" data-action="redetect">重新检测</button>
      ${info && info.ready_problem ? `<span class="small err">${esc(info.ready_problem)}</span>` : ""}</div>`;
}

function readSettingsForm() {
  const f = $("#settings-form");
  const v = (n) => (f.elements[n] ? f.elements[n].value : undefined);
  const r = (n) => { const x = f.querySelector(`input[name="${n}"]:checked`); return x ? x.value : undefined; };
  const body = {
    user_name: v("user_name"), executor: r("executor"), budget_per_run_usd: v("budget_per_run_usd"),
    max_minutes_per_run: v("max_minutes_per_run"), allow_shell_in_build: f.elements.allow_shell_in_build.checked,
    workspace: v("workspace"), claude_source: r("claude_source"), model: v("model"), provider_id: v("provider_id"),
    provider_model: v("provider_model"), provider_base_url: v("provider_base_url"),
    provider_small_model: v("provider_small_model"), claude_path: v("claude_path"),
    codex_source: r("codex_source"), codex_model: v("codex_model"), codex_path: v("codex_path"),
    pi_model: v("pi_model"), pi_thinking: v("pi_thinking"), pi_path: v("pi_path"),
  };
  Object.keys(body).forEach((k) => body[k] === undefined && delete body[k]);
  return body;
}

async function saveSettings(quiet) {
  const { config } = await post("/api/config", readSettingsForm());
  App.config = config;
  renderTopbar();
  if (!quiet) toast("设置已保存");
  return config;
}

document.addEventListener("change", (e) => {
  const kind = e.target.dataset && e.target.dataset.actionChange;
  if (!kind) return;
  const f = $("#settings-form");
  if (kind === "exec") {
    f.querySelectorAll(".exec-detail").forEach((d) => { d.hidden = d.dataset.for !== e.target.value; });
  } else if (kind === "source") {
    f.querySelectorAll("[data-source]").forEach((d) => { d.hidden = d.dataset.source !== e.target.value; });
  } else if (kind === "csource") {
    f.querySelectorAll("[data-csource]").forEach((d) => { d.hidden = d.dataset.csource !== e.target.value; });
  } else if (kind === "modelsel") {
    const input = f.elements[e.target.dataset.target];
    if (!input) return;
    if (e.target.value === "__custom__") { input.hidden = false; input.value = ""; input.focus(); }
    else { input.hidden = true; input.value = e.target.value; }
  } else if (kind === "provider") {
    const p = (App.execInfo.providers || []).find((x) => x.id === e.target.value);
    if (!p) return;
    App.config = Object.assign({}, App.config, readSettingsForm(), {
      provider_id: p.id, provider_base_url: p.base_url, provider_model: p.models[0] || "",
    });
    paintExecCards();
  }
});

// ------------------------------------------------------------------ 路由

async function router() {
  clearTimers();
  App.pid = null;
  if (!App.config) {
    const c = await get("/api/config");
    App.config = c.config;
    App.guides = c.guides;
  }
  renderTopbar();
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  try {
    if (parts[0] === "p" && parts[1]) {
      App.pid = parts[1];
      main().innerHTML = `<div class="loading">正在打开…</div>`;
      App.sigs = {};
      await loadProduct(parts[1], true);
    } else if (parts[0] === "settings") {
      await renderSettings();
    } else {
      await renderHome();
    }
  } catch (e) {
    main().innerHTML = `<div class="loading err">${esc(e.message)}<br><a href="#/">回到产品列表</a></div>`;
  }
  main().focus({ preventScroll: true });
}

// ------------------------------------------------------------------ 事件

function val(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

async function act(fn, okMsg) {
  try {
    await fn();
    if (okMsg) toast(okMsg);
    resetEditing();
    if (App.pid) { App.sigs = {}; clearTimers(); await loadProduct(App.pid, false); }
  } catch (e) {
    toast(e.message, true);
  }
}

const actions = {
  example(el) {
    const [n, t] = EXAMPLES[+el.dataset.i];
    const f = $("#new-form");
    f.name.value = n;
    f.idea.value = t;
    f.idea.focus();
  },
  "show-new"() { const w = $("#new-wrap"); w.hidden = false; $("#new-form [name=name]").focus(); },
  "toggle-import"() { const f = $("#import-form"); f.hidden = !f.hidden; },
  async demo() {
    try { const { id } = await post("/api/products/demo"); location.hash = "#/p/" + id; } catch (e) { toast(e.message, true); }
  },
  toggle(el) {
    const t = document.getElementById(el.dataset.target);
    if (!t) return;
    t.hidden = !t.hidden;
    const f = t.querySelector("textarea, input");
    if (!t.hidden && f) f.focus();
  },
  run(el) { act(() => post(`/api/products/${App.pid}/run`, { mode: el.dataset.mode }), "AI 开始工作了"); },
  stop() { act(() => post(`/api/products/${App.pid}/run/stop`), "已停止"); },
  "manual-done"() { act(() => post(`/api/products/${App.pid}/run/manual-done`), "已读取 AI 的结果"); },
  async "copy-prompt"() {
    try { await navigator.clipboard.writeText($("#prompt-text").textContent); toast("已复制"); }
    catch { const r = document.createRange(); r.selectNodeContents($("#prompt-text")); getSelection().removeAllRanges(); getSelection().addRange(r); toast("按 ⌘C 复制已选中的指令"); }
  },
  feedback(el) {
    const text = el.dataset.src ? val(el.dataset.src) : val("fb-text");
    act(() => post(`/api/products/${App.pid}/feedback`, { kind: el.dataset.kind, text }),
      el.dataset.kind === "question" ? "问题已交给 AI" : "已交给 AI");
  },
  async approve(el) {
    const id = el.dataset.id;
    const body = { id, quote: val("quote"), acknowledged: !!($("#ack") && $("#ack").checked) };
    if (id === "release_go") {
      body.scope = {};
      ["platform", "environment", "cost", "visibility", "data_migration", "rollback"].forEach((k) => body.scope[k] = val("rg-" + k));
    }
    const stamp = $("#stamp");
    el.disabled = true;
    if (stamp) stamp.classList.add("go");
    try {
      await post(`/api/products/${App.pid}/approve`, body);
      await new Promise((r) => setTimeout(r, 650));
      toast("已盖章");
      resetEditing();
      App.sigs = {};
      clearTimers();
      await loadProduct(App.pid, false);
    } catch (e) {
      if (stamp) stamp.classList.remove("go");
      el.disabled = false;
      toast(e.message, true);
    }
  },
  advance() {
    const autostart = !!($("#autostart") && $("#autostart").checked);
    act(() => post(`/api/products/${App.pid}/advance`, { autostart }), "进入下一阶段");
  },
  skip() { act(() => post(`/api/products/${App.pid}/skip`, { reason: val("skip-reason") }), "已跳过"); },
  waive() { act(() => post(`/api/products/${App.pid}/waive`, { reason: val("waive-reason"), quote: val("waive-quote") }), "已记录豁免"); },
  iterate() { act(() => post(`/api/products/${App.pid}/iterate`, { reason: val("iterate-reason") }), "新版本开始了"); },
  "add-blocker"() { act(() => post(`/api/products/${App.pid}/blocker`, { add: val("blocker-text") }), "已记下"); },
  "clear-blocker"(el) { act(() => post(`/api/products/${App.pid}/blocker`, { clear: +el.dataset.i, resolution: "用户在控制台标记为已解决" }), "已解决"); },
  async forget() {
    if (!confirmInline()) return;
    act(async () => { await post(`/api/products/${App.pid}/forget`); location.hash = "#/"; }, "已从列表移除，文件仍在原处");
  },
  doc(el) { App.docTab = el.dataset.path; App.sigs.docs = null; paintProduct(); },
  "check-pass"() { checkStep("pass"); },
  "check-fail"() {
    const note = val("fail-note");
    if (!note) { toast("写一句你看到了什么，AI 才能修。", true); return; }
    checkStep("fail", note);
  },
  "check-back"() {
    const st = App.check[checkKey(App.detail)];
    st.idx = Math.max(0, st.idx - 1);
    rerenderTask();
  },
  recheck() {
    const d = App.detail;
    App.check[checkKey(d)] = { idx: 0, results: {} };
    act(() => post(`/api/products/${App.pid}/checklist`, { results: {} }));
  },
  "submit-check"() {
    const st = App.check[checkKey(App.detail)];
    act(() => post(`/api/products/${App.pid}/checklist`, { results: st.results }), "验收结果已保存");
  },
  async redetect() {
    App.config = Object.assign({}, App.config, readSettingsForm());
    App.execInfo = null;
    paintExecCards();
    try { await saveSettings(true); App.execInfo = await get("/api/executors"); } catch (e) { toast(e.message, true); }
    paintExecCards();
  },
  async "save-key"(el) {
    const kind = el.dataset.kind;
    const input = $("#key-" + kind);
    const value = input ? input.value.trim() : "";
    if (!value) { toast("先粘贴 Key 再保存", true); return; }
    try {
      const f = $("#settings-form");
      await post("/api/secrets", { kind, value, provider_id: f.elements.provider_id ? f.elements.provider_id.value : "" });
      input.value = "";
      await saveSettings(true);
      App.execInfo = await get("/api/executors");
      paintExecCards();
      toast("Key 已保存");
    } catch (e) { toast(e.message, true); }
  },
  async "delete-key"(el) {
    try {
      const f = $("#settings-form");
      await post("/api/secrets/delete", { kind: el.dataset.kind, provider_id: f.elements.provider_id ? f.elements.provider_id.value : "" });
      App.execInfo = await get("/api/executors");
      paintExecCards();
      toast("Key 已删除");
    } catch (e) { toast(e.message, true); }
  },
  async "test-exec"() {
    const out = $("#test-result");
    out.className = "small";
    out.textContent = "正在调用模型测试（约 10–60 秒，会产生极少量费用）…";
    try {
      await saveSettings(true);
      const r = await post("/api/executor/test");
      out.className = "small " + (r.ok ? "" : "err");
      out.textContent = r.message;
    } catch (e) { out.className = "small err"; out.textContent = e.message; }
  },
};

let forgetArmed = 0;
function confirmInline() {
  if (Date.now() - forgetArmed < 4000) return true;
  forgetArmed = Date.now();
  toast("再点一次确认从列表移除（文件不会被删除）");
  return false;
}

function checkStep(result, note = "") {
  const d = App.detail;
  const st = App.check[checkKey(d)];
  const c = d.inbox.checklist[st.idx];
  st.results[c.id] = { result, note };
  st.idx += 1;
  rerenderTask();
}
function rerenderTask() {
  App.sigs.task = null;
  const el = $("#p-task");
  el.innerHTML = taskHTML(App.detail);
  afterTask(el);
  App.sigs.task = "local";
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]");
  if (!el || el.tagName === "FORM") return;
  const fn = actions[el.dataset.action];
  if (fn) { e.preventDefault(); fn(el); }
});

document.addEventListener("input", (e) => {
  const root = e.target.closest("#p-task, #p-side");
  if (root && e.target.closest("form, .inline-form, .approval")) e.target.closest("section, form, .inline-form").setAttribute("data-dirty", "1");
});

document.addEventListener("submit", async (e) => {
  const f = e.target;
  e.preventDefault();
  if (f.id === "new-form") {
    const btn = f.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      const { id } = await post("/api/products", { name: f.name.value, idea: f.idea.value, notes: f.notes.value });
      location.hash = "#/p/" + id;
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  } else if (f.id === "import-form") {
    try { const { id } = await post("/api/products/import", { path: f.path.value }); location.hash = "#/p/" + id; }
    catch (err) { toast(err.message, true); }
  } else if (f.id === "answer-form") {
    const answers = {};
    for (const q of App.detail.inbox.questions) {
      if (q.type === "multi") answers[q.id] = [...f.querySelectorAll(`input[name="${CSS.escape(q.id)}"]:checked`)].map((x) => x.value);
      else if (q.type === "choice") {
        const c = f.querySelector(`input[name="${CSS.escape(q.id)}"]:checked`);
        answers[q.id] = c ? (c.value === "__other" ? (f.querySelector(`[data-other="${CSS.escape(q.id)}"]`).value || "") : c.value) : "";
      } else answers[q.id] = f.querySelector(`[name="${CSS.escape(q.id)}"]`).value;
    }
    act(() => post(`/api/products/${App.pid}/answers`, { answers }), "回答已交给 AI");
  } else if (f.id === "actions-form") {
    const acts = App.detail.inbox.user_actions;
    const done = [...f.querySelectorAll("input[name=done]:checked")].map((x) => x.value);
    const envActs = acts.filter((a) => a.fields && a.fields.length);
    const plain = acts.filter((a) => !(a.fields && a.fields.length));
    const all = plain.every((a) => done.includes(a.id));
    act(async () => {
      for (const a of envActs) {
        const values = {};
        a.fields.forEach((fl) => { const el = f.elements[`env:${a.id}:${fl.key}`]; if (el) values[fl.key] = el.value; });
        await post(`/api/products/${App.pid}/env`, { action: a.id, values });
        a.fields.forEach((fl) => { const el = f.elements[`env:${a.id}:${fl.key}`]; if (el && fl.secret) el.value = ""; });
      }
      await post(`/api/products/${App.pid}/actions`, { done });
      if (all) {
        const d = await get("/api/products/" + App.pid);
        if (d.next_action.kind === "continue") await post(`/api/products/${App.pid}/run`, { mode: "continue" });
      }
    }, all ? "已完成" : "已保存");
  } else if (f.id === "settings-form") {
    try { await saveSettings(false); App.execInfo = await get("/api/executors"); paintExecCards(); }
    catch (err) { toast(err.message, true); }
  }
});

// 术语提示
let tip = null;
function showTip(el) {
  hideTip();
  const text = App.guides && App.guides.glossary[el.dataset.term];
  if (!text) return;
  tip = document.createElement("div");
  tip.className = "term-tip";
  tip.setAttribute("role", "tooltip");
  tip.textContent = text;
  document.body.appendChild(tip);
  const r = el.getBoundingClientRect();
  const w = Math.min(280, window.innerWidth - 24);
  tip.style.maxWidth = w + "px";
  tip.style.left = Math.max(12, Math.min(r.left + window.scrollX, window.innerWidth - w - 12)) + "px";
  tip.style.top = r.bottom + window.scrollY + 6 + "px";
}
function hideTip() { if (tip) { tip.remove(); tip = null; } }
document.addEventListener("mouseover", (e) => { const t = e.target.closest(".term"); if (t) showTip(t); });
document.addEventListener("mouseout", (e) => { if (e.target.closest(".term")) hideTip(); });
document.addEventListener("focusin", (e) => { const t = e.target.closest(".term"); if (t) showTip(t); });
document.addEventListener("focusout", (e) => { if (e.target.closest(".term")) hideTip(); });

window.addEventListener("hashchange", router);
router();
