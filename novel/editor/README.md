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
