# Canon 審核區（Review）

本目錄為第 3A 階段建立的「Canon 衝突與作者確認系統」。

目的：把 Canon 中的 `[CONFLICT]`、`[INFERRED]`、`[PROPOSED]` 系統化整理，
讓後續 Novel Editor Agent 不會自行把未確認內容當成正式 Canon。

> 本目錄為整理資料，不屬於正式 Canon。引用時仍以 `novel/canon/`、
> `novel/plot/`、`novel/ideas/` 原檔案為準。

## 檔案說明

| 檔案 | 用途 |
|------|------|
| `conflicts.md` | 實際 Canon 衝突逐筆整理（C-001 起） |
| `proposed.md` | 所有 `[PROPOSED]` 追蹤（P-001 起） |
| `inferred.md` | 所有 `[INFERRED]` 分級整理（I-A/B/C 起） |
| `author-decisions.md` | 作者確認表（作者修改 Canon 的主要入口） |
| `review-status.json` | 機器可讀統計（由掃描產生，勿手寫） |

## 掃描基準

- 掃描範圍：`novel/canon/`、`novel/plot/`、`novel/ideas/` 共 18 檔。
- `novel/canon/README.md` 內的 `[CONFLICT]` / `[INFERRED]` / `[PROPOSED]` /
  `[AI IDEA]` 為文件定義與範例，不計入實際條目。
- 原始標記出現次數（`python scripts/audit_canon.py`）：`[CONFLICT]` 13、
  `[INFERRED]` 77、`[PROPOSED]` 102、`[AI IDEA]` 11（含 README 範例與指引文字）。
- 去除 README 範例與各檔指引文字後，實際追蹤條目見 `review-status.json`。

## 狀態定義

- 衝突：`[UNRESOLVED]` / `[RESOLVED]`
- 提案：`[PROPOSED]` / `[ACCEPTED]` / `[REJECTED]` / `[SUPERSEDED]`
- 作者決定：待確認 / 已確認 / 已否決

## 驗證

```bash
python scripts/audit_canon.py --review
python scripts/test_canon_review.py
```
