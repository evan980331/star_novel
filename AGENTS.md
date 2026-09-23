# Agent 行為規則 — 星星小說專案

## 專案

- 小說資料根目錄：`D:\小說`
- 小說資料系統：`novel/`
- 腳本：`scripts/`
- 報告：`docs/`（盤點見 `docs/FILE_AUDIT.md`）
- Git remote（若存在）：https://github.com/evan980331/star_novel — 不修改既有 remote。

## 資料優先級

使用者明確指示 > 小說原始正文 > 已確認設定 > 整理資料 > 推論 > AI 提案。
完整定義見 `novel/editor/consistency.md`。禁止 `[PROPOSED]` 覆蓋 `[CANON]`。

## 修改規則

- `novel/source/**` 內原始 DOCX / PDF / PNG 只讀，不得覆蓋或刪除。
- `chapters/**` 保持原文，不改寫、不潤稿、不改錯字。
- 未經使用者要求不得刪除任何小說資料。

## Git 規則

- 僅在明確要求時 commit / push。
- 不 force push、不改 remote、不提交 `.env` / token / cookie / API key。

## 小說資料位置

- 正文來源 PDF：`novel/source/original/`（原 8 檔之一）
- 正文備份 DOCX：`novel/source/backup/`
- 解析章節：`novel/chapters/`
- Penana 下載：`novel/source/penana/`

## 禁止

- 不得對 Penana 進行登入破解、CAPTCHA / Cloudflare bypass、大量請求或暴力抓取。
- 不把完整小說正文塞進本檔。

## Novel Writing Mode

Trigger:
「寫作開始」

When triggered:
- use writing-procedure.md
- read Canon before writing
- generate multiple drafts
- validate every draft
- run consistency checks
- never modify Canon during drafting
- never modify formal chapters automatically

Finalization Trigger:
「正式章節已確認，請存檔」

When triggered:
- verify chapter exists in novel/chapters/
- treat it as author-confirmed
- run Canon Sync
- block unresolved conflicts
- preserve provenance
- create adoption log
