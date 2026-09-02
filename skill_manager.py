# -*- coding: utf-8 -*-
"""Skill Manager：检测本机 Agent，把 GitHub 合集仓里的 skill 拷到各工具目录。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

HOME = Path.home()
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "skill_manager.json"

DEFAULT_GITHUB = "https://github.com/deermiya/skills.git"
DEFAULT_LOCAL = Path(r"D:\AI\SKILLs\skills")

AGENTS = [
    ("Claude Code", HOME / ".claude", HOME / ".claude" / "skills"),
    ("Cursor", HOME / ".cursor", HOME / ".cursor" / "skills"),
    ("Codex", HOME / ".codex", HOME / ".codex" / "skills"),
    ("Grok", HOME / ".grok", HOME / ".grok" / "skills"),
    ("Qoder", HOME / ".qoder", HOME / ".qoder" / "skills"),
    ("Gemini", HOME / ".gemini", HOME / ".gemini" / "skills"),
    ("OpenCode", HOME / ".opencode", HOME / ".opencode" / "skills"),
    ("Continue", HOME / ".continue", HOME / ".continue" / "skills"),
    ("Windsurf", HOME / ".codeium" / "windsurf", HOME / ".codeium" / "windsurf" / "skills"),
    ("Trae", HOME / ".trae", HOME / ".trae" / "skills"),
]

IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store")
BACK_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store", ".claude-plugin")
SKIP_DIRS = {".git", "__pycache__", ".claude-plugin"}
SKIP_FILES = {".ds_store"}


def is_skill_dir(path: Path) -> bool:
    return path.is_dir() and (
        (path / "SKILL.md").is_file() or (path / "skill.md").is_file()
    )


def list_skills(source: Path) -> list[Path]:
    if not source.is_dir():
        return []
    skills = [p for p in source.iterdir() if is_skill_dir(p)]
    return sorted(skills, key=lambda p: p.name.lower())


def git_run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )


def git_out(r: subprocess.CompletedProcess[str]) -> str:
    return ((r.stdout or "") + (r.stderr or "")).strip()


def git_commit_push(repo: Path, paths: list[str], message: str) -> str:
    if not (repo / ".git").exists():
        raise RuntimeError("源目录不是 git 仓库，文件已写回，但无法提交推送")
    add = git_run(["add", "--", *paths], cwd=repo)
    if add.returncode != 0:
        raise RuntimeError(git_out(add) or "git add 失败")
    staged = git_run(["diff", "--cached", "--quiet"], cwd=repo)
    if staged.returncode == 0:
        return "工作区没有新变化，跳过提交和推送"
    commit = git_run(["commit", "-m", message], cwd=repo)
    if commit.returncode != 0:
        raise RuntimeError(git_out(commit) or "git commit 失败")
    push = git_run(["push"], cwd=repo)
    if push.returncode != 0:
        raise RuntimeError(
            "已提交到本地，但推送失败：\n" + (git_out(push) or "git push 失败")
        )
    lines = [git_out(commit), git_out(push)]
    return "\n".join(x for x in lines if x)


def load_config() -> dict:
    data = {
        "github_url": DEFAULT_GITHUB,
        "local_source": str(DEFAULT_LOCAL if DEFAULT_LOCAL.is_dir() else APP_DIR / "skills-cache"),
    }
    if CONFIG_PATH.is_file():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            data.update({k: v for k, v in saved.items() if k in data})
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def actual_skill_md(folder: Path) -> Path | None:
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if name.lower() == "skill.md":
            return folder / name
    return None


def normalize_skill_md(dest: Path) -> None:
    found = actual_skill_md(dest)
    if found is None or found.name == "SKILL.md":
        return
    # Windows 大小写不敏感，skill.md 和 SKILL.md 是同一个文件，必须绕一跳改名
    tmp = dest / (found.name + ".rename-tmp")
    found.rename(tmp)
    tmp.rename(dest / "SKILL.md")


def write_claude_plugin(dest: Path) -> None:
    """Claude Code 把 ~/.claude/skills 当插件目录，必须有 plugin.json 才会加载。"""
    normalize_skill_md(dest)
    md = dest / "SKILL.md"
    description = dest.name
    if md.is_file():
        fm = parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        if fm.get("description"):
            description = fm["description"]
    plugin_dir = dest / ".claude-plugin"
    plugin_dir.mkdir(exist_ok=True)
    manifest = {
        "$schema": "https://anthropic.com/claude-code/plugin.schema.json",
        "name": dest.name,
        "version": "0.1.0",
        "description": description,
        "skills": ["./"],
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_skill(src: Path, dest: Path, agent: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=IGNORE)
    if agent == "Claude Code":
        write_claude_plugin(dest)
    else:
        normalize_skill_md(dest)


def iter_skill_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    if not root.is_dir():
        return files
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.lower() in SKIP_FILES or name.lower().endswith(".pyc"):
                continue
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            files[rel.lower()] = full
    return files


def diff_skill(src: Path, dest: Path) -> list[str]:
    if not dest.is_dir():
        return ["未部署"]
    left = iter_skill_files(src)
    right = iter_skill_files(dest)
    changes: list[str] = []
    for key in sorted(set(left) | set(right)):
        if key not in right:
            changes.append(f"- {left[key].relative_to(src).as_posix()}")
        elif key not in left:
            changes.append(f"+ {right[key].relative_to(dest).as_posix()}")
        else:
            try:
                if left[key].read_bytes() != right[key].read_bytes():
                    changes.append(f"~ {right[key].relative_to(dest).as_posix()}")
            except OSError as e:
                changes.append(f"! {key}: {e}")
    return changes


def is_real_change(changes: list[str]) -> bool:
    return bool(changes) and changes != ["未部署"]


def copy_back(agent_copy: Path, source: Path) -> None:
    if not agent_copy.is_dir():
        raise FileNotFoundError(f"Agent 里没有这个 skill：{agent_copy}")
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(agent_copy, source, ignore=BACK_IGNORE)


def _boot_error(msg: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, msg, "Skill Manager", 0x10)
    except Exception:
        sys.stderr.write(msg + "\n")
    sys.exit(1)


try:
    from PySide6.QtCore import QLocale, QObject, Qt, Signal
    from PySide6.QtGui import QColor, QFont
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QFileDialog,
        QHBoxLayout,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
    from qfluentwidgets import (
        Action,
        BodyLabel,
        CaptionLabel,
        CheckBox,
        CommandBar,
        FluentIcon as FIF,
        FluentTranslator,
        FluentWidget,
        IndeterminateProgressBar,
        InfoBadge,
        InfoBar,
        InfoBarPosition,
        InfoLevel,
        LineEdit,
        MessageBox,
        MessageBoxBase,
        PushButton,
        ScrollArea,
        StrongBodyLabel,
        SubtitleLabel,
        TextEdit,
        Theme,
        TitleLabel,
        TransparentPushButton,
        setFont,
        setFontFamilies,
        setTheme,
    )
except ImportError:
    _boot_error("缺少依赖，请先安装：\npip install PySide6 PySide6-Fluent-Widgets")


class AppSignals(QObject):
    log = Signal(str)
    alert = Signal(str, str)
    toast_warn = Signal(str, str)
    toast_ok = Signal(str, str)
    finish_check = Signal(object)
    done_refresh = Signal()
    done_refresh_keep = Signal()


class CommitDialog(MessageBoxBase):
    def __init__(self, default_msg: str, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("提交说明", self)
        self.hintLabel = BodyLabel("将提交并推送到 GitHub：", self)
        self.line = LineEdit(self)
        self.line.setText(default_msg)
        self.line.setClearButtonEnabled(True)
        self.line.setPlaceholderText("commit message")
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.hintLabel)
        self.viewLayout.addWidget(self.line)
        self.yesButton.setText("提交并推送")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(520)

    def message(self) -> str:
        return self.line.text().strip()


def _badge(text: str, level: InfoLevel, parent: QWidget) -> InfoBadge:
    badge = InfoBadge(text, parent, level)
    badge.adjustSize()
    return badge


class CheckRow(QWidget):
    def __init__(
        self,
        key: str,
        title: str,
        badges: list[tuple[str, InfoLevel]],
        checked: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.key = key
        self.box = CheckBox(title, self)
        self.box.setChecked(checked)
        self.box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(8)
        lay.addWidget(self.box, 1)
        for text, level in badges:
            lay.addWidget(_badge(text, level, self), 0)
        self.setMinimumHeight(34)


class CheckList(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 0)
        self.select_all = TransparentPushButton("全选", self)
        self.select_none = TransparentPushButton("全不选", self)
        head.addWidget(StrongBodyLabel(title, self))
        head.addStretch(1)
        head.addWidget(self.select_all)
        head.addWidget(self.select_none)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.enableTransparentBackground()
        self.inner = QWidget()
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(0, 4, 0, 8)
        self.inner_layout.setSpacing(0)
        self.scroll.setWidget(self.inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addLayout(head)
        root.addWidget(self.scroll)
        self.rows: dict[str, CheckRow] = {}
        self.select_all.clicked.connect(lambda: self.set_all(True))
        self.select_none.clicked.connect(lambda: self.set_all(False))

    def set_items(self, items: list[tuple[str, str, bool, list[tuple[str, InfoLevel]]]]):
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.rows.clear()
        for key, title, checked, badges in items:
            row = CheckRow(key, title, badges, checked, self.inner)
            self.inner_layout.addWidget(row)
            self.rows[key] = row
        self.inner_layout.addStretch(1)

    def selected(self) -> list[str]:
        return [k for k, r in self.rows.items() if r.box.isChecked()]

    def set_all(self, value: bool):
        for r in self.rows.values():
            r.box.setChecked(value)

    def snapshot(self) -> dict[str, bool]:
        return {k: r.box.isChecked() for k, r in self.rows.items()}


class App(FluentWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Skill Manager")
        self.setWindowIcon(FIF.ROBOT.icon())
        self.resize(1020, 740)
        self.setMinimumSize(880, 600)
        self.cfg = load_config()
        self.busy = False
        self.dirty: dict[str, dict[str, list[str]]] = {}
        self.sig = AppSignals()
        self.sig.log.connect(self.log_line)
        self.sig.alert.connect(self._alert)
        self.sig.toast_warn.connect(self._toast_warn)
        self.sig.toast_ok.connect(self._toast_ok)
        self.sig.finish_check.connect(self._finish_check)
        self.sig.done_refresh.connect(self._done_refresh)
        self.sig.done_refresh_keep.connect(self._done_refresh_keep)
        self._build()
        self.refresh()

    def _build(self):
        self.body = QWidget(self)
        root = QVBoxLayout(self.body)
        root.setContentsMargins(36, 16, 36, 20)
        root.setSpacing(16)

        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(TitleLabel("Skill Manager", self.body))
        self.status_label = CaptionLabel("Agent 0/0  ·  Skill 0", self.body)
        self.status_label.setTextColor(QColor(96, 96, 96), QColor(206, 206, 206))
        head.addWidget(self.status_label)
        root.addLayout(head)

        self.act_pull = Action(FIF.SYNC, "更新", self)
        self.act_refresh = Action(FIF.SEARCH, "重新检测", self)
        self.act_check = Action(FIF.VIEW, "检查改动", self)
        self.act_writeback = Action(FIF.CLOUD, "写回并上传", self)
        self.act_copy = Action(FIF.COPY, "下发到 Agent", self)
        self.act_pull.triggered.connect(self.on_pull)
        self.act_refresh.triggered.connect(lambda *_: self.refresh())
        self.act_check.triggered.connect(self.on_check)
        self.act_writeback.triggered.connect(self.on_writeback)
        self.act_copy.triggered.connect(self.on_copy)

        bar = CommandBar(self.body)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.addAction(self.act_pull)
        bar.addAction(self.act_refresh)
        bar.addSeparator()
        bar.addAction(self.act_check)
        bar.addSeparator()
        bar.addAction(self.act_writeback)
        bar.addAction(self.act_copy)
        root.addWidget(bar)

        self.busy_bar = IndeterminateProgressBar(self.body, start=False)
        self.busy_bar.setVisible(False)
        root.addWidget(self.busy_bar)

        self.github_edit = LineEdit(self.body)
        self.github_edit.setText(self.cfg["github_url"])
        self.github_edit.setClearButtonEnabled(True)
        self.github_edit.setPlaceholderText("https://github.com/user/skills.git")
        self.local_edit = LineEdit(self.body)
        self.local_edit.setText(self.cfg["local_source"])
        self.local_edit.setClearButtonEnabled(True)
        self.local_edit.setPlaceholderText("本地 skill 合集目录")
        self.browse_btn = PushButton(FIF.FOLDER, "浏览", self.body)
        self.browse_btn.clicked.connect(self.on_browse)
        root.addWidget(self._field_row("GitHub", self.github_edit))
        root.addWidget(self._field_row("本地", self.local_edit, self.browse_btn))

        lists = QHBoxLayout()
        lists.setSpacing(24)
        self.agent_list = CheckList("Agent", self.body)
        self.skill_list = CheckList("Skills", self.body)
        lists.addWidget(self.agent_list, 1)
        lists.addWidget(self.skill_list, 1)
        root.addLayout(lists, 1)

        root.addWidget(StrongBodyLabel("日志", self.body))
        self.log = TextEdit(self.body)
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        self.log.setMaximumHeight(160)
        setFont(self.log, 12)
        font = self.log.font()
        font.setFamilies(["Consolas", "Cascadia Mono", "Microsoft YaHei UI"])
        font.setPixelSize(12)
        self.log.setFont(font)
        root.addWidget(self.log)

        self._busy_actions = [
            self.act_pull,
            self.act_refresh,
            self.act_check,
            self.act_writeback,
            self.act_copy,
        ]
        self._busy_widgets = [
            self.browse_btn,
            self.github_edit,
            self.local_edit,
        ]
        self.titleBar.raise_()
        self._layout_body()

    def _field_row(self, name: str, *widgets: QWidget) -> QWidget:
        w = QWidget(self.body)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lab = BodyLabel(name, w)
        lab.setFixedWidth(52)
        lay.addWidget(lab)
        for i, widget in enumerate(widgets):
            lay.addWidget(widget, 1 if i == 0 else 0)
        return w

    def _layout_body(self):
        body = getattr(self, "body", None)
        if body is None:
            return
        top = self.titleBar.height() if getattr(self, "titleBar", None) else 0
        body.setGeometry(0, top, self.width(), max(0, self.height() - top))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_body()

    def set_busy(self, busy: bool):
        self.busy = busy
        for act in self._busy_actions:
            act.setEnabled(not busy)
        for w in self._busy_widgets:
            w.setEnabled(not busy)
        self.busy_bar.setVisible(busy)
        if busy:
            self.busy_bar.start()
        else:
            self.busy_bar.stop()

    def log_line(self, msg: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {msg}")

    def _toast_warn(self, title: str, content: str):
        InfoBar.warning(title, content, parent=self.body, duration=2800, position=InfoBarPosition.TOP)

    def _toast_ok(self, title: str, content: str):
        InfoBar.success(title, content, parent=self.body, duration=2800, position=InfoBarPosition.TOP)

    def _alert(self, title: str, content: str):
        box = MessageBox(title, content, self)
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

    def _confirm(self, title: str, content: str) -> bool:
        box = MessageBox(title, content, self)
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        return box.exec() == QDialog.DialogCode.Accepted

    def persist(self):
        self.cfg["github_url"] = self.github_edit.text().strip()
        self.cfg["local_source"] = self.local_edit.text().strip()
        save_config(self.cfg)

    def source(self) -> Path:
        return Path(self.local_edit.text().strip())

    def refresh(self, keep: bool = False, quiet: bool = False):
        source = self.source()
        skills = list_skills(source)
        skill_prev = self.skill_list.snapshot() if keep else {}
        agent_prev = self.agent_list.snapshot() if keep else {}

        skill_items = []
        for p in skills:
            dirty_agents = [
                agent
                for agent, changes in self.dirty.get(p.name, {}).items()
                if is_real_change(changes)
            ]
            badges: list[tuple[str, InfoLevel]] = []
            if dirty_agents:
                if len(dirty_agents) <= 2:
                    badges.append((f"已改: {', '.join(dirty_agents)}", InfoLevel.WARNING))
                else:
                    badges.append((f"已改 {len(dirty_agents)}", InfoLevel.WARNING))
            checked = skill_prev.get(p.name, True)
            skill_items.append((p.name, p.name, checked, badges))
        self.skill_list.set_items(skill_items)

        items = []
        detected = 0
        dirty_count: dict[str, int] = {}
        for skill_map in self.dirty.values():
            for agent, changes in skill_map.items():
                if is_real_change(changes):
                    dirty_count[agent] = dirty_count.get(agent, 0) + 1
        for name, home, skills_dir in AGENTS:
            installed = home.is_dir()
            if installed:
                detected += 1
            have = 0
            if skills_dir.is_dir():
                have = sum(1 for s in skills if (skills_dir / s.name).is_dir())
            badges = []
            if installed:
                badges.append(("已安装", InfoLevel.SUCCESS))
            else:
                badges.append(("未检测到", InfoLevel.INFOAMTION))
            if skills:
                badges.append((f"已有 {have}/{len(skills)}", InfoLevel.ATTENTION))
            n_dirty = dirty_count.get(name, 0)
            if n_dirty:
                badges.append((f"已改 {n_dirty}", InfoLevel.WARNING))
            checked = agent_prev.get(name, installed) if keep else installed
            items.append((name, name, checked, badges))
        self.agent_list.set_items(items)
        self.status_label.setText(f"Agent {detected}/{len(AGENTS)}  ·  Skill {len(skills)}")
        if quiet:
            return
        self.log_line(f"检测完成：Agent {detected}/{len(AGENTS)}，Skill {len(skills)} 个")
        if not source.is_dir():
            self.log_line(f"本地目录不存在：{source}")
        elif not skills:
            self.log_line("本地目录里没有 SKILL.md，先点 GitHub 旁的「更新」")

    def on_browse(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择本地目录", self.local_edit.text() or str(HOME)
        )
        if path:
            self.local_edit.setText(path)
            self.persist()
            self.refresh()

    def _guard(self) -> bool:
        if self.busy:
            self._toast_warn("请稍候", "正在执行上一个任务")
            return False
        return True

    def on_pull(self):
        if not self._guard():
            return
        self.persist()
        url = self.github_edit.text().strip()
        local = self.source()
        if not url:
            self._toast_warn("缺少地址", "请填写 GitHub 地址")
            return
        self.set_busy(True)
        self.log_line(f"开始更新：{url}")

        def work():
            try:
                if local.is_dir() and (local / ".git").exists():
                    r = git_run(["pull"], cwd=local)
                    out = (r.stdout or "") + (r.stderr or "")
                    ok = r.returncode == 0
                    self.sig.log.emit(out.strip() or ("git pull 完成" if ok else "git pull 失败"))
                    if not ok:
                        raise RuntimeError(out.strip() or "git pull 失败")
                elif local.exists() and any(local.iterdir()):
                    raise RuntimeError(f"{local} 已存在且不是 git 仓库，换一个空目录再更新")
                else:
                    local.parent.mkdir(parents=True, exist_ok=True)
                    r = git_run(["clone", url, str(local)])
                    out = (r.stdout or "") + (r.stderr or "")
                    if r.returncode != 0:
                        raise RuntimeError(out.strip() or "git clone 失败")
                    self.sig.log.emit(out.strip() or "clone 完成")
                self.sig.log.emit("更新完成")
                self.sig.toast_ok.emit("更新完成", "源目录已同步")
            except Exception as e:
                self.sig.log.emit(f"失败：{e}")
                self.sig.alert.emit("更新失败", str(e))
            finally:
                self.sig.done_refresh.emit()

        threading.Thread(target=work, daemon=True).start()

    def on_check(self):
        if not self._guard():
            return
        source = self.source()
        if not source.is_dir():
            self._toast_warn("缺少源", "本地目录不存在")
            return
        agents = self.agent_list.selected()
        if not agents:
            agents = [name for name, home, _dest in AGENTS if home.is_dir()]
        skills = self.skill_list.selected() or [p.name for p in list_skills(source)]
        agent_map = {name: dest for name, _home, dest in AGENTS}
        self.set_busy(True)
        self.log_line(f"检查改动：对照 {source}")

        def work():
            dirty: dict[str, dict[str, list[str]]] = {}
            total = 0
            try:
                for sname in skills:
                    src = source / sname
                    if not is_skill_dir(src):
                        continue
                    for aname in agents:
                        dest = agent_map[aname] / sname
                        changes = diff_skill(src, dest)
                        dirty.setdefault(sname, {})[aname] = changes
                        if is_real_change(changes):
                            total += 1
                            self.sig.log.emit(f"{aname} / {sname}\n  " + "\n  ".join(changes))
                if total == 0:
                    self.sig.log.emit("没有相对源仓的改动")
                    self.sig.toast_ok.emit("检查完成", "没有相对源仓的改动")
                else:
                    self.sig.log.emit(
                        f"共 {total} 处 skill×Agent 有改动。~ 内容不同，+ Agent多出来，- 源有Agent没有"
                    )
                    self.sig.toast_ok.emit("检查完成", f"共 {total} 处有改动")
                self.sig.finish_check.emit(dirty)
            except Exception as e:
                self.sig.log.emit(f"失败：{e}")
                self.sig.alert.emit("检查失败", str(e))
                self.sig.done_refresh_keep.emit()

        threading.Thread(target=work, daemon=True).start()

    def on_writeback(self):
        if not self._guard():
            return
        agents = self.agent_list.selected()
        skills = self.skill_list.selected()
        if len(agents) != 1:
            self._toast_warn("写回源目录", "请只勾选一个 Agent，改动从那里写回源仓。")
            return
        if not skills:
            self._toast_warn("未选择", "请勾选要写回的 Skill")
            return
        aname = agents[0]
        source = self.source()
        dest_root = {name: dest for name, _home, dest in AGENTS}[aname]
        missing = [n for n in skills if not (dest_root / n).is_dir()]
        if missing:
            self._alert("Agent 里没有", "这些 skill 在该 Agent 里不存在：\n" + "\n".join(missing))
            return
        default_msg = f"Update {', '.join(skills)} from {aname}"
        if not self._confirm(
            "确认写回并上传",
            f"用 {aname} 里的 {len(skills)} 个 skill 覆盖本地源目录，然后 git commit + push。\n\n{source}",
        ):
            return
        dlg = CommitDialog(default_msg, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        commit_msg = dlg.message() or default_msg
        self.set_busy(True)
        self.log_line(f"写回并上传：{aname} → {source}")

        def work():
            ok = 0
            fail = 0
            copied: list[str] = []
            try:
                for sname in skills:
                    try:
                        copy_back(dest_root / sname, source / sname)
                        ok += 1
                        copied.append(sname)
                        self.sig.log.emit(f"OK  {sname} → 源目录")
                    except Exception as e:
                        fail += 1
                        self.sig.log.emit(f"FAIL {sname}：{e}")
                git_msg = ""
                if copied:
                    try:
                        git_msg = git_commit_push(source, copied, commit_msg)
                        self.sig.log.emit(git_msg)
                    except Exception as e:
                        self.sig.log.emit(f"上传失败：{e}")
                        self.sig.alert.emit("上传失败", str(e))
                        return
                self.dirty = {}
                summary = f"写回 {ok} 个"
                if fail:
                    summary += f"，失败 {fail}"
                if git_msg:
                    summary += "，已提交并推送" if "跳过" not in git_msg else "，无新变化未推送"
                self.sig.log.emit(summary)
                if fail:
                    self.sig.alert.emit("部分失败", summary)
                else:
                    self.sig.toast_ok.emit("完成", summary)
            except Exception as e:
                self.sig.log.emit(f"失败：{e}")
                self.sig.alert.emit("写回失败", str(e))
            finally:
                self.sig.done_refresh_keep.emit()

        threading.Thread(target=work, daemon=True).start()

    def on_copy(self):
        if not self._guard():
            return
        agents = self.agent_list.selected()
        skills = self.skill_list.selected()
        if not agents:
            self._toast_warn("未选择", "请至少勾选一个 Agent")
            return
        if not skills:
            self._toast_warn("未选择", "请至少勾选一个 Skill")
            return
        source = self.source()
        missing = [n for n in skills if not is_skill_dir(source / n)]
        if missing:
            self._alert("源不存在", "这些 skill 在本地目录里找不到：\n" + "\n".join(missing))
            return
        agent_map = {name: (home, dest) for name, home, dest in AGENTS}
        n = len(agents) * len(skills)
        if not self._confirm(
            "确认复制",
            f"将把 {len(skills)} 个 skill 复制到 {len(agents)} 个 Agent（共 {n} 次）。\n目标已存在则覆盖。",
        ):
            return
        self.set_busy(True)
        self.log_line(f"开始复制：{len(skills)} skill × {len(agents)} Agent")

        def work():
            ok = 0
            fail = 0
            try:
                for aname in agents:
                    _home, dest_root = agent_map[aname]
                    for sname in skills:
                        src = source / sname
                        dest = dest_root / sname
                        try:
                            copy_skill(src, dest, aname)
                            ok += 1
                            self.sig.log.emit(f"OK  {sname} → {aname}\n     {dest}")
                        except Exception as e:
                            fail += 1
                            self.sig.log.emit(f"FAIL {sname} → {aname}：{e}")
                self.sig.log.emit(f"复制结束：成功 {ok}，失败 {fail}")
                extra = ""
                if "Claude Code" in agents:
                    extra = " Claude 需新开会话，或执行 /reload-plugins。"
                    self.sig.log.emit("Claude：新开会话，或执行 /reload-plugins")
                if fail:
                    self.sig.alert.emit("部分失败", f"成功 {ok}，失败 {fail}，见日志")
                else:
                    self.sig.toast_ok.emit("完成", f"已复制 {ok} 项。{extra}".strip())
            except Exception as e:
                self.sig.log.emit(f"失败：{e}")
                self.sig.alert.emit("复制失败", str(e))
            finally:
                self.sig.done_refresh.emit()

        threading.Thread(target=work, daemon=True).start()

    def _finish_check(self, dirty: dict[str, dict[str, list[str]]]):
        self.dirty = dirty
        self.set_busy(False)
        self.refresh(keep=True, quiet=True)

    def _done_refresh(self):
        self.set_busy(False)
        self.dirty = {}
        self.refresh()

    def _done_refresh_keep(self):
        self.set_busy(False)
        self.refresh(keep=True, quiet=True)


def main():
    if sys.platform == "win32":
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    translator = FluentTranslator(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    app.installTranslator(translator)
    setTheme(Theme.AUTO)
    setFontFamilies(["Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei", "PingFang SC"])
    win = App()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _boot_error(traceback.format_exc())
