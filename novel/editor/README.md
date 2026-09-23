# Novel Editor Agent Core（3B）

本目錄為 Novel Editor Agent 的核心：Context Engine。
只負責「準備寫作上下文」，不負責寫小說、不呼叫 LLM 續寫。

## 檔案

| 檔案 | 用途 |
|------|------|
| `context_builder.py` | Context Builder（CLI，可執行，唯讀） |
| `context-schema.json` | Context JSON Schema（Canon / Plot / Review 分離） |
| `retrieval-rules.md` | 檢索規則（優先級、衝突處理、相關度、唯讀保證） |
| `writing-rules.md` | 未來 Writer Agent 寫作規則 |
| `consistency.md` | 一致性規則（含寫作前／中／後檢查） |

## 使用

```bash
python novel/editor/context_builder.py --request "續寫第60章"
python novel/editor/context_builder.py --request "寫星星與沐寒戰鬥" --max-items 30
python novel/editor/context_builder.py --request "分析星星目前能力" --format markdown
```

輸出為 JSON（預設）或 Markdown（`--format markdown`），僅為 Context，
可直接提供給未來的 Writer Agent 使用。

## Writer Agent（3C）

```text
User
 ↓
writer.py
 ↓
context_builder.py
 ↓
Context
 ↓
WriterProvider
 ↓
Draft
 ↓
draft-validator.py
 ↓
Validation Report
 ↓
novel/drafts/
```

| 檔案 | 用途 |
|------|------|
| `writer.py` | Writer Agent CLI（經 Context Builder，不可繞過） |
| `writer-schema.json` | Draft JSON Schema |
| `writer-prompt.md` | Writer 系統提示詞（含 Canon 規則與禁令） |
| `draft-validator.py` | Draft Validator（唯讀，產出 Validation Report） |

Provider 介面 `WriterProvider.generate(context, instruction)`；
`mock` 用於測試（只產出 `[MOCK DRAFT]`），`openai-compatible` 經環境變數
（`LLM_PROVIDER`／`LLM_BASE_URL`／`LLM_MODEL`／`LLM_API_KEY`）設定，
未設定時明確回報而不 crash。草稿只能寫入 `novel/drafts/`。

```bash
python novel/editor/writer.py --request "續寫第60章" --provider mock
python novel/editor/draft-validator.py novel/drafts/chapter-060-001.md
```

## 3D Consistency / Quality Gate

```text
Writer 負責產生 Draft
Validator 負責格式與基本結構
Consistency Checker 負責 Canon / Plot / Review 一致性
作者負責最終確認
```

```bash
python novel/editor/consistency_checker.py novel/drafts/chapter-060-v1.md --json
python novel/editor/consistency_checker.py novel/drafts/chapter-060-v1.md --markdown
python novel/editor/writer.py --request "續寫第60章" --provider mock \
  --output novel/drafts/chapter-060-v1.md --consistency
```

明確聲明：

```text
Consistency PASS ≠ 文學品質保證
Consistency PASS ≠ Canon 自動採用
Consistency WARNING ≠ 一定錯誤
Consistency ERROR = 發現明確或高度可確定的規則違反
```

Checker 只能檢查與報告（JSON／Markdown Report），不得修改 Canon、
正式章節、Draft，不得採用設定、不得解 Conflict。規則見
`consistency-rules.md`，報告格式見 `consistency-schema.json`。

## 3E Canon Adoption / Author Approval

```text
Generate ≠ Apply
Approve ≠ Apply
只有 --apply 才會正式修改 Canon
```

```bash
# 1. Generate：只產生候選變更（全部 PENDING，不動 Canon）
python novel/editor/canon_adopter.py novel/drafts/chapter-060-v1.md --generate

# 2. Review：閱讀 novel/adoptions/<name>-adoption.md

# 3. Approve / Reject：作者逐項決策
python novel/editor/canon_adopter.py <adoption.json> --approve A-001 A-003
python novel/editor/canon_adopter.py <adoption.json> --reject A-002

# 4. Apply：僅 APPROVED 可寫入（版本鎖＋原子寫入＋log）
python novel/editor/canon_adopter.py <adoption.json> --apply

# 5. Audit：確認結果
python scripts/audit_canon.py --review
```

| 檔案 | 用途 |
|------|------|
| `canon_adopter.py` | Change Set Generator＋Approval Gate＋Apply |
| `adoption-schema.json` | Adoption JSON Schema |
| `adoption-rules.md` | 採用安全規則 |

規則見 `adoption-rules.md`：涉及未解決 Conflict → BLOCKED（C-004 永不靜默解決）；
`[PROPOSED]`／`[INFERRED]`／`[AI IDEA]` 需作者明確批准才可進 Canon；
`--approve-all` 僅在無 conflict、無未確認來源、無 ERROR、全為安全 ADD 時放行。
