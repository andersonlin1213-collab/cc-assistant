# 手机端 Obsidian 触发股票深度分析 — 设计文档

**日期**: 2026-05-04
**状态**: 已批准（用户 5/4 凌晨睡前批 OK）
**作者**: claude (sonnet/opus 协作)
**关联**: cc-assitant daemon, StockAnalysis/buffett-oracle-analyzer skill

---

## 背景

用户已有完整基建：

- **cc-assitant daemon** (5/2-5/3 dogfood 完成稳定): Obsidian-as-UI 任务流，watcher 监 `tasks/todo/`，零 frontmatter，文件名当 title，自动派单给 `claude_cli` provider 跑（烧 Max 订阅）。
- **buffett-oracle-analyzer skill** (StockAnalysis 项目下): 12 模块深度分析，已用小米 1810.HK 完成首例报告，归档到 `<personal-vault>\analysis\`。
- **个人 Obsidian Vault**: analysis的浏览端。

缺的只是把这些组件用极少的代码缝上：让用户在手机上写 `分析-小米.md` 就能 5-15 分钟内拿到完整深度报告。

---

## 目标

1. 用户在手机 Obsidian (cc-assitant vault) 创建 `tasks/todo/分析-{股票}.md` (内容空白即可)
2. 系统自动跑完 12 模块分析
3. 报告自动出现在 `<personal-vault>\analysis\` (主) + `analysis\历史\` (归档)
4. 用户可在 cc-assitant `tasks/doing/` 该任务卡里追问 / 调参

## 非目标

- ❌ 不做股价告警 / 持仓追踪 / 定时复盘
- ❌ 不动 cc-assitant daemon 代码
- ❌ 不做"已分析股票"看板自动维护
- ❌ 不做歧义 ticker 的交互式消歧（默认选最知名，不行用户改文件名重跑）

---

## 架构

```
[手机 Obsidian — cc-assitant vault]
  新建 tasks/todo/分析-小米.md (空)
        ↓ Obsidian Sync (秒级)
[cc-assitant daemon (PC 持续运行)]
  watcher 检测 → todo→doing → 派单 claude_cli
        ↓
[Claude CLI subprocess]
  从 ~/.claude/skills/ 加载 buffett-oracle-analyzer
  task title "分析-小米" 命中 skill description
        ↓
[buffett-oracle-analyzer 跑 12 模块]
  WebSearch 拉数据 (10-15 min)
  生成报告 markdown
        ↓
[Skill 自动化模式 写两份报告]
  主: <personal-vault>\analysis\{中文名}-{代码}-深度分析.md (覆盖)
  档: <personal-vault>\analysis\历史\{中文名}-{代码}-{YYYY-MM-DD-HHMM}.md (新增)
        ↓
[doing/分析-小米.md 自动追加]
  ## 对话 节里: 简短摘要 (评级/目标价/3 句结论) + 报告路径链接
  daemon 加 placeholder "[我] *(在这里写下一条…)*"
        ↓
[用户后续]
  - 手机看主报告 (个人 vault 里方便浏览)
  - 回 doing/ 追问 (例如 "70 万辆乐观情景再算一次")
```

---

## 组件 & 改动

| 组件 | 改动 | 工作量 |
|------|------|--------|
| `cc-assitant` daemon | **0 行代码** — 复用 todo-folder-implies-task + claude_cli | — |
| `buffett-oracle-analyzer/SKILL.md` | 新增 `## 自动化输出模式` 章节 | 1 段 |
| `~/.claude/skills/buffett-oracle-analyzer/` | 新建 — 整目录从 StockAnalysis 复制过来 | 1 命令 |
| `<personal-vault>\analysis\历史\` | 新建空目录 + .gitkeep 占位 | 1 命令 |
| `~/.claude/projects/.../memory/feedback_obsidian_stock_reports.md` | 加自动化路径条款 | 1 段 |
| `cc-assitant/tasks/projects/StockAnalysis.md` | 状态卡刷新 + 添加 dogfood 任务 | 1 次更新 |

**总计**: 文件改动 5 处，0 行 daemon 代码。

---

## 数据流细节

### 1. 触发约定 (输入)

- **位置**: `cc-assitant\tasks\todo\`
- **文件名格式**: `分析-{识别符}.md`
  - 识别符可以是: 中文公司名 (`小米`)、股票代码 (`1810.HK` / `AAPL`)、英文名 (`Xiaomi`)
  - 前缀必须是 `分析-` (skill 触发可靠 + 与 cc-assitant 普通任务区分)
- **内容**: 可空，可加自由备注（如"重点看汽车业务"）

### 2. 报告输出 (skill 自动化模式)

skill 在跑完 12 模块后必须执行：

1. **主报告**: `Write` 到 `<personal-vault>\analysis\{中文名}-{代码}-深度分析.md`
   - 同名文件存在则覆盖
   - 文件名沿用 cases/ 里现有约定: `{中文公司名}-{交易代码}-深度分析.md` (如 `小米集团-1810.HK-深度分析.md`)

2. **归档**: `Write` 到 `<personal-vault>\analysis\历史\{中文名}-{代码}-{YYYY-MM-DD-HHMM}.md`
   - 时分到分钟级 (防同日反复跑覆盖)
   - 内容与主报告相同

3. **不写** `cases/analysis-reports/` —— 那是 skill 维护者手动添加的示例库，不接自动化

### 3. 对话回写 (cc-assitant doing 流)

skill 在最后向 Claude CLI 输出（最终回 doing/ 文件）：

```
✅ 分析完成

**评级**: 持有偏买入 (B 级 25/36)
**目标价**: 基准 45 HKD / 乐观 58 / 悲观 28
**核心结论**: <3 句话>

📄 完整报告: [[analysis/小米集团-1810.HK-深度分析]]
📦 归档: analysis/历史/小米集团-1810.HK-2026-05-04-1530.md
```

doing/ 文件其余按 cc-assitant 标准流程 (placeholder 追加，便于追问)。

---

## 边界情况

| 情况 | 处理 |
|------|------|
| 公司名歧义 (`分析-苹果`) | skill 默认选最知名 (AAPL > 0683.HK 苹果日报)，报告开头注明"如需另一支同名股票，请重写文件名为 `分析-0683.HK`" |
| Ticker 不存在 / 数据源全挂 | skill 在 doing/ 对话里说明失败原因 + 建议；daemon placeholder 让用户重试 |
| 同日反复分析 | 主报告覆盖 OK；归档文件名带时分防覆盖 |
| 用户在 doing/ 追问 | 走 cc-assitant 标准 placeholder UX，skill 可重新跑部分模块 (如只更新估值) 或 freeform 回答 |
| 网速慢 / WebSearch 超时 | skill 内置容错；daemon 的 LLM 失败 placeholder 兜底 |

---

## 测试 / 验收

### 冒烟测试 (用户睡醒第一件事)

1. 手机 Obsidian → cc-assitant vault → `tasks/todo/` 新建 `分析-比亚迪.md`
2. 等 5-15 分钟
3. **预期**:
   - `<personal-vault>\analysis\比亚迪-1211.HK-深度分析.md` 存在 (或 `002594.SZ`)
   - `<personal-vault>\analysis\历史\` 下有时戳归档
   - cc-assitant `tasks/doing/分析-比亚迪.md` 里 `## 对话` 节有简短摘要 + 报告链接
4. 在 doing/ 里追问"如果 2026 全年 600 万辆，目标价怎么变"，验证 placeholder 流正常

### 失败兜底验证

- 故意建 `分析-XXXFAKETICKER.md` —— skill 应在 doing/ 里说"找不到这个标的"，不是静默挂掉

---

## Rollout

无灰度，单用户场景。一次性安装 + dogfood 即上线。

---

## 后续工作 (Out of scope)

- 已分析股票 watchlist 自动维护 (手动维护 `analysis/index.md` 即可)
- 定时复盘 (每季度财报后自动重跑) — 用 cron skill 实现，留待后续
- 股价告警 / 持仓追踪
- 多模型估值的可视化图表 (现在是 markdown 表，未来可加 Chart.js)
- 跨股票对比报告 (`分析-小米-vs-苹果.md`)

---

## 风险

| 风险 | 缓解 |
|------|------|
| Claude CLI 子进程不会自动加载 ~/.claude/skills | 已验证：其他全局 skill (agent-reach 等) 都从这里加载 |
| skill 误判触发 (cc-assitant 普通任务被当成股票分析) | `分析-` 前缀约定 + skill description 限定为公司/股票/投资 |
| WebSearch 拿不到中国 A 股的实时财务数据 | 备用 WebFetch <source-A>/<source-B> |
| 用户文件名乱写 (`bydddd.md` 漏 `分析-` 前缀) | 退化为普通 cc-assitant 任务，Claude 会问澄清，不会静默失败 |
| 手机 Obsidian Sync 延迟过长 | 用户已经接受 cc-assitant 这点延迟 |

---

## 决策记录

- 输入 vault 选 cc-assitant 而非个人 vault: 0 daemon 代码改动 > 单 vault UX 便利
- 文件名前缀选 `分析-`: 触发可靠 vs 多打 3 字成本极低
- 历史归档选 latest+archive 模式: analysis的复盘价值需要历史，但日常浏览不被噪音淹没
- skill 输出绕过 cases/: 那是手动示例库，自动化路径只写 vault
