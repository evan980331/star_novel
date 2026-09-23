# Consistency Rules（3D 一致性檢查規則）

Consistency Checker 是 deterministic 檢查器：只能「檢查與報告」，
不能修改 Canon、正式章節、Draft，不能採用設定、不能解 Conflict。

定位：

```text
Draft
 ↓
Consistency Checker
 ↓
JSON Report
 ↓
Markdown Report
 ↓
PASS / WARNING / ERROR
 ↓
作者人工確認
```

明確聲明：

```text
Consistency PASS ≠ 文學品質保證
Consistency PASS ≠ Canon 自動採用
Consistency WARNING ≠ 一定錯誤
Consistency ERROR = 發現明確或高度可確定的規則違反
```

Checker 無法完整理解小說語意；所有判斷都是關鍵字與結構層級的啟發式檢查，
最終一律以作者人工確認為準。

## 檢查一覽

| ID | 檢查 | 嚴重度上限 |
|----|------|-----------|
| C3D-001 | Unknown Entity（人物／能力／武器／勢力／地點／術語） | WARNING（標 `[NEW_SETTING]`，不判錯） |
| C3D-002 | CHARACTER_STATUS（已確認死亡角色重新出現） | ERROR；若死亡本身是 `[INFERRED]`／`[PROPOSED]` 則 WARNING |
| C3D-003 | CHARACTER_LOCATION（位置矛盾且無移動交代） | WARNING，不自行推論移動 |
| C3D-004 | ABILITY（專屬能力被他人使用、神覺擅自啟動） | ERROR；Canon 未規定者 WARNING |
| C3D-005 | WEAPON（持有者錯誤、未記載特殊能力） | ERROR；未知新武器 WARNING |
| C3D-006 | TIMELINE（不存在章節引用、未來事件當已發生） | ERROR／WARNING |
| C3D-007 | CONTINUITY_059（續寫無理由跳過 #059 結尾狀態） | WARNING |
| C3D-008 | CONFLICT（涉及未解決衝突，C-004 特別處理） | WARNING＋`[NEEDS_AUTHOR_DECISION]`，禁靜默解決 |
| C3D-009 | PROPOSED_USAGE（未經採用指示使用 Proposed） | WARNING＋`[NEEDS_AUTHOR_DECISION]` |
| C3D-010 | INFERRED_USAGE（推論寫成確定事實） | WARNING |
| C3D-011 | FORESHADOWING（疑似提前揭露／否定伏筆） | WARNING（不得判 ERROR） |
| C3D-012 | UNRESOLVED（處理未解支線） | INFO；若同時違反 Canon 則 WARNING／ERROR |
| C3D-013 | AI_IDEA_USAGE（引用 ideas 的 AI 構想） | WARNING |
| C3D-014 | PROTECTED_FILE_MODIFIED（Checker 造成保護目錄異動） | ERROR |

## Status 判定

```text
ERROR > 0   → ERROR
ERROR = 0 且 WARNING > 0 → WARNING
否則 → PASS（可含 INFO）
```

Exit code：普通模式 ERROR→1、WARNING→0；`--strict` 下 WARNING→1。INFO 不影響。
