---
name: skill-updater
description: |
  Skill 更新管理器——检查并更新所有来自第三方开发者的 skill 和 plugin，管理自建 skill 同步。
  当用户说"检查更新"、"更新所有 skill"、"升级插件"、"看看有没有新版本"、"同步市场插件"、"更新第三方skill"、"同步我的skill"、"同步到hallow"时，必须使用此 skill。
  也适用于用户想了解当前已安装 skill/plugin 的来源和版本状态时，或者要新增一个 GitHub 开源 skill 的跟踪时。
  注意：此 skill 将 skill 分类为：Anthropic 官方、第三方插件管理、第三方 GitHub 源、第三方直接安装、自己的 skill、来源未知。
---

# Skill Updater

## Overview

该 skill 用于管理 Claude Code 的 skill 生态，支持三大功能：

1. **检查与更新** — 扫描所有 skill 和 plugin，识别第三方来源，检查更新
2. **来源发现** — 在 skillsmp.com 上搜索未知来源的 skill，找到 GitHub 仓库
3. **自建 skill 同步** — 将自己的 skill 同步到 `D:\MuyiSong\Project\hallow-skills\`，更新 README，SVN commit

---

## 数据文件

所有第三方 GitHub 来源和自建 skill 的配置存储在：
```
~/.claude/skills/skill-updater/known-sources.json
```

可直接编辑此文件或通过命令管理。

---

## Phase 1: 扫描与分类

```bash
python ~/.claude/skills/skill-updater/scripts/check-updates.py inventory
```

输出分类结果，共 6 类：

| 分类 | 含义 | 处理方式 |
|------|------|---------|
| `first_party` | Anthropic 官方 | 跳过 |
| `third_party_managed` | 第三方插件管理（如 superpowers） | 通过插件系统更新 |
| `third_party_github` | 第三方 GitHub 开源（在 known-sources.json 中配置） | 从 GitHub 克隆更新 |
| `third_party_direct` | 第三方直接安装（来自 marketplace 但未管理） | 检查 marketplace 源 |
| `own` | 自己的 skill（在 known-sources.json 中标记） | 同步到 hallow-skills |
| `unknown` | 来源未知 | 进入 skillsmp.com 查找流程 |

---

## Phase 2: 处理未知来源（skillsmp.com 查找）

对 `unknown` 类别的 skill，进行以下操作：

### 步骤 1：生成搜索信息

```bash
python ~/.claude/skills/skill-updater/scripts/check-updates.py lookup-skillsmp <skill-name>
```

这会输出 skillsmp.com 搜索策略（搜索 URL 和搜索关键词）。

### 步骤 2：Claude 执行搜索

用 WebSearch 搜索：
```
site:skillsmp.com "<skill-name>"
```

或用 WebFetch 访问：
```
https://skillsmp.com/skills?q=<skill-name>
```

### 步骤 3：提取 GitHub 地址

从 skillsmp.com 页面中找到该 skill 的 GitHub 仓库地址（通常在页面的 "Source" 或 "Repository" 部分）。

### 步骤 4：添加到 known-sources

找到 GitHub 地址后，添加到 known-sources.json：

```bash
# 如果 skill 在仓库根目录：
python ~/.claude/skills/skill-updater/scripts/check-updates.py add-source <skill-name> <github-url>

# 如果 skill 在仓库的子目录中（常见于 monorepo）：
python ~/.claude/skills/skill-updater/scripts/check-updates.py add-source <skill-name> <github-url> "path/to/skill"
```

如果 skillsmp.com 也没找到，向用户报告并询问如何处理。

---

## Phase 3: 检查可用更新

### 检查插件管理的更新（如 superpowers）

```bash
python ~/.claude/skills/skill-updater/scripts/check-updates.py check-all
```

### 检查 GitHub 源的更新

GitHub 源的更新通过查看仓库的最新 commit 确定：
```bash
python ~/.claude/skills/skill-updater/scripts/check-updates.py check <skill-name>
```

### 向用户展示

呈现更新报告，格式示例：

```
📦 可用更新：
  • superpowers: 5.0.6 → 5.1.0（来自 marketplace）
  • doc-coauthoring: 有新 commit（来自 GitHub）

✅ 已是最新：
  • github
  • tailored-resume-generator
```

等待用户确认后再执行更新。默认建议全部更新。

---

## Phase 4: 执行更新

### 更新插件管理的 skill

```bash
# 先 dry-run 预览
python ~/.claude/skills/skill-updater/scripts/check-updates.py update superpowers --dry-run

# 确认后执行
python ~/.claude/skills/skill-updater/scripts/check-updates.py update superpowers
```

### 更新 GitHub 源的 skill

```bash
# 先 dry-run
python ~/.claude/skills/skill-updater/scripts/check-updates.py update-github doc-coauthoring --dry-run

# 确认后执行
python ~/.claude/skills/skill-updater/scripts/check-updates.py update-github doc-coauthoring
```

GitHub 更新流程：
1. `git clone --depth 1 <url> <临时目录>`
2. 从仓库中提取 skill 文件
3. 备份旧版本到 `~/.claude/skills/skill-updater/backups/<name>-<timestamp>/`
4. 替换为新版本

### 更新 marketplace 直接安装的 skill（如 github）

如果在 marketplace 中找到了源信息，同样用 `update` 命令处理。

---

## Phase 5: 同步自建 Skill 到 hallow-skills

当用户创建新 skill 或修改已有 skill 后，或者明确要求同步时执行。

### 标记自己的 skill

新创建的 skill 需要先标记为"自己的"：

```bash
python ~/.claude/skills/skill-updater/scripts/check-updates.py add-own <skill-name>
```

也可以直接编辑 `known-sources.json` 的 `own_skills` 数组。

### 执行同步

```bash
# 先 dry-run 预览
python ~/.claude/skills/skill-updater/scripts/check-updates.py sync-hallow --dry-run

# 确认后执行
python ~/.claude/skills/skill-updater/scripts/check-updates.py sync-hallow
```

同步流程：
1. 将 `own_skills` 中每个 skill 从 `~/.claude/skills/<name>/` 复制到 `D:\MuyiSong\Project\hallow-skills\claude\<name>\`
2. 更新 `D:\MuyiSong\Project\hallow-skills\README.md`，自动生成技能列表
3. 在 hallow-skills 目录下执行 `git add` + `git commit`

---

## Phase 6: 总结报告

所有操作完成后，输出完整的总结报告：

```
========= 更新完成 =========

📦 已更新:
  ✓ superpowers: 5.0.6 → 5.1.0

✅ 已是最新:
  - github
  - doc-coauthoring
  - tailored-resume-generator

🔄 已同步到 hallow-skills:
  ✓ agent-the-chariot
  ✓ agent-the-hierophant
  ✓ agent-the-star
  ✓ README.md 已更新
  ✓ Git committed

⏭ 跳过（Anthropic 官方）:
  - frontend-design, skill-creator, xlsx ...
```

---

## 命令参考

| 命令 | 用途 |
|------|------|
| `inventory` | 完整分类清单 |
| `check-all` | 检查所有第三方插件更新 |
| `check <name>` | 检查特定项目更新 |
| `update <name> [--dry-run]` | 更新插件或 GitHub skill |
| `lookup-skillsmp <name>` | 生成 skillsmp.com 搜索策略 |
| `add-source <name> <url> [path]` | 添加 GitHub 来源 |
| `add-own <name>` | 标记为自己的 skill |
| `sync-hallow [--dry-run]` | 同步自己的 skill 到 hallow-skills |
| `update-github <name> [--dry-run]` | 从 GitHub 源更新 |

## 已知来源（known-sources.json）

```json
{
  "third_party_github": {
    "doc-coauthoring": {
      "url": "https://github.com/anthropics/skills.git",
      "path": "skills/doc-coauthoring",
      "type": "git-subdir"
    }
  },
  "own_skills": ["agent-the-chariot", "..."],
  "hallow_sync": {
    "target_dir": "D:\\MuyiSong\\Project\\hallow-skills",
    "claude_subdir": "claude"
  }
}
```

## 安全策略

1. **先 dry-run，再执行**：所有更新操作都先用 `--dry-run` 预览
2. **用户确认**：每次更新必须得到用户明确同意
3. **自动备份**：GitHub 更新前自动备份旧版本
4. **失败恢复**：更新失败时保留备份，报告错误信息
