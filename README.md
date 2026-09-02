# Skill Manager

把 GitHub 上的 Agent Skill 合集，同步到本机各个 AI 编程工具。

Windows 桌面程序，Fluent 界面。本机装了 Claude Code、Cursor、Grok 之后，各自的 `skills` 目录是分开的。这个工具用来统一分发，也能把某个工具里改过的 skill 写回源仓。

## 能干什么

- 检测本机装了哪些 Agent，已安装的默认勾上
- 从 GitHub 拉取或克隆 skill 合集仓
- 勾选 skill 和 Agent，复制到各工具目录（已有则覆盖）
- 对比 Agent 拷贝和源仓的差异
- 从某一个 Agent 写回源仓，然后 `git commit` + `push`

合集仓里每个子目录有 `SKILL.md`（或 `skill.md`）就算一个 skill。

## 支持的 Agent

| 工具 | 目录 |
| --- | --- |
| Claude Code | `~/.claude/skills` |
| Cursor | `~/.cursor/skills` |
| Codex | `~/.codex/skills` |
| Grok | `~/.grok/skills` |
| Qoder | `~/.qoder/skills` |
| Gemini | `~/.gemini/skills` |
| OpenCode | `~/.opencode/skills` |
| Continue | `~/.continue/skills` |
| Windsurf | `~/.codeium/windsurf/skills` |
| Trae | `~/.trae/skills` |

复制到 Claude Code 时会额外写 `.claude-plugin/plugin.json`。没有这个文件，Claude 不会把它当插件加载。

## 环境

- Windows
- Python 3.10+
- Git（「更新」和「写回并上传」都走 git）

```text
pip install -r requirements.txt
```

## 使用

双击 `启动.bat`，或：

```text
python skill_manager.py
```

界面里填 GitHub 地址和本地目录。本地目录指向合集仓根目录，不是某个 skill 自己。

| 按钮 | 行为 |
| --- | --- |
| 更新 | 已是 git 仓就 `pull`；空目录就 `clone` |
| 重新检测 | 再扫一遍本机 Agent 和本地 skill |
| 检查改动 | 对照源仓。`~` 内容不同，`+` Agent 多出来，`-` 源有 Agent 没有 |
| 写回并上传 | Agent → 源仓。只能勾 **一个** Agent，覆盖后 `commit` + `push` |
| 下发到 Agent | 源仓 → Agent，覆盖目标目录 |

配置写在程序旁边的 `skill_manager.json`，不进 git。

## 注意

- 写回会覆盖本地源目录里对应的 skill，确认后再点
- 源目录不是 git 仓库的话，文件能写回，但没法推送
- Claude Code 复制完成后，需要新开会话，或在对话里执行 `/reload-plugins`
- 本地已有内容、且不是 git 仓库时，不要对这个目录点「更新」，换一个空目录
