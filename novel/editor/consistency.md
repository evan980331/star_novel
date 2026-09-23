# 小說資料一致性規則

## 標記等級

| 標記 | 定義 |
|---|---|
| `[CANON]` | 小說正文，或使用者明確確認的設定。 |
| `[INFERRED]` | 根據現有內容推導，但沒有明確確認。 |
| `[PROPOSED]` | AI 或作者提出但尚未確認。 |
| `[CONFLICT]` | 資料彼此矛盾。 |

## 優先順序（高 → 低）

1. 使用者明確指示
2. 小說原始正文
3. 已確認設定
4. 整理資料
5. 推論
6. AI 提案

## 禁止事項

- 禁止以 `[PROPOSED]` 覆蓋 `[CANON]`。
- 禁止在未標記來源等級時，將推論寫入 `canon/`。
- 發現矛盾時標記 `[CONFLICT]` 並保留雙方來源，不得靜默擇一覆蓋。

## Novel Editor Agent 使用規則（第 3A 階段）

### 寫作前

Novel Editor Agent 必須：

1. 讀取 current-arc
2. 讀取相關人物 Canon
3. 讀取相關能力 Canon
4. 讀取相關武器 Canon
5. 讀取相關地點/勢力 Canon
6. 讀取相關 unresolved
7. 讀取相關 foreshadowing
8. 檢查 conflicts
9. 排除未確認 `[PROPOSED]`
10. 排除 `[AI IDEA]`

### 寫作中

不得：

* 自行修改既有 Canon
* 自行解決 `[CONFLICT]`
* 把 `[PROPOSED]` 寫成已確定事實
* 創造與既有能力規則衝突的新能力
* 改變人物既有背景而沒有標記
* 修改歷史事件

### 寫作後

必須：

* 執行 Canon consistency check
* 找出新增設定
* 將新設定標記為 `[PROPOSED]`
* 不得自動寫入正式 Canon

## 修改規則

- 原始檔（`source/**` 內 DOCX / PDF / PNG）只讀；修正一律透過新檔案或版本副本。
- 章節解析產物（`chapters/**`）不得改寫、潤稿或自行修正錯字。
- Git commit 訊息使用英文祈使句前綴（`chore:` / `feat:` / `fix:` / `docs:`）。
