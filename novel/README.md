# 《說好一起當吊車尾，妳神化全開？》

- **小說名稱**：《說好一起當吊車尾，妳神化全開？》
- **作者**：星之皮卡丘
- **Penana Story ID**：216000
- **Penana**：https://www.penana.com/story/216000/說好一起當吊車尾-妳神化全開

## 目錄說明

| 目錄 | 用途 |
|---|---|
| `source/original/` | 原始資料（封面、設定、PDF 正文） |
| `source/backup/` | 舊版／備份（DOCX 正文備份、人物、後續安排） |
| `source/backup/archive/` | 確認為完全重複時的封存區（目前為空） |
| `source/penana/` | Penana 下載設定、manifest、PDF/TXT 下載產物 |
| `chapters/` | 解析後章節（`000.md` …） |
| `canon/` | 已確認設定 |
| `plot/` | 劇情規劃 |
| `ideas/` | 新想法 |
| `drafts/` | 草稿 |
| `editor/` | 編輯規則（見 `editor/consistency.md`） |

## 工具

- `scripts/audit_novel_files.py` — 只讀盤點
- `scripts/penana_download.py` — 下載 Penana PDF
- `scripts/parse_novel.py` — PDF → TXT → 章節
- `scripts/sync_novel.py` — download → hash → parse → chapters → manifest

## 資料優先順序

見 `editor/consistency.md`。禁止 `[PROPOSED]` 覆蓋 `[CANON]`。
