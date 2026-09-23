# Writing Rules（未來 Writer Agent 寫作規則）

> 本檔案規範未來的 Writer Agent。3B 階段不執行寫作，只定義規則。

## 寫作前

1. 必須先以 `context_builder.py` 產生 Writing Context。
2. 讀取 Context 內的 conflicts 與 pending author decisions。
3. 未確認 `[PROPOSED]` 不得當作既定事實使用；`[AI IDEA]` 不得使用。

## 寫作中

- 不得自行修改既有 Canon、自行解決 `[CONFLICT]`。
- 不得創造與既有能力規則衝突的新能力。
- 不得改變人物既有背景而不標記；不得修改歷史事件。
- 涉及 `[CONFLICT]` 的內容必須停下並要求作者決策。

## 寫作後

- 執行 Canon consistency check（`scripts/audit_canon.py --review`）。
- 新增設定一律標記為 `[PROPOSED]`，不得自動寫入正式 Canon。
- 新增 `[INFERRED]` 必須附 `confidence` / `source` / `reason`。
