# Writing Procedure（Agent 寫作流程，3F）

作者只用瀏覽器操作；Agent 依本流程調用既有 3A～3E 工具。
全程遵守：起草期 Canon 只讀；正式章節只能由作者放入 `novel/chapters/`。

```text
WRITE_START
 ↓
REQUIREMENT_COLLECTION
 ↓
CONTEXT_BUILD
 ↓
DRAFT_GENERATION
 ↓
VALIDATION
 ↓
CONSISTENCY_CHECK
 ↓
DRAFT_PRESENTATION
 ↓
AUTHOR_SELECTION
 ↓
ITERATIVE_REVISION
 ↓
FINAL_AUTHOR_CONFIRMATION
 ↓
CANON_SYNC
```

## WRITE_START

觸發暗號（任一即視為寫作意圖）：

```text
寫作開始／開始寫／開始寫小說／開始新章／我要寫第60章／開始創作
```

一般劇情討論不得誤觸發：必須命中上述暗號之一才進入寫作流程。

## REQUIREMENT_COLLECTION

第一步不直接生成正文，先確認：目標章節（預設接續最新正式章節）、
是否續寫、接續哪一章、劇情方向、必須出現人物、必須避免內容、
篇幅、戰鬥／日常／情感比例。上下文足夠時不再追問，只問必要資訊。

## CONTEXT_BUILD

用既有 `context_builder.py` 建立 Context。CONTINUE 優先讀取：
最後正式章節、current-arc、timeline、foreshadowing、unresolved、
主要角色、相關能力、相關武器、相關地點。不重建 Context Engine。

## DRAFT_GENERATION

每次觸發至少生成 v1／v2／v3（劇情推進型／戰鬥強化型／角色互動型），
存於 `novel/drafts/chapter-060/v1.md…`，永不覆蓋舊版（修改產生 v4…）。
Canon 權限：READ 允許、WRITE 禁止；優先級遵守
作者指令＞已確認 Canon＞正式 chapters＞確認設定＞INFERRED＞PROPOSED＞AI IDEA。

## VALIDATION ＋ CONSISTENCY_CHECK

每版自動跑 `draft-validator.py`（存 `vN-validation.md`）與
`consistency_checker.py`（存 `vN-consistency.md`／`.json`）。作者只看結果。

## DRAFT_PRESENTATION ＋ AUTHOR_SELECTION

聊天區只回報摘要（版本定位、Validator、Consistency、差異、路徑），
不貼全文；全文在 Draft 面板看。作者可說「我選 v2」「v1＋v3」
或「使用 v2，但結尾改成 v1」；選擇只代表 CURRENT_WORKING_DRAFT，
絕不代表正式章節。

## ITERATIVE_REVISION

修改流程：讀選定 Draft → 讀 Canon → 修改 → Validator →
Consistency → 存為下一版。舊版永不覆蓋。

## FINAL_AUTHOR_CONFIRMATION

暗號（任一）：

```text
正式章節已確認，請存檔／這章確定了，請存檔／
第60章已確定，請更新設定／正式版已上傳，請同步 Canon
```

非 `novel/chapters/` 檔案不能觸發；章節檔不存在則拒絕同步。

## CANON_SYNC

1. 確認章節存在於 `novel/chapters/`（作者已自行放入）。
2. 用 3E `canon_adopter.py --generate` 產生 Change Set（讀正式章節內文）。
3. Change Set → Conflict／Proposed／Inferred 檢查 → Version Lock →
   Atomic Apply → Adoption Log（與 3E 完全相同的安全鏈）。
4. 未解決 Conflict（含 C-004 無生血界）一律 BLOCKED，UI 顯示「需要作者決定」；
   PROPOSED／INFERRED 保留 provenance；AI IDEA 預設不進 Canon。
