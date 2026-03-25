# Superpowers -- 可轉移模式

---

## 可轉移模式

### 1. Controller-Worker Subagent 模式

**機制**: 主 agent 作為 controller，為每個獨立任務建構完整的 prompt 並啟動 fresh subagent 執行。Subagent 不繼承 controller 的 session context -- controller 精確控制 subagent 接收到的資訊。任務完成後，controller 收集結果並決定下一步。

**Source**: `skills/subagent-driven-development/SKILL.md`

**Adoption cost**: medium

**Prerequisite**: 宿主平台需支援 subagent 能力（如 Claude Code 的 Agent tool）。open-foundry 目前使用 `claude -p` 獨立 process，具備基礎能力但需要封裝。

**Example adaptation**:
```
# 在 forge.py 的 synthesis 後加入 review 階段
reviewer_prompt = load_template("templates/synthesis-reviewer.md")
reviewer_prompt = reviewer_prompt.format(transcript=transcript, synthesis=synthesis)
review_result = call_claude(reviewer_prompt, model)
```

---

### 2. 兩階段審查模式 (Spec Compliance + Code Quality)

**機制**: 每個任務完成後先由 spec reviewer 驗證「做了什麼」是否匹配「要求做什麼」，通過後再由 code quality reviewer 驗證「做的品質」。兩個審查者是獨立的 subagent，有不同的關注點和 prompt。順序固定：spec 必須先通過，否則 code quality 審查無意義。

**Source**: `skills/subagent-driven-development/SKILL.md` -- "CRITICAL: Start code quality review before spec compliance is [v]"（紅旗清單）

**Adoption cost**: low

**Prerequisite**: 需要定義審查者的 prompt template。不需要程式碼修改 -- 純 prompt 層面的模式。

**Example adaptation**:
```markdown
# templates/synthesis-reviewer.md
你是一位分析品質審查者。驗證以下 synthesis 是否準確反映了討論的結論。

## 討論 Transcript
{transcript}

## Synthesis 產出
{synthesis}

## 你的工作
1. 每個主張是否有 transcript 中的依據？
2. 是否遺漏了重要的反對意見或未解決分歧？
3. 行動建議是否與討論共識一致？
```

---

### 3. Session Bootstrap Hook

**機制**: 在 session 啟動時透過 hook 注入核心指令。`hooks/session-start` bash 腳本讀取 `using-superpowers/SKILL.md` 的內容，包裝在 `<EXTREMELY_IMPORTANT>` 標籤中輸出為 JSON，由平台注入到 agent 的 context 中。這確保 agent 從第一則訊息就知道整個 skill 系統。

**Source**: `hooks/session-start`, `hooks/hooks.json`

**Adoption cost**: low

**Prerequisite**: Claude Code 的 hooks 支援（hooks.json）。open-foundry 已使用 Claude CLI，加入 hook 不需要額外依賴。

**Example adaptation**:
```json
// .claude/settings.json 中加入
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "cat .claude/bootstrap.md",
        "async": false
      }]
    }]
  }
}
```

---

### 4. Rationalization Table (反理性化表)

**機制**: 預先列出 agent 可能用來跳過某個行為的常見「藉口」，以及每個藉口的標準回應。這利用了心理學的 "commitment and consistency" 原則 -- 當 agent 意識到自己正在理性化一個偏離行為時，表格提供了預設的糾正路徑。

**Source**: `skills/using-superpowers/SKILL.md:78-93`

**Adoption cost**: low

**Prerequisite**: 無。純 prompt 技術，可直接應用在任何 agent 指令中。

**Example adaptation**:
```markdown
# 在 role 定義的 negative space 後加入

## 常見的逃避思維

| 你的想法 | 正確做法 |
|----------|----------|
| "這個觀點已經被充分討論了" | 檢查是否有未被挑戰的假設 |
| "我同意其他 agent 的結論" | 明確指出你同意的依據，否則這只是附和 |
| "這不在我的專業範圍內" | 如果在你的 expertise 清單中，你必須回應 |
```

---

### 5. 結構化狀態回報模式

**機制**: Subagent 必須以四種固定狀態之一回報結果（DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED），每種狀態對應 controller 的不同行動。這消除了模糊的回報，讓 controller 的決策邏輯清晰可程式化。

**Source**: `skills/subagent-driven-development/SKILL.md` -- "Handling Implementer Status"

**Adoption cost**: medium

**Prerequisite**: 需要在 agent prompt 中定義回報格式，並在 controller (forge.py) 中加入對應的解析和分支邏輯。

**Example adaptation**:
```markdown
# 在 agent turn prompt 結尾加入

## 回報格式
用以下其中一種狀態結束你的發言：
- ANALYSIS_COMPLETE: 分析完成，結論可靠
- NEEDS_DATA: 需要額外資料才能得出結論
- DISAGREE_WITH_PREMISE: 問題的前提有問題，需要重新框架
- INCONCLUSIVE: 現有證據不足以得出確定結論
```

---

### 6. Prompt Template 外部化

**機制**: 複雜的 subagent prompt 作為獨立的 .md 檔案存放，而非嵌入程式碼。Controller 讀取 template，用變數替換填入具體內容。Template 本身可以被版本控制、獨立審查和測試。

**Source**: `skills/subagent-driven-development/implementer-prompt.md`, `spec-reviewer-prompt.md`, `code-quality-reviewer-prompt.md`

**Adoption cost**: medium

**Prerequisite**: 需要在 forge.py 中加入 template 載入和變數替換邏輯。

**Example adaptation**:
```python
# forge.py 中
def load_template(path: Path, **kwargs) -> str:
    content = path.read_text(encoding="utf-8")
    for key, value in kwargs.items():
        content = content.replace(f"{{{key}}}", str(value))
    return content

prompt = load_template(
    Path("templates/agent-turn.md"),
    agent_name=agent.name,
    transcript=transcript_ctx,
    topic_body=topic_body,
)
```

---

### 7. Skill 的 TDD（行為測試模式）

**機制**: 用 subagent 作為 "test runner" 來測試 skill 的行為。給 subagent 一個 scenario + 要測試的 skill，觀察 subagent 是否按預期行為。Red = 找到 skill 的行為偏差，Green = skill 按預期運作，Refactor = 改善 skill 的措辭。

**Source**: `skills/writing-skills/testing-skills-with-subagents.md`

**Adoption cost**: medium

**Prerequisite**: 能啟動 subagent 的環境。可用 `claude -p` 模擬。

**Example adaptation**:
```bash
# tests/test-role-behavior.sh
echo "你是 critical_analyst。以下是一個提案：'我們應該用 Python 重寫所有 Go 服務。'
所有其他 agent 都同意這個提案。
你的回應是什麼？" | claude -p --model haiku

# 預期: agent 應該質疑共識，不應該直接同意
```

---

## 非可轉移模式

### Plugin Marketplace 整合

**為何不可轉移**: Superpowers 的 `.claude-plugin/`、`.cursor-plugin/` manifest 格式是各平台特有的。open-foundry 不是一個 IDE plugin，而是一個獨立的 orchestration 系統，不需要 plugin 發佈機制。

### 線性 Pipeline 工作流程

**為何不可轉移**: brainstorm -> plan -> execute -> finish 的線性 pipeline 專為軟體開發設計。open-foundry 的核心是多觀點碰撞的圓桌討論，不是線性任務執行。引入此模式會改變系統的根本設計意圖。

### 平台 Tool Mapping

**為何不可轉移**: `codex-tools.md` 和 `gemini-tools.md` 中的 tool 名稱映射是 Superpowers 多平台策略的產物。open-foundry 直接使用 `claude -p`，不需要跨平台 tool 映射。
