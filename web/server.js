'use strict';
/* 星星小說 Agent 工作台 — localhost server (3F).
 * Node.js 標準函式庫，無外部依賴。
 * Frontend -> Local API -> 既有 Python 工具 (3A~3E)，不另建 LLM provider。
 * 啟動：node web/server.js (PORT=3000 可覆寫)
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const WEB_DIR = __dirname;
const PORT = parseInt(process.env.PORT || '3000', 10) || 3000;
const PY = process.env.PYTHON || 'python';
const EDITOR = path.join(REPO_ROOT, 'novel', 'editor');
const DRAFTS = path.join(REPO_ROOT, 'novel', 'drafts');
const CHAPTERS = path.join(REPO_ROOT, 'novel', 'chapters');
const ADOPTIONS = path.join(REPO_ROOT, 'novel', 'adoptions');

const STATES = ['IDLE', 'THINKING', 'CONTEXT_BUILD', 'WRITING', 'VALIDATING',
  'CONSISTENCY_CHECK', 'WAITING_AUTHOR', 'CANON_SYNC', 'ERROR'];
const agent = { state: 'IDLE', stage: null, detail: '', updatedAt: Date.now() };
function setStatus(state, stage, detail) {
  agent.state = state;
  agent.stage = stage || null;
  agent.detail = detail || '';
  agent.updatedAt = Date.now();
}

// session memory (per server process)
const session = { lastChapter: null, lastRequest: null, pendingSync: null };

// ---------------------------------------------------------------- helpers
function runPy(script, args, timeoutMs) {
  const r = spawnSync(PY, [script, ...args], {
    cwd: REPO_ROOT, timeout: timeoutMs || 300000, encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  return {
    code: r.status === null ? 124 : r.status,
    stdout: r.stdout || '', stderr: r.stderr || '',
    timeout: r.status === null,
  };
}

function cleanSeg(s) {
  return (typeof s === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(s)) ? s : null;
}
function isBlockedPath(p) {
  return /(\.\.|\\.env($|\.)|secrets|(^|\/)\.)/i.test(p || '');
}
function draftPath(chapter, version) {
  const c = cleanSeg(chapter), v = cleanSeg(version);
  if (!c || !v) return null;
  const p = path.resolve(DRAFTS, c, v + '.md');
  if (!p.startsWith(DRAFTS + path.sep)) return null;
  return p;
}
function readJsonSafe(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}
function sendJson(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(body);
}
function sendText(res, code, text, type) {
  res.writeHead(code, { 'Content-Type': (type || 'text/plain') + '; charset=utf-8' });
  res.end(text);
}
function gitHead() {
  try {
    const r = spawnSync('git', ['rev-parse', '--short', 'HEAD'],
      { cwd: REPO_ROOT, timeout: 15000, encoding: 'utf8' });
    return (r.stdout || '').trim() || 'unknown';
  } catch { return 'unknown'; }
}

// ---------------------------------------------------------------- data APIs
function listChapters() {
  let files = [];
  try {
    files = fs.readdirSync(CHAPTERS).filter(f => /^\d{3}\.md$/.test(f)).sort();
  } catch { return []; }
  return files.map((f, i) => {
    let title = '';
    try {
      title = (fs.readFileSync(path.join(CHAPTERS, f), 'utf8').split('\n')[0] || '').slice(0, 80);
    } catch { /* ignore */ }
    return { id: f.slice(0, 3), title, latest: i === files.length - 1 };
  });
}

function readSelection(chapterDir) {
  const sel = readJsonSafe(path.join(chapterDir, 'selection.json'));
  return sel && Array.isArray(sel.selected) ? sel : { selected: [] };
}

function listDrafts() {
  const out = [];
  let entries = [];
  try { entries = fs.readdirSync(DRAFTS, { withFileTypes: true }); } catch { return out; }
  for (const e of entries) {
    if (!e.isDirectory() || !cleanSeg(e.name)) continue;
    const dir = path.join(DRAFTS, e.name);
    const sel = readSelection(dir);
    const versions = fs.readdirSync(dir)
      .filter(f => /^v\d+\.md$/.test(f))
      .map(f => f.slice(0, -3))
      .sort((a, b) => parseInt(a.slice(1), 10) - parseInt(b.slice(1), 10))
      .map(v => {
        const csum = readJsonSafe(path.join(dir, v + '-consistency.json'));
        return {
          version: v,
          validation: fs.existsSync(path.join(dir, v + '-validation.md')),
          consistency: fs.existsSync(path.join(dir, v + '-consistency.md')),
          consistencyStatus: csum && csum.summary ? (
            csum.summary.errors > 0 ? 'ERROR'
              : csum.summary.warnings > 0 ? 'WARNING' : 'PASS') : null,
          selected: sel.selected.includes(v),
        };
      });
    if (versions.length) out.push({ chapter: e.name, versions, selected: sel.selected });
  }
  return out.sort((a, b) => a.chapter.localeCompare(b.chapter));
}

// ---------------------------------------------------------------- chat intents
const WRITE_RES = /(寫作開始|開始寫小說|開始新章|開始創作|我要寫第\d+章|^\s*開始寫)/;
const FINAL_RES = /(正式章節已確認|這章確定了|正式版已上傳|已確定.*(存檔|更新設定|同步))/;
const CHAPTER_RES = /(?:第\s*0*(\d{1,3})\s*章|chapter-0*(\d{1,3})|#0*(\d{1,3}))/i;

function extractChapter(msg) {
  const m = msg.match(CHAPTER_RES);
  if (!m) return null;
  const n = parseInt(m[1] || m[2] || m[3], 10);
  if (Number.isNaN(n) || n < 0 || n > 999) return null;
  return String(n).padStart(3, '0');
}
function latestFormalId() {
  const ch = listChapters();
  return ch.length ? ch[ch.length - 1].id : '059';
}

const VARIANTS = [
  { key: 'plot', label: '劇情推進型', suffix: '（劇情推進）' },
  { key: 'battle', label: '戰鬥強化型', suffix: '（戰鬥強化）' },
  { key: 'character', label: '角色互動型', suffix: '（角色互動）' },
];

function nextVersions(chapterDir, count) {
  let max = 0;
  try {
    for (const f of fs.readdirSync(chapterDir)) {
      const m = f.match(/^v(\d+)\.md$/);
      if (m) max = Math.max(max, parseInt(m[1], 10));
    }
  } catch { /* new dir */ }
  return Array.from({ length: count }, (_, i) => 'v' + (max + i + 1));
}

function runSingleVersion(chapter, chapterDir, version, request) {
  const stages = [];
  const outRel = path.join('novel', 'drafts', chapter, version + '.md');
  stages.push('WRITING');
  setStatus('WRITING', 'WRITING', `${chapter} ${version}`);
  const w = runPy(path.join(EDITOR, 'writer.py'),
    ['--request', request, '--output', outRel, '--provider', 'mock']);
  if (w.code !== 0) {
    return { ok: false, version, stages, error: (w.stderr || w.stdout).slice(0, 500) };
  }
  stages.push('VALIDATING');
  setStatus('VALIDATING', 'VALIDATING', `${chapter} ${version}`);
  const v = runPy(path.join(EDITOR, 'draft-validator.py'), [outRel]);
  fs.writeFileSync(path.join(chapterDir, version + '-validation.md'), v.stdout || v.stderr || '', 'utf8');
  const vpass = v.code === 0;
  stages.push('CONSISTENCY_CHECK');
  setStatus('CONSISTENCY_CHECK', 'CONSISTENCY_CHECK', `${chapter} ${version}`);
  const cj = runPy(path.join(EDITOR, 'consistency_checker.py'),
    [outRel, '--json', '--output', path.join(chapterDir, version + '-consistency.json')]);
  runPy(path.join(EDITOR, 'consistency_checker.py'),
    [outRel, '--markdown', '--output', path.join(chapterDir, version + '-consistency.md')]);
  const csum = readJsonSafe(path.join(chapterDir, version + '-consistency.json'));
  const cstatus = csum && csum.summary
    ? (csum.summary.errors > 0 ? 'ERROR' : csum.summary.warnings > 0 ? 'WARNING' : 'PASS')
    : 'UNKNOWN';
  void cj;
  return { ok: true, version, stages, validator: vpass ? 'PASS' : 'FAIL', consistency: cstatus };
}

function runWritingFlow(chapter, baseRequest) {
  const stages = ['REQUIREMENT_COLLECTION', 'CONTEXT_BUILD'];
  setStatus('CONTEXT_BUILD', 'CONTEXT_BUILD', chapter);
  const chapterDir = path.join(DRAFTS, chapter);
  fs.mkdirSync(chapterDir, { recursive: true });
  const versions = nextVersions(chapterDir, VARIANTS.length);
  const results = VARIANTS.map((vnt, i) => {
    const r = runSingleVersion(chapter, chapterDir, versions[i], baseRequest + vnt.suffix);
    return { ...r, label: vnt.label };
  });
  const selPath = path.join(chapterDir, 'selection.json');
  const prev = readJsonSafe(selPath) || {};
  fs.writeFileSync(selPath, JSON.stringify({
    chapter, selected: prev.selected || [], baseRequest,
    versions: versions, updatedAt: new Date().toISOString(),
  }, null, 2), 'utf8');
  setStatus('WAITING_AUTHOR', 'DRAFT_PRESENTATION', chapter);
  const lines = [`第${parseInt(chapter.replace(/^chapter-/, ''), 10)}章已產生 ${results.length} 個版本。`, ''];
  for (const r of results) {
    lines.push(`${r.version}｜${r.label}`);
    lines.push(`Validator：${r.validator || 'ERROR'}`);
    lines.push(`Consistency：${r.consistency || 'ERROR'}`);
    lines.push(`主要差異：寫作側重（${r.label}指示）＋Context vary by focus`);
    lines.push('');
  }
  lines.push(`Draft：\nNovel/drafts/${chapter}/`.replace('Novel', 'novel'));
  return { results, stages: [...stages, 'DRAFT_GENERATION', 'VALIDATION', 'CONSISTENCY_CHECK', 'DRAFT_PRESENTATION'], reply: lines.join('\n') };
}

function handleChat(message) {
  const msg = String(message || '').slice(0, 2000);
  const stages = ['THINKING'];
  setStatus('THINKING', 'THINKING', '');

  // 1. finalization trigger -> CANON_SYNC
  if (FINAL_RES.test(msg)) {
    if (/drafts\//i.test(msg)) {
      setStatus('WAITING_AUTHOR', null, '');
      return { reply: '已拒絕：非 novel/chapters/ 檔案不能觸發 Canon Sync。請先由作者把正式章節放入 novel/chapters/。', status: 'idle', stages, draftsChanged: false };
    }
    const ch = extractChapter(msg);
    if (!ch) {
      setStatus('WAITING_AUTHOR', null, '');
      return { reply: '請指定要存檔的正式章節（例如：第60章已確定，請更新設定）。', status: 'idle', stages, draftsChanged: false };
    }
    const cpath = path.join(CHAPTERS, ch + '.md');
    if (!fs.existsSync(cpath)) {
      setStatus('WAITING_AUTHOR', null, '');
      return { reply: `找不到 novel/chapters/${ch}.md，無法同步。請作者先放入正式章節檔。`, status: 'idle', stages, draftsChanged: false };
    }
    setStatus('CANON_SYNC', 'CANON_SYNC', ch);
    stages.push('CANON_SYNC');
    const g = runPy(path.join(EDITOR, 'canon_adopter.py'), [cpath, '--generate']);
    if (g.code !== 0) {
      setStatus('ERROR', null, '');
      return { reply: `Canon Sync 產生 Change Set 失敗：\n${(g.stderr || g.stdout).slice(0, 500)}`, status: 'error', stages, draftsChanged: false };
    }
    const m = g.stdout.match(/adoption written:\s*(\S+)/);
    let summary = { pending: 0, approved: 0, rejected: 0, blocked: 0 };
    let blockedIds = [];
    if (m) {
      const adop = readJsonSafe(path.resolve(REPO_ROOT, m[1]));
      if (adop && adop.summary) {
        summary = adop.summary;
        blockedIds = (adop.changes || []).filter(c => c.approval === 'BLOCKED').map(c => c.id);
        session.pendingSync = { chapter: ch, adoption: m[1] };
      }
    }
    setStatus('WAITING_AUTHOR', null, '');
    return {
      reply: [`第${parseInt(ch, 10)}章正式檔已確認，Change Set 已產生（Generate ≠ Apply）。`,
        `Pending: ${summary.pending}，Approved: ${summary.approved}，Rejected: ${summary.rejected}，Blocked: ${summary.blocked}`,
        blockedIds.length ? `需要作者決定：${blockedIds.join('、')}` : '目前無 BLOCKED 項目。',
        '請以「批准 A-001」逐項批准，或「套用」執行已批准項目（僅 APPROVED 會寫入 Canon）。'].join('\n'),
      status: 'waiting_author', stages, draftsChanged: false,
    };
  }

  // 2. approve / apply (only against pendingSync adoption)
  let mApprove = msg.match(/批准\s+([A-Z]-\d+(?:\s*[、,，]\s*[A-Z]-\d+)*)/);
  if (/全部批准/.test(msg) || mApprove || /^(套用|同步執行)\s*$/.test(msg.trim())) {
    if (!session.pendingSync) {
      setStatus('WAITING_AUTHOR', null, '');
      return { reply: '目前沒有待審核的 Change Set。請先觸發正式章節確認。', status: 'idle', stages, draftsChanged: false };
    }
    const adopPath = path.resolve(REPO_ROOT, session.pendingSync.adoption);
    let args;
    if (/^(套用|同步執行)\s*$/.test(msg.trim())) args = ['--apply'];
    else if (/全部批准/.test(msg)) args = ['--approve-all'];
    else args = ['--approve', ...mApprove[1].split(/\s*[、,，]\s*/)];
    const r = runPy(path.join(EDITOR, 'canon_adopter.py'), [adopPath, ...args]);
    setStatus('WAITING_AUTHOR', null, '');
    return { reply: (r.stdout || r.stderr).slice(0, 2000), status: r.code === 0 ? 'waiting_author' : 'error', stages, draftsChanged: true };
  }

  // 3. selection
  let mSelMulti = msg.match(/v(\d+)\s*\+\s*v(\d+)/);
  let mSelMerge = msg.match(/使用\s*v(\d+).*改成|結尾改成\s*v?(\d+)/);
  let mSel = msg.match(/(?:chapter-0*(\d+)\s*)?(?:的)?\s*(?:我選|選擇|選用)\s*v?(\d+)/)
    || msg.match(/(?:我選|選擇|選用)\s*(?:chapter-0*(\d+)\s*(?:的)?\s*)?v?(\d+)/);
  if (mSelMulti || mSelMerge || mSel) {
    const chapter = (mSel && mSel[1] ? 'chapter-' + mSel[1].padStart(3, '0') : null)
      || session.lastChapter || ('chapter-' + latestFormalId());
    const dir = path.join(DRAFTS, chapter);
    if (!fs.existsSync(dir)) {
      setStatus('WAITING_AUTHOR', null, '');
      return { reply: `找不到 ${chapter} 的草稿。`, status: 'idle', stages, draftsChanged: false };
    }
    if (mSelMerge) {
      const base = mSelMerge[1] || mSelMerge[2];
      const sel = readSelection(dir);
      const nv = nextVersions(dir, 1)[0];
      const req = (sel.baseRequest || `續寫${chapter}`) + `\n【修改指示】${msg}（基於 v${base}）`;
      const r = runSingleVersion(chapter, dir, nv, req);
      const sel2 = readSelection(dir);
      fs.writeFileSync(path.join(dir, 'selection.json'), JSON.stringify({
        ...sel2, chapter, selected: [nv],
        versions: [...new Set([...(sel2.versions || []), nv])],
        updatedAt: new Date().toISOString(),
      }, null, 2), 'utf8');
      setStatus('WAITING_AUTHOR', 'DRAFT_PRESENTATION', chapter);
      session.lastChapter = chapter;
      return { reply: `已基於 v${base} 產生 ${nv}（舊版保留）。\nValidator：${r.validator}\nConsistency：${r.consistency}`, status: 'waiting_author', stages: [...stages, 'ITERATIVE_REVISION', 'VALIDATION', 'CONSISTENCY_CHECK'], draftsChanged: true };
    }
    const picked = mSelMulti ? ['v' + mSelMulti[1], 'v' + mSelMulti[2]] : ['v' + (mSel[2] || mSel[1])];
    const okPicked = picked.filter(v => fs.existsSync(path.join(dir, v + '.md')));
    if (!okPicked.length) {
      setStatus('WAITING_AUTHOR', null, '');
      return { reply: `指定的版本不存在：${picked.join('、')}。`, status: 'idle', stages, draftsChanged: false };
    }
    const sel = readSelection(dir);
    fs.writeFileSync(path.join(dir, 'selection.json'), JSON.stringify({
      ...sel, chapter, selected: okPicked, updatedAt: new Date().toISOString(),
    }, null, 2), 'utf8');
    session.lastChapter = chapter;
    setStatus('WAITING_AUTHOR', 'AUTHOR_SELECTION', chapter);
    return { reply: `已選為目前版本（CURRENT_WORKING_DRAFT）：${chapter} ${okPicked.join('＋')}。\n注意：選擇版本不代表正式章節。`, status: 'waiting_author', stages: [...stages, 'AUTHOR_SELECTION'], draftsChanged: true };
  }

  // 4. write trigger
  if (WRITE_RES.test(msg)) {
    const num = extractChapter(msg);
    const latest = latestFormalId();
    const target = num ? String(parseInt(num, 10)).padStart(3, '0') : String(parseInt(latest, 10) + 1).padStart(3, '0');
    const chapter = 'chapter-' + target;
    const bare = /^\s*(寫作開始|開始寫|開始寫小說|開始新章|開始創作)\s*$/.test(msg);
    let baseRequest = bare ? `續寫第${parseInt(target, 10)}章` : msg;
    // 明確章節目標＋寫作意圖 ⇒ 續寫語義，讓 Context Engine 走 CONTINUE
    if (!bare && !/(續寫|繼續|接續|下一章)/.test(msg)) {
      baseRequest = `${msg}（續寫第${parseInt(target, 10)}章）`;
    }
    setStatus('CONTEXT_BUILD', 'REQUIREMENT_COLLECTION', chapter);
    const { results, stages: st, reply } = runWritingFlow(chapter, baseRequest);
    void results;
    session.lastChapter = chapter;
    session.lastRequest = baseRequest;
    return { reply, status: 'waiting_author', stages: st, draftsChanged: true };
  }

  // 5. revision (only with an existing selection)
  if (/(修改|改成|不要|加入|刪除|結尾)/.test(msg) && session.lastChapter) {
    const chapter = session.lastChapter;
    const dir = path.join(DRAFTS, chapter);
    const sel = readSelection(dir);
    if (sel.selected.length && fs.existsSync(dir)) {
      const nv = nextVersions(dir, 1)[0];
      const req = (sel.baseRequest || `續寫${chapter}`) + `\n【修改指示】${msg}`;
      const r = runSingleVersion(chapter, dir, nv, req);
      fs.writeFileSync(path.join(dir, 'selection.json'), JSON.stringify({
        ...sel, chapter, selected: [nv],
        versions: [...new Set([...(sel.versions || []), nv])],
        updatedAt: new Date().toISOString(),
      }, null, 2), 'utf8');
      setStatus('WAITING_AUTHOR', 'DRAFT_PRESENTATION', chapter);
      return { reply: `已產生 ${nv}（舊版保留，未覆寫）。\nValidator：${r.validator}\nConsistency：${r.consistency}`, status: 'waiting_author', stages: [...stages, 'ITERATIVE_REVISION', 'VALIDATION', 'CONSISTENCY_CHECK'], draftsChanged: true };
    }
  }

  // 6. discussion (no pipeline, no drafts)
  setStatus('IDLE', null, '');
  return {
    reply: '收到。若要開始寫作請說「寫作開始」（可加需求，例如：我要寫第60章）。\n若要定稿同步請說「正式章節已確認，請存檔」並指定已放入 novel/chapters/ 的章節。',
    status: 'idle', stages, draftsChanged: false,
  };
}

// ---------------------------------------------------------------- routing
const STATIC = {
  '/': ['index.html', 'text/html'],
  '/index.html': ['index.html', 'text/html'],
  '/style.css': ['style.css', 'text/css'],
  '/app.js': ['app.js', 'application/javascript'],
};

function router(req, res) {
  const url = new URL(req.url, 'http://localhost');
  const pathname = url.pathname;
  try {
    if (req.method === 'GET' && STATIC[pathname]) {
      const [file, type] = STATIC[pathname];
      res.writeHead(200, { 'Content-Type': type + '; charset=utf-8' });
      res.end(fs.readFileSync(path.join(WEB_DIR, file)));
      return;
    }
    if (req.method === 'GET' && pathname === '/api/health') {
      sendJson(res, 200, { ok: true, state: agent.state, head: gitHead() });
      return;
    }
    if (req.method === 'GET' && pathname === '/api/status') {
      sendJson(res, 200, { ...agent, states: STATES });
      return;
    }
    if (req.method === 'GET' && pathname === '/api/chapters') {
      sendJson(res, 200, { chapters: listChapters() });
      return;
    }
    let m = pathname.match(/^\/api\/chapters\/([A-Za-z0-9_.-]+)$/);
    if (req.method === 'GET' && m) {
      const id = m[1];
      if (!/^\d{3}$/.test(id) || isBlockedPath(id)) { sendJson(res, 400, { error: 'bad chapter' }); return; }
      const p = path.resolve(CHAPTERS, id + '.md');
      if (!p.startsWith(CHAPTERS + path.sep) || !fs.existsSync(p)) { sendJson(res, 404, { error: 'not found' }); return; }
      const lines = fs.readFileSync(p, 'utf8').split('\n');
      sendJson(res, 200, { id, title: (lines[0] || '').slice(0, 120), excerpt: lines.slice(0, 50).join('\n') });
      return;
    }
    if (req.method === 'GET' && pathname === '/api/drafts') {
      sendJson(res, 200, { drafts: listDrafts() });
      return;
    }
    m = pathname.match(/^\/api\/drafts\/([A-Za-z0-9_.-]+)(?:\/([A-Za-z0-9_.-]+))?$/);
    if (req.method === 'GET' && m) {
      const chapter = m[1], version = m[2] || null;
      if (!cleanSeg(chapter) || isBlockedPath(chapter + (version || ''))) { sendJson(res, 400, { error: 'bad path' }); return; }
      const dir = path.resolve(DRAFTS, chapter);
      if (!dir.startsWith(DRAFTS + path.sep) || !fs.existsSync(dir)) { sendJson(res, 404, { error: 'not found' }); return; }
      if (!version) {
        const all = listDrafts().find(d => d.chapter === chapter);
        sendJson(res, 200, all || { chapter, versions: [] });
        return;
      }
      if (!cleanSeg(version)) { sendJson(res, 400, { error: 'bad path' }); return; }
      const p = draftPath(chapter, version);
      if (!p || !fs.existsSync(p)) { sendJson(res, 404, { error: 'not found' }); return; }
      const readOpt = (f) => fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : null;
      sendJson(res, 200, {
        chapter, version,
        content: fs.readFileSync(p, 'utf8'),
        validation: readOpt(path.join(dir, version + '-validation.md')),
        consistencyMd: readOpt(path.join(dir, version + '-consistency.md')),
        consistency: readJsonSafe(path.join(dir, version + '-consistency.json')),
      });
      return;
    }
    if (req.method === 'POST' && pathname === '/api/chat') {
      let body = '';
      req.on('data', c => {
        body += c;
        if (body.length > 65536) req.destroy();
      });
      req.on('end', () => {
        let msg = '';
        try { msg = String(JSON.parse(body).message || ''); }
        catch { sendJson(res, 400, { error: 'bad json' }); return; }
        if (!msg.trim() || msg.length > 2000) { sendJson(res, 400, { error: 'bad message' }); return; }
        let out;
        try {
          out = handleChat(msg);
        } catch (e) {
          setStatus('ERROR', null, String(e && e.message || e));
          out = { reply: 'Agent 執行失敗，已停止（未修改 Canon）。', status: 'error', stages: ['ERROR'], draftsChanged: false };
        }
        sendJson(res, 200, { message: out.reply, status: out.status, stages: out.stages || [], stage: agent.stage, state: agent.state });
      });
      return;
    }
    sendJson(res, 404, { error: 'not found' });
  } catch (e) {
    sendJson(res, 500, { error: 'internal error' });
  }
}

const server = http.createServer(router);
if (require.main === module) {
  server.listen(PORT, '127.0.0.1', () => {
    console.log(`novel studio listening on http://localhost:${PORT}`);
  });
}
module.exports = { server, router, handleChat, listChapters, listDrafts };
