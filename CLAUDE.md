# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 5. 口语化项目开发 — Linear 工作流自动化

### 项目配置

```yaml
project:
  name: "GraphRAG"
  team: "Finley1991"     # Linear 团队名
  team_key: "FIN"        # Linear issue 前缀（如 FIN-37）
  repo: "https://github.com/Finley1991/GraphRAG"
  python: ".venv/bin/python"    # Python 3.12.11 虚拟环境
  pip: ".venv/bin/pip"          # pip 包管理器
```

**注意：** 口语中可使用各种变体（"GraphRAG"、"多模态RAG项目"、"RAG 项目"、"知识库项目"），统一对应上述项目配置。

### 触发模式

用户用自然口语说出以下模式时，执行对应的 MCP 工具链：

#### 模式一：开始任务

**触发短语：** "开始做 X" | "做一下 X" | "我来做 X" | "认领 X" | "开始 X"

其中 X 为任务描述（模糊匹配 Linear issue 标题）。

**执行步骤：**
1. `linear_list_issues(assignee: "me", team: "Finley1991", state: "Backlog")` — 查出待办列表
2. 在结果中按标题相似度模糊匹配用户说的 "X"
3. 如果匹配到唯一 issue：
   - `linear_get_issue(id)` — 获取详情（含 description、priority、labels、milestone）
   - `linear_update_issue(id, state: "In Progress", assignee: "me")` — 设为进行中
   - 输出 `git branch` 命令：`git checkout -b feature/fin-{number}-{kebab-title}`
   - 总结 issue 的 description/目标给用户
4. 如果匹配到多个：列出候选让用户选
5. 如果没匹配到：询问是否要创建新 issue → `linear_create_issue(title, team: "Finley1991", state: "In Progress", assignee: "me")`

#### 模式二：完成任务

**触发短语：** "X 做完了" | "完成 X" | "X 搞定了" | "X 做好了"

**执行步骤：**
1. 如果当前有通过模式一开始的任务，用该 issue ID；否则 `linear_list_issues(assignee: "me", team: "Finley1991", state: "In Progress")` 查当前进行中
2. `linear_update_issue(id, state: "Done")` — 标记完成
3. 询问是否要：
   - 创建 commit（在本地执行 git add + commit）
   - 创建 PR（`gh pr create` + `linear_create_attachment` 关联到 issue）
   - 直接继续下一个任务

#### 模式三：同步计划到 Linear

**触发短语：** （粘贴 Markdown 内容，包含 "Phase N: xxx" 标题）

**执行步骤：**
1. 解析 Markdown 中所有 `Phase N:` / `### Phase N` 等标题
2. 对每个 Phase：
   - `linear_list_issues(team: "Finley1991", project: "GraphRAG")` — 查已有 issues
   - 对比标题，找出缺失的条目
   - 批量创建缺失的 issue：`linear_create_issue(title, team: "Finley1991", project: "GraphRAG", state: "Backlog")`
3. 输出摘要：已创建 N 个、已存在 N 个

#### 模式四：查看任务

**触发短语：** "看下我的任务" | "我有哪些任务" | "待办任务" | "任务列表"

**执行步骤：**
1. `linear_list_issues(assignee: "me", team: "Finley1991")` — 获取当前用户所有 issues
2. 按状态分组输出（Backlog / In Progress / Done），每项含 `FIN-编号: 标题` + 优先级 + 里程碑

### 行为规范

- **精确匹配再行动：** 只有用户明确说出上述触发短语时才执行 Linear MCP 调用。日常对话不触发。
- **先 echo 再执行：** 调用任何 MCP 工具前，先输出一句话："好的，我来查一下..." / "正在设为完成..." 等。
- **批量操作需确认：** 创建/修改超过 3 个 issue 时，先列出变更清单让用户确认。
- **分支命名规则：** `feature/fin-{number}-{kebab-case-title}`
- **MCP 优先：** 所有 Linear 操作通过 `mcp__plugin_linear_linear__*` 工具完成，不手动调用 HTTP API。

### 反模式（不要这样做）

- 不要主动同步 Linear 状态 — 只在触发时操作
- 不要创建与已有 issue 重复的条目
- 不要在非触发模式下引用 Linear 数据
- 不要修改非当前用户的 issue 分配

---

## 6. Phase 开发流程规范

### 总体原则

每个 Phase 的开发遵循 **分支开发 → 增量提交 → 自动化测试 → E2E 验证 → Code Review → 合并** 的完整流程，并与 **Linear Issue 状态同步**。

### Linear Issue 状态映射

| 开发阶段 | Linear Issue 状态 | 触发条件 |
|---------|------------------|---------|
| 未开始 | `Backlog` | Issue 创建后的默认状态 |
| 开发中 | `In Progress` | 开始 Phase 开发，创建 feature 分支 |
| 待审核 | `In Review` | 所有 commit 完成，创建 PR |
| 已完成 | `Done` | PR 合并到 main 分支 |

### 流程步骤

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Phase 开发流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 开始 Phase                                                          │
│     └── 从 main 分支新建 feature 分支                                    │
│         命名规则: feature/phase{N}-{简短描述}                            │
│         示例: feature/phase2-kafka-ingestion                            │
│     └── 【Linear】更新 Issue 状态为 In Progress                          │
│         工具: mcp__linear__update_issue(state: "In Progress")           │
│                                                                         │
│  2. 开发过程                                                             │
│     └── 每完成一个独立 Task → 立即 git commit                            │
│         commit 格式: feat(phase{N}): {task描述}                         │
│         示例: feat(phase2): 实现 Prometheus 解析器                       │
│     └── 【Task】创建并跟踪开发任务                                       │
│         工具: TaskCreate / TaskUpdate                                   │
│                                                                         │
│  3. Phase 完成后                                                         │
│     └── 编写完整测试脚本                                                 │
│     └── 执行测试 → 确保全部通过                                          │
│     └── 通知用户: "Phase {N} 开发完成，是否进行人工验证？"                │
│                                                                         │
│  4. 用户确认后                                                           │
│     └── 启动项目（后端服务 + 前端）                                      │
│     └── 使用 Playwright MCP 进行 E2E 验证                               │
│         - 验证前端外观与设计稿一致性                                     │
│         - 验证接口响应正确性                                             │
│         - 验证数据展示正确性                                             │
│     └── 发现问题 → 及时调整代码 → 重新验证                               │
│                                                                         │
│  5. E2E 验证通过后                                                       │
│     └── 推送代码到远程分支                                               │
│     └── 创建 Pull Request                                               │
│     └── 【Linear】更新 Issue 状态为 In Review                           │
│         工具: mcp__linear__update_issue(state: "In Review")             │
│     └── 执行 code-review 技能进行评审                                    │
│                                                                         │
│  6. Code Review 结果                                                     │
│     └── 通过 → 合并到 main 分支                                          │
│         └── 【Linear】更新 Issue 状态为 Done                            │
│             工具: mcp__linear__update_issue(state: "Done")              │
│     └── 有问题 → 修复后重新评审                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 分支管理规范

| 分支类型 | 命名规则 | 说明 |
|---------|---------|------|
| 主分支 | `main` | 稳定版本，始终可部署 |
| 功能分支 | `feature/phase{N}-{描述}` | 每个 Phase 一个分支 |
| 修复分支 | `fix/{描述}` | Bug 修复 |

### Commit 规范

```
feat(phase{N}): {功能描述}        # 新功能
fix(phase{N}): {修复描述}        # Bug 修复
test(phase{N}): {测试描述}       # 测试相关
docs(phase{N}): {文档描述}       # 文档更新
refactor(phase{N}): {重构描述}   # 代码重构
```

### E2E 验证清单

使用 Playwright MCP 验证以下内容：

- [ ] 页面加载正常，无白屏或报错
- [ ] 前端外观与设计稿（HTML）一致
- [ ] 导航和路由切换正常
- [ ] 表单提交和交互功能正常
- [ ] API 接口响应正确
- [ ] 数据展示正确（无空数据、格式错误）
- [ ] 错误提示和边界情况处理正常

### Code Review 标准

评审通过条件：

1. 无明显的逻辑错误或 Bug
2. 代码符合 CLAUDE.md 规范
3. 测试覆盖率达标
4. E2E 验证全部通过

### 注意事项

- **增量提交**: 不要等整个 Phase 完成才 commit，每完成一个 Task 就提交
- **测试先行**: Phase 完成后必须先写测试，测试通过才能通知用户
- **用户确认**: 必须等用户确认后才能进行 E2E 验证
- **问题修复**: E2E 发现的问题需立即修复，不要留到后续 Phase
- **Linear 同步**: 状态变更必须及时同步到 Linear，确保 issue 状态与实际进度一致

### Linear Issue 状态查询

```bash
# 查看当前项目所有 issues
mcp__linear__list_issues(project: "GraphRAG")

# 查看当前用户待办
mcp__linear__list_issues(assignee: "me", state: "Backlog")

# 查看进行中的任务
mcp__linear__list_issues(assignee: "me", state: "In Progress")
```
