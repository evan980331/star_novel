'use strict';
/* 星星小說 Agent 工作台前端：面板＋聊天＋安全 Markdown 檢視。 */
const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// 安全 Markdown：先 escape，再套用有限語法（不直接 innerHTML 未信任原文）。
function renderMarkdown(src) {
  const lines = escapeHtml(src).split('\n');
  let html = '', inList = false, inCode = false, para = [];
  const flushPara = () => {
    if (para.length) { html += '<p>' + para.join('<br>') + '</p>'; para = []; }
  };
  const inline = (t) => t
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|\W)\*(.+?)\*/g, '$1<em>$2</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
  for (const line of lines) {
    if (/^```/.test(line)) {
      flushPara();
      if (inCode) { html += '</code></pre>'; inCode = false; }
      else { html += '<pre><code>'; inCode = true; }
      continue;
    }
    if (inCode) { html += line + '\n'; continue; }
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      flushPara(); const lv = m[1].length;
      html += `<h${lv}>${inline(m[2])}</h${lv}>`; continue;
    }
    if (/^---+$/.test(line.trim())) { flushPara(); html += '<hr>'; continue; }
    if ((m = line.match(/^&gt;\s?(.*)$/))) { flushPara(); html += `<blockquote>${inline(m[1])}</blockquote>`; continue; }
    if ((m = line.match(/^[-*]\s+(.*)$/))) {
      flushPara();
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${inline(m[1])}</li>`; continue;
    }
    if (/^\s*$/.test(line)) { if (inList) { html += '</ul>'; inList = false; } flushPara(); continue; }
    para.push(inline(line));
  }
  if (inList) html += '</ul>';
  if (inCode) html += '</code></pre>';
  flushPara();
  return html;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function addMsg(who, markdown) {
  const log = $('chatLog');
  const div = document.createElement('div');
  div.className = 'msg ' + who;
  const whoEl = document.createElement('div');
  whoEl.className = 'who';
  whoEl.textContent = who === 'user' ? 'User' : 'Agent';
  const body = document.createElement('div');
  body.innerHTML = renderMarkdown(markdown);
  div.append(whoEl, body);
  log.append(div);
  log.scrollTop = log.scrollHeight;
}

async function refreshPanels() {
  try {
    const ch = await api('/api/chapters');
    const ul = $('chapterList');
    ul.textContent = '';
    for (const c of ch.chapters) {
      const li = document.createElement('li');
      li.textContent = `#${c.id} ${c.title || ''}${c.latest ? ' ✓最新' : ''}`;
      if (c.latest) li.classList.add('latest');
      ul.append(li);
    }
  } catch { /* offline */ }
  try {
    const d = await api('/api/drafts');
    const tree = $('draftTree');
    tree.textContent = '';
    if (!d.drafts.length) {
      const p = document.createElement('p');
      p.className = 'muted'; p.textContent = '尚無草稿，對話輸入「寫作開始」。';
      tree.append(p); return;
    }
    for (const ch of d.drafts) {
      const det = document.createElement('details');
      det.className = 'draft-ch'; det.open = true;
      const sum = document.createElement('summary');
      sum.textContent = ch.chapter;
      det.append(sum);
      for (const v of ch.versions) {
        const row = document.createElement('div');
        row.className = 'ver-row';
        const b = document.createElement('button');
        b.type = 'button'; b.textContent = v.version + (v.selected ? ' ●' : '');
        b.onclick = () => openViewer(ch.chapter, v.version);
        const val = document.createElement('span');
        val.className = 'pill ' + (v.validation ? 'pass' : '');
        val.textContent = v.validation ? 'V' : 'V-';
        const con = document.createElement('span');
        con.className = 'pill ' + (v.consistencyStatus === 'PASS' ? 'pass' : v.consistencyStatus === 'WARNING' ? 'warn' : v.consistencyStatus === 'ERROR' ? 'err' : '');
        con.textContent = 'C:' + (v.consistencyStatus || '-');
        row.append(b, val, con);
        det.append(row);
      }
      tree.append(det);
    }
  } catch { /* offline */ }
  try {
    const s = await api('/api/status');
    const badge = $('statusBadge');
    badge.textContent = s.stage ? `${s.state} · ${s.stage}` : s.state;
  } catch { /* offline */ }
}

let viewerCtx = null;
const viewerTabs = {};
async function openViewer(chapter, version) {
  const data = await api(`/api/drafts/${encodeURIComponent(chapter)}/${encodeURIComponent(version)}`);
  viewerCtx = { chapter, version };
  viewerTabs.content = data.content || '';
  viewerTabs.validation = data.validation || '(無 Validator 報告)';
  viewerTabs.consistency = data.consistencyMd || '(無 Consistency 報告)';
  $('viewerTitle').textContent = `${chapter} ${version}`;
  showViewerTab('content');
  $('viewerOverlay').hidden = false;
}
function showViewerTab(tab) {
  document.querySelectorAll('.viewer-tabs button').forEach((b) => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  $('viewerBody').innerHTML = renderMarkdown(viewerTabs[tab] || '');
}

async function sendChat(text) {
  addMsg('user', text);
  $('statusBadge').textContent = 'WORKING';
  try {
    const r = await api('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    addMsg('agent', r.message || '(無回覆)');
    if (r.draftsChanged) await refreshPanels();
  } catch {
    addMsg('agent', '連線失敗：請確認 server 運作中。');
  }
  await refreshPanels();
}

document.addEventListener('DOMContentLoaded', () => {
  const root = document.documentElement;
  try {
    const saved = localStorage.getItem('novel-theme');
    if (saved) root.dataset.theme = saved;
  } catch { /* ignore */ }
  $('themeBtn').onclick = () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('novel-theme', next); } catch { /* ignore */ }
  };
  document.querySelectorAll('.viewer-tabs button').forEach((b) => {
    b.onclick = () => showViewerTab(b.dataset.tab);
  });
  $('viewerClose').onclick = () => { $('viewerOverlay').hidden = true; };
  $('viewerOverlay').addEventListener('click', (e) => {
    if (e.target === $('viewerOverlay')) $('viewerOverlay').hidden = true;
  });
  $('viewerSelect').onclick = async () => {
    if (!viewerCtx) return;
    $('viewerOverlay').hidden = true;
    await sendChat(`我選 ${viewerCtx.chapter} 的 ${viewerCtx.version}`);
  };
  $('chatForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const v = $('chatInput').value.trim();
    if (!v) return;
    $('chatInput').value = '';
    sendChat(v);
  });
  addMsg('agent', '工作台就緒。輸入「寫作開始」啟動寫作流程；通訊僅走本機 API。');
  refreshPanels();
  setInterval(refreshPanels, 5000);
});
