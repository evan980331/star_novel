# Retrieval Rules（Context 檢索規則）

Context Builder 檢索資料時必須遵守以下規則。本檔案為 3B Context Engine 的行為規範。

## 1. Context 優先級

```text
作者明確指示
>
作者已確認 Canon
>
正式正文
>
確認設定
>
[INFERRED]
>
[PROPOSED]
>
[AI IDEA]
```

## 2. 衝突處理

如果不同來源衝突：

```text
不要自行選擇
→ 加入 warnings
→ 保留來源
→ 要求作者決策
```

凡 Context 包含 `[UNRESOLVED]` 衝突，必須加入：

```text
WARNING:
Canon conflict detected.
Do not resolve automatically.
Author decision required.
```

## 3. 標記安全

- `[PROPOSED]` 必須保留標記，不得輸出成已確定設定。
- `[INFERRED]` 必須保留 `confidence` / `source` / `reason`，禁止自動升級成 Canon。
- `[AI IDEA]` 不得進入 Canon Context（僅可存在於 ideas 側註，且須標明非 Canon）。

## 4. 相關度評分

```text
完全命中人物 / 能力 / 地點 / 章節
→ 高相關（high）

同義詞 / 別名 / 關聯人物
→ 中相關（medium）

僅一般關鍵字
→ 低相關（low）
```

預設只輸出高相關 + 必要中相關；低相關預設捨去（除非 `--max-items` 允許）。

## 5. 大小控制

- 不得把整個 60 章全文塞進 Context；章節一律只取摘錄（開頭 + 結尾），並註明 `excerpt: true`。
- `--max-items` 限制輸出條目總數；截斷時優先保留高相關，並在 `warnings` 註明。
- 續寫類 request 至少讀取：前一章摘錄、current-arc、timeline 最近事件、
  foreshadowing、unresolved、future 對應段落。

## 6. 正規化匹配

匹配前必須正規化（大小寫、空白、中文標點），並支援別名：

- 人物別名：如「主角」→ 星星、「光之子」→ 索爾、「震動人」→ 赫連震
- 武器別名：如「流星手套」↔「彗星手套」、「星環」→ 六星飛環
- 地點別名：如「學院」→ 聖啟明皇家學院、「秘境」→ 荒古秘境

不得只做完整字串匹配。

## 7. 唯讀保證

Context Builder 為 READ ONLY：不得修改 Canon、chapter、plot、review；
不得自動接受 Proposed、自動解決 Conflict、自動新增角色或能力。輸出只能是 Context。
