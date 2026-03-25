# Superpowers -- 領域分析

針對四個核心問題的深入調查。

---

## Q1: Agent 如何分工與協作

### 回答

Superpowers 採用 "controller + disposable worker" 模式。主 session 的 agent 扮演 controller 角色（讀取計畫、分配任務、審查結果），而每個具體任務由一次性的 subagent 執行。Subagent 不繼承 controller 的 session context -- controller 必須精確構造每個 subagent 需要的所有資訊。

### 分工架構

```
Controller (主 session agent)
  |
  |-- 為每個 task 建構 prompt
  |-- 啟動 Implementer subagent (執行具體任務)
  |-- 啟動 Spec Reviewer subagent (驗證規格合規)
  |-- 啟動 Code Quality Reviewer subagent (驗證程式碼品質)
  |-- 管理任務進度 (TodoWrite)
```

### 協作機制

**1. Context 隔離**: 每個 subagent 獲得 controller 精心建構的 prompt，包含完整的 task 描述、架構上下文和約束條件。Subagent 不讀取計畫檔案本身 -- controller 已將相關內容貼入 prompt 中。

**Source**: `skills/subagent-driven-development/SKILL.md` -- "Don't make subagent read plan file (provide full text instead)"

**2. 問答機制**: Implementer subagent 可以在開始工作前提出問題。Controller 回答問題後重新啟動 subagent。這避免了 subagent 基於錯誤假設工作。

**Source**: `skills/subagent-driven-development/implementer-prompt.md` -- "If you have questions about the requirements... Ask them now."

**3. 狀態回報**: Implementer 必須回報四種狀態之一：`DONE`、`DONE_WITH_CONCERNS`、`NEEDS_CONTEXT`、`BLOCKED`。Controller 根據不同狀態採取不同行動。

**Source**: `skills/subagent-driven-development/SKILL.md` -- "Handling Implementer Status" 區塊

**4. 審查迴圈**: 每個 task 完成後經歷兩階段審查（先 spec 合規，再 code 品質），審查不通過則由原 implementer 修正後重新審查。

**Source**: `skills/subagent-driven-development/SKILL.md` -- Process 流程圖

**5. 平行調度**: 對於互相獨立的問題（如不同檔案的測試失敗），可同時啟動多個 subagent 平行處理。但實作任務不能平行（避免衝突）。

**Source**: `skills/dispatching-parallel-agents/SKILL.md` -- "Don't use when: Agents would interfere with each other"

### 任務傳遞方式

Controller 不是透過 API 或訊息佇列傳遞任務，而是直接將任務內容嵌入 subagent 的啟動 prompt 中。這是一個 "prompt as interface" 的設計 -- 所有協作都透過自然語言 prompt 完成。

---

## Q2: 自主性與控制的平衡

### 回答

Superpowers 在三個層面建立控制機制：結構性強制（pipeline 閘門）、行為約束（紅旗清單）、以及升級通道（允許 agent 說"我做不到"）。人類在關鍵決策點介入，但日常執行完全自主。

### 控制層次

**第一層 -- Pipeline 閘門 (Hard Gates)**

設計必須在 brainstorming 階段獲得人類批准後才能進入計畫階段。計畫必須獲批後才能進入實作。這些閘門用 `<HARD-GATE>` 標籤在 prompt 中強制執行。

**Source**: `skills/brainstorming/SKILL.md:17-19`

```
brainstorming (人類批准設計)
  -> writing-plans (subagent 審查計畫)
  -> subagent-driven-development (自主執行)
  -> finishing-a-development-branch (人類選擇 merge/PR/keep/discard)
```

**第二層 -- 行為紅旗 (Red Flags)**

每個 skill 都有明確的"不能做"清單。subagent-driven-development 列出了 12 條禁令，包括：
- 不能跳過審查
- 不能在未修正問題時繼續
- 不能平行啟動多個實作 subagent
- 不能讓 implementer 的自我審查取代正式審查
- 不能在 spec 審查通過前開始 code 品質審查

**Source**: `skills/subagent-driven-development/SKILL.md` -- "Red Flags" 區塊

**第三層 -- 升級通道 (Escalation)**

Implementer subagent 被明確告知"It is always OK to stop and say 'this is too hard for me.'"。升級觸發條件包括：需要架構決策、無法理解提供的 code、對方法不確定、task 需要計畫外的重構。

**Source**: `skills/subagent-driven-development/implementer-prompt.md` -- "When You're in Over Your Head" 區塊

Controller 對升級的回應也有明確規則：
1. 如果是 context 問題 -> 提供更多 context，重新啟動
2. 如果 task 太複雜 -> 換用更強的模型重新啟動
3. 如果 task 太大 -> 拆分成更小的 task
4. 如果計畫本身有問題 -> 升級給人類

**Source**: `skills/subagent-driven-development/SKILL.md` -- "Handling Implementer Status: BLOCKED"

### 人類介入點

| 時機 | 介入方式 |
|------|----------|
| 設計完成 | 逐段審核設計，批准後才進入計畫 |
| 計畫完成 | 選擇 subagent 模式或 inline 模式 |
| Subagent 問問題 | Controller 可能需要人類幫助回答 |
| BLOCKED 升級 | 計畫有問題時升級給人類 |
| 審查迴圈超過 3 次 | Surface to human for guidance |
| 開發完成 | 選擇 merge/PR/keep/discard |

### 自主性範圍

在 pipeline 的閘門之間，agent 有高度自主權。一旦計畫獲批，controller 可以連續自主工作數小時，為每個 task 啟動 subagent、審查結果、推進進度，無需人類介入。

**Source**: `README.md:13` -- "It's not uncommon for Claude to be able to work autonomously for a couple hours at a time without deviating from the plan you put together."

---

## Q3: Prompt / Skill 設計模式

### 回答

Superpowers 使用 SKILL.md 作為 agent 行為定義的標準格式。每個 skill 是一份結構化的 Markdown 文件，融合了流程定義、約束條件、反模式警告和 prompt template。其設計深度借鑑了行為心理學的說服原則。

### Skill 結構模式

一個典型的 SKILL.md 包含：

```
---
name: {kebab-case 名稱}
description: {觸發條件的自然語言描述}
---

# {標題}

## Overview        -- 做什麼、為什麼、核心原則
## When to Use     -- 決策樹 (Graphviz DOT)
## The Process     -- 完整流程圖 (Graphviz DOT)
## [具體流程步驟]  -- 每一步的詳細指引
## Red Flags       -- 不能做的事，以及錯誤思維的糾正
## Integration     -- 與其他 skill 的關係
```

**Source**: `skills/writing-skills/SKILL.md` -- 定義了完整的 skill 撰寫指南

### 關鍵設計模式

**1. Description-based 觸發**

Skill 的 `description` frontmatter 同時是觸發條件和用途說明。`using-superpowers` 的 bootstrap 指令強制 agent 在有 1% 可能性時就調用 skill，靠 description 匹配來決定是否適用。

**Source**: 每個 skill 的 frontmatter，如 `skills/brainstorming/SKILL.md:3` -- `description: "You MUST use this before any creative work..."`

**2. Rationalization Table (反理性化表)**

`using-superpowers/SKILL.md` 包含一張表格，列出 agent 可能用來跳過 skill 的 11 種"藉口"及其對應的反駁。這是行為心理學中 "commitment and consistency" 原則的應用 -- 預先識別並封堵逃避路徑。

**Source**: `skills/using-superpowers/SKILL.md:78-93` -- Red Flags 表格

**3. Prompt Template 分離**

複雜的 subagent prompt 不直接寫在 SKILL.md 中，而是作為獨立的 .md 檔案。controller 讀取 template 並填入具體的 task 內容。

模板結構：
- `implementer-prompt.md` -- 實作者的完整指令，包含問答機制、自我審查清單、回報格式
- `spec-reviewer-prompt.md` -- 規格審查者的指令，包含不信任原則
- `code-quality-reviewer-prompt.md` -- 程式碼品質審查者的指令

**Source**: `skills/subagent-driven-development/` 目錄下三個 prompt 檔案

**4. 說服原則的系統應用**

`persuasion-principles.md` 文件列出了七個說服原則（Authority、Commitment、Scarcity、Social Proof、Unity、Reciprocity、Liking），並示範如何在 skill 撰寫中應用。例如：

- **Authority**: "You are a Senior Code Reviewer with expertise in..."
- **Commitment**: "Create TodoWrite todo per item" -- 一旦建立 checklist，agent 傾向完成
- **Scarcity**: `<HARD-GATE>` 和 "Never" 清單製造稀缺感（選項有限）
- **Unity**: "You are implementing Task N" -- 給 subagent 身份認同

**Source**: `skills/writing-skills/persuasion-principles.md`

**5. 流程視覺化 (Graphviz DOT)**

每個複雜的決策流程都用 Graphviz DOT 格式的流程圖描述，而非純文字敘述。這讓 agent 能更精確地理解分支邏輯。

**Source**: 幾乎所有 SKILL.md 都包含 `digraph` 定義

**6. Skill 的 TDD**

`testing-skills-with-subagents.md` 定義了對 skill 本身進行 TDD 的方法論：用 subagent 作為"測試者"，給出特定 scenario 讓 subagent 嘗試執行 skill，觀察是否按照預期行為，然後修正 skill 直到通過所有 test case。

**Source**: `skills/writing-skills/testing-skills-with-subagents.md`

---

## Q4: 可擴展性與組合性

### 回答

Superpowers 透過三個機制實現擴展：扁平的 skill 目錄結構允許任意新增 skill；skill 之間透過名稱引用形成鬆耦合的依賴鏈；以及 agent 在 skill 內部的 prompt 引用其他 skill 的內容。

### 新增 Skill 的流程

1. 在 `skills/` 下建立新目錄
2. 寫 SKILL.md，包含 name/description frontmatter
3. description 定義觸發條件 -- 系統自動發現
4. 可選：新增輔助 prompt template 檔案
5. 用 `writing-skills` skill 的指南確保品質

**Source**: `skills/writing-skills/SKILL.md`

### 組合機制

**1. Skill 鏈 (Skill Chaining)**

Skill A 的指令可以明確要求接下來調用 Skill B。例如 brainstorming 的結尾是 "Invoke the writing-plans skill"，writing-plans 的結尾是 "Use superpowers:subagent-driven-development"。

```
brainstorming --> writing-plans --> subagent-driven-development --> finishing-a-development-branch
                                              |
                                              +--> test-driven-development (subagent 內部使用)
                                              +--> requesting-code-review (審查時使用)
```

**Source**: `skills/brainstorming/SKILL.md` -- "The terminal state is invoking writing-plans."

**2. Skill 嵌套引用**

Skill 內部可以引用其他 skill 的內容。如 subagent-driven-development 的 code quality reviewer prompt 引用了 `requesting-code-review/code-reviewer.md` 作為 template。

**Source**: `skills/subagent-driven-development/code-quality-reviewer-prompt.md` -- "Use template at requesting-code-review/code-reviewer.md"

**3. 平台適配層**

每個平台有自己的 tool mapping。`using-superpowers/references/codex-tools.md` 和 `gemini-tools.md` 定義了 tool 名稱的轉換規則，讓同一套 skill 能在不同平台運作。

**Source**: `skills/using-superpowers/references/codex-tools.md`, `gemini-tools.md`

### 擴展限制

**不支援的擴展場景**:
- Skill 無法定義自訂工具或 API -- 它只能使用宿主平台已有的 tool
- Skill 之間沒有程式化的依賴管理 -- 引用是字串名稱，不存在版本控制
- 沒有 skill 發現的 registry 機制 -- 依賴平台的 skill discovery（如 Claude Code 的 `Skill` tool）
- 沒有跨 session 的狀態持久化 -- 每個 session 從 bootstrap 重新開始

### 領域適配

Superpowers 目前專注於軟體開發領域，所有 skill 都圍繞 coding workflow。但其架構本身是領域無關的 -- SKILL.md 格式、prompt template 模式、bootstrap hook 機制都可以用於非軟體領域。

要擴展到新領域（如研究分析、文件撰寫），需要：
1. 建立該領域的 skill 集合
2. 修改 `using-superpowers/SKILL.md` 的 bootstrap 指令以涵蓋新領域
3. 可選：建立該領域的 prompt template
