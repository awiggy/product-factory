// 轻量 Markdown 渲染：标题、段落、列表、表格、引用、代码、粗体/斜体、链接。所有文本先转义。
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function inline(s) {
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
  s = esc(s);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, "$1");
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => "<code>" + esc(codes[+i]) + "</code>");
  return s;
}

function splitRow(line) {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  return t.split("|").map((c) => c.trim());
}

export function renderMarkdown(src) {
  src = (src || "").replace(/<!--[\s\S]*?-->/g, "").replace(/\r\n/g, "\n");
  const lines = src.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*$/.test(line)) { i++; continue; }
    const fence = line.match(/^```(\w*)/);
    if (fence) {
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      out.push("<pre><code>" + esc(buf.join("\n")) + "</code></pre>");
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      out.push("<table><thead><tr>" + head.map((c) => "<th>" + inline(c) + "</th>").join("") + "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + head.map((_, k) => "<td>" + inline(r[k] || "") + "</td>").join("") + "</tr>").join("") +
        "</tbody></table>");
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push("<blockquote>" + buf.map(inline).join("<br>") + "</blockquote>");
      continue;
    }
    const li = line.match(/^(\s*)([-*]|\d+[.)])\s+(.*)$/);
    if (li) {
      const ordered = /\d/.test(li[2]);
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*]|\d+[.)])\s+(.*)$/);
        if (m) { items.push({ depth: m[1].length >= 2 ? 1 : 0, text: m[3] }); i++; continue; }
        if (/^\s{2,}\S/.test(lines[i]) && items.length) { items[items.length - 1].text += " " + lines[i].trim(); i++; continue; }
        break;
      }
      const tag = ordered ? "ol" : "ul";
      let html = "<" + tag + ">";
      let open = false;
      items.forEach((it, k) => {
        if (it.depth === 1 && !open) { html = html.replace(/<\/li>$/, ""); html += "<ul>"; open = true; }
        if (it.depth === 0 && open) { html += "</ul></li>"; open = false; }
        html += "<li>" + inline(it.text) + (it.depth === 0 && items[k + 1] && items[k + 1].depth === 1 ? "" : "</li>");
      });
      if (open) html += "</ul></li>";
      out.push(html + "</" + tag + ">");
      continue;
    }
    const buf = [line];
    i++;
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,4}\s|```|>|\s*[-*]\s|\s*\d+[.)]\s|\s*\|)/.test(lines[i])) buf.push(lines[i++]);
    out.push("<p>" + buf.map(inline).join("<br>") + "</p>");
  }
  return out.join("\n");
}

export { esc };
