# Multi-Project Portfolio in Obsidian

**Status:** Draft
**Date:** 2026-04-30
**Predecessors:** `2026-04-27-plan-5b-obsidian-design.md`

## 動機

`projects/` 底下有 14 個項目資料夾。Plan 5b 完成後,cc-assistant 的 Obsidian vault 只服務一個項目(cc-assitant 自己)。其他 13 個項目目前沒有任何看板、沒有狀態紀錄、沒有「回頭翻歷史」的入口。

我們希望 Obsidian 變成「項目組合的記憶 + 控制台」:
- 每個項目都有一張卡,記錄它在做什麼、做到哪、為什麼這樣決定。
- 兩個月後回到某個項目,開卡片就能無縫接回去,不用重讀 git log。
- 透過卡片上的 `status` 欄位告訴 cc-assistant 「這個項目別動了」,即使 todo 還很多。

## 範圍

**In scope**
- 在現有 vault `tasks/` 下新增 `projects/` 資料夾,每個項目一個 .md 卡片。
- 卡片用 frontmatter 表達狀態(active / paused / archived)。
- 任務(`todo/ doing/ ...` 既有檔案)新增 `project:` 欄位,連回項目卡。
- Orchestrator 取 ready task 時,若任務的 project 卡 `status != active`,跳過該任務。
- 一個 bootstrap 命令掃 `projects/` 下的資料夾,為每個還沒有卡的項目產生 stub 卡片。
- 一個 Obsidian Base 視圖,按 `status` 分組顯示項目卡。

**Out of scope (此 spec 不做)**
- 多 vault / per-project sub-vault。Vault 只有一個。
- 移動既有的 `cc-assitant/tasks/` vault 到別的位置。Plan 5b 才剛把 Obsidian Sync 弄通,不動。
- 為其他 13 個項目自動生成大量 task。Bootstrap 只產 project 卡,task 是用戶自己加。
- 跨 repo 的程式碼自動執行(例如 cc-assistant daemon 進到 evernote/ repo 跑命令)。任務的執行細節由任務自己描述,daemon 行為不變。
- 從 git log 自動推斷 `last_touched` 或 progress。第一版手動填。

## 設計

### 檔案佈局

```
tasks/                          # vault root (不變)
├── .obsidian/                  # 不變
├── _attachments/               # 不變
├── templates/                  # 既有
│   ├── default.md              # 既有(task 模板)
│   └── project.md              # 新增(project 卡模板)
├── projects/                   # 新增
│   ├── cc-assitant.md
│   ├── evernote.md
│   ├── alpha-project.md
│   ├── connect-nas.md
│   └── ... (14 個,每個項目一張)
├── todo/                       # 既有
├── doing/                      # 既有
├── blocked/                    # 既有
├── review/                     # 既有
├── done/                       # 既有
├── backlog/                    # 既有
├── views.base                  # 既有(task 看板)
└── projects.base               # 新增(項目看板)
```

### 項目卡 schema (範本 B)

```yaml
---
type: project                   # 區別於 task,讓 daemon 不會誤把它當 task 處理
slug: evernote                  # 必填,等於 repo 資料夾名,任務透過此值連回
status: active                  # active | paused | archived
repo_path: ../../evernote       # 從 vault 算起的相對路徑,可選
priority: P1                    # P0 / P1 / P2,可選
tags: [migration, knowledge]    # 可選
last_touched: 2026-04-30        # 可選,用戶手動更新
---
# evernote

## 一句話
(這個項目要解決什麼問題,一兩句講完。)

## 現在的焦點
(目前正在處理的子問題。)

## 下一步 (Next actions)
- [ ] ...

## 決策記錄
- YYYY-MM-DD: ...

## 待解決的問題
- ...

## 回顧 / 暫停原因
(僅 paused / archived 時填:為什麼停、回來時要先看什麼、避免重蹈覆轍的事。)
```

**為什麼有 `type: project` 欄位**
Vault 既有任務檔有 `intent`、`status`(in folder)、`project_id` 等欄位。新增 `type: project` 是讓 daemon 在做 vault 全掃時(orchestrator、watcher),能 O(1) 區分「這是項目卡還是任務卡」,不靠資料夾路徑判斷,也不會被誤掃進 doing 隊列。

**為什麼 `slug` 必填且要等於資料夾名**
任務的 `project:` 欄位用 slug 連結。等於資料夾名才能讓 cc-assistant 在執行任務時對應到實際 repo 路徑(雖然 daemon 本身目前不跨 repo 執行,但任務內容會引用)。

### Task → Project 連結

任務檔(`todo/foo.md` 等)新增 frontmatter 欄位:

```yaml
project: evernote               # 可選;若空表示 vault 自身的元任務(例如改 cc-assistant 的功能)
```

向後相容:既有任務沒有 `project` 欄位 → 視同 `project: cc-assitant`(預設值)。

### 「不再推進」的執行語意

Orchestrator 在「決定哪個任務從 todo/ 進 doing/」時,新增一道過濾:

```
for task in ready_tasks:
    if task.project is None:
        keep
    else:
        project_card = projects/{task.project}.md
        if project_card.status == "active":
            keep
        else:
            skip (log: "skipped: project paused/archived")
```

`status: paused` 與 `status: archived` 在 daemon 行為上**等價**(都被跳過)。差別只在 UI 視圖上的呈現:
- `paused` 顯示在預設視圖的「暫停中」分組,折疊但可展開。
- `archived` 預設折疊隱藏,要在視圖切換器選「Show archived」才看得到。

### Obsidian Base 視圖 — `projects.base`

按 `status` 分組:
- 🟢 Active(預設展開)
- 🟡 Paused(預設折疊)
- ⚪ Archived(預設隱藏)

每張卡顯示:標題、`priority`、`last_touched`、`tags`。點擊進入詳細頁。

### Bootstrap 命令

```
cc-assistant bootstrap-projects [--projects-root <path>]
```

行為:
1. 預設 `--projects-root` = vault 上一層的上一層(即 `cc-assitant/tasks/` → `cc-assitant/` → `projects/`)。可被覆寫。
2. 列出 `<projects-root>/*/`(所有資料夾)。
3. 對每個資料夾名 `<name>`:
   - 若 `tasks/projects/<name>.md` 已存在 → 跳過。
   - 否則,從 `templates/project.md` 複製,填好 `slug`、`repo_path`、`status: active`、`last_touched: <today>`,內容區留空白讓用戶補。
4. 印出哪些卡是新建、哪些跳過。
5. 不寫進 `cc-assitant.md` 自身,因為 vault 本身就是這個項目,卡會手動建一張更詳細的。

### Daemon 端的程式變動點

| 模組 | 變動 |
|---|---|
| `src/board/manager.py` | 新增方法 `get_project(slug) -> Project` 讀取 projects/{slug}.md |
| `src/parser/...` | 新增 Project model;parser 認得 `type: project` 並回傳 Project 而非 Task |
| `src/orchestrator/...` | 在 ready-task selection 後加一道 project-status 過濾 |
| `src/dispatcher/watcher.py` | `projects/` 變更時觸發狀態快取重整(用於決定是否要把目前 doing/ 的任務 pause 掉) |
| `src/cli.py` | 新增 `bootstrap-projects` subcommand |
| `tasks/templates/` | 新增 `project.md` |
| `tasks/projects.base` | 新增視圖檔(由 Obsidian 產生,git 追蹤) |

### 已在 doing/ 的任務若項目突然被 paused 怎麼辦?

兩個選項:
- **A. 不打擾正在跑的**:已被起出來的 task 跑完。新的 ready task 才檢查 status。
- **B. 立刻撤回**:把那個 task 移回 backlog/(類似 `intent: pause`)。

選 **A**。理由:中斷正在跑的 Claude session 風險高(可能留下半成品檔案、git 狀態不乾淨),Plan 5a 的測試也顯示正在跑的任務有 in_flight lock 保護。pause 是「下次別再啟」的意圖,不是「立刻 kill」。

### 錯誤情境

| 情境 | 行為 |
|---|---|
| 任務的 `project:` 對應的卡片不存在 | log warning,不過濾(任務照跑)。避免 daemon 因 typo 卡死。 |
| 項目卡 `status` 欄位是非預期值(例如打錯字) | 視同 `active`,log warning。 |
| 項目卡 `status` 欄位缺失 | 視同 `active`,不報 warning(新建卡片可能還沒填完整)。 |
| `projects/` 底下的檔案缺 `type: project` 欄位 | parser 仍視為項目卡(用資料夾路徑判定),但 log warning 提示要補欄位。`type: project` 是 daemon 在跨資料夾全掃時的快速分流欄位,不是強制驗證。 |
| `bootstrap-projects` 找不到 `--projects-root` | 報錯退出,不建立任何卡。 |
| 兩張卡 `slug` 重複 | parser 啟動時報錯,要求人工解決。 |
| `cc-assitant` 自身要不要 bootstrap | bootstrap 會跳過 cc-assitant 對應的那張卡(vault 自身的 meta 卡由用戶手動寫,內容比 stub 詳細)。其餘 13 個項目都建。 |

## 測試

- Unit: `Project` parser 認 frontmatter,容錯 status 拼錯。
- Unit: orchestrator 過濾邏輯—— ready task 列表中,paused project 的 task 被剔除,沒 `project:` 的不受影響。
- Integration: bootstrap 命令對著 fixture projects-root 跑,產生預期的 stub 卡。
- Integration: 把 `evernote.md` 從 active 改 paused,既有 doing/ 中的 evernote 任務不受影響;todo/ 中的 evernote 任務不會被升 doing。

## 遷移

- 既有所有任務都沒有 `project:` 欄位 → 預設視同 `project: cc-assitant`,行為不變。
- 用戶第一次跑 `bootstrap-projects` 後,projects/ 多 14 張 stub 卡。一張一張慢慢補正文。
- 不需要寫 migration 腳本,既有資料零改動。

## 開放問題

無。所有設計決策都在 brainstorm 階段確定:
- 單 vault(不分 sub-vault):確認。
- 模板 B(中等):確認。
- frontmatter 控制(不用資料夾):確認。
- paused 不打斷正在跑的任務:本 spec 確定。
