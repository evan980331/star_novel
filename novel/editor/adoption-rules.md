# Adoption Rules（3E Canon 採用規則）

3E 不是 AI 判斷器，而是 **Change Set Generator + Explicit Approval Gate**：

```text
Draft
 ↓
分析 Draft 與目前 Canon 的差異
 ↓
產生候選變更（全部 PENDING，不動 Canon）
 ↓
作者選擇採用哪些（Approve / Reject）
 ↓
只有被明確核准的項目才可以寫入 Canon（--apply）
 ↓
留下 Adoption Log
```

## 鐵律

```text
Generate ≠ Apply
Approve ≠ Apply
只有 --apply 才會正式修改 Canon
```

- 產生 Change Set 時絕對不能修改 Canon。
- 所有變更預設 `approval = PENDING`。
- AI 不得自動把 Draft 內容加入 Canon，不得自動採用 NEW_SETTING／`[PROPOSED]`，
  不得自動解決 `[CONFLICT]`，不得把 `[INFERRED]` 自動升級。
- 不得刪除 Canon：移除舊設定只能用 `DEPRECATE` 並經作者確認。
- 永遠不得修改 `novel/source/original/`、`novel/source/backup/`、`novel/chapters/`。

## Conflict

- 候選變更若涉及 `conflicts.md` 未解決衝突 → `approval = BLOCKED`。
- `BLOCKED(conflict)` 在 `author-decisions.md` 出現明確決策前，
  任何 approve 路徑（含 `--approve-all`）都必須拒絕。
- 特別是 C-004（無生血界）：禁止 AI 自己選版本。

## 來源保留

- `source_status` 必須保留：`NEW_SETTING`／`PROPOSED`／`INFERRED`／`AI_IDEA`／`CANON`。
- `[PROPOSED]`→Canon 需作者批准；`[INFERRED]`→Canon 需作者確認推論成立；
  `[AI IDEA]` 預設 BLOCKED，僅作者明確 `--approve` 可解鎖（`--approve-all` 永遠拒絕）。

## 版本鎖與原子寫入

- Change Set 建立時記錄 `canon_version`（git HEAD）；`--apply` 時重取，
  不同即 `ERROR CANON_VERSION_CHANGED` 並停止。
- 正式寫入先算好全部新內容再一次性 replace；任何一項失敗則 Canon 保持原樣。
- 每次 apply 建立 `novel/adoptions/<timestamp>-adoption-log.json`，
  記錄 draft、canon 前後 hash、批准／拒絕清單，可追查每條設定的來源。
- 重複 `--apply` 必須安全失敗（狀態已是 APPLIED）。
