"""`oraena connect|disconnect|init`: 두 호스트에 하네스를 걸고 푼다.

사용자가 자기 터미널에서 실행한다(설계서 11절 G6). AI는 하네스 설정을 고치지 못하게 막혀 있다.
표시 블록과 oraena 항목만 고치고 다른 내용은 그대로 둔다. 쓰기 전에 원본을 백업한다.

- Claude: `~/.claude/settings.json`(훅, 폴더 접근, 설정 파일 편집 막기), `~/.claude/CLAUDE.md`(표시 블록),
  `~/.claude/skills/<이름>`(정션)
- Codex: `~/.codex/hooks.json`(훅), `~/.codex/AGENTS.md`(표시 블록, 지침과 지도를 그대로 넣음),
  `~/.agents/skills/<이름>`(정션)
- `~/.oraena.json`(데이터 폴더 위치)
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from oraena import config, index, localgit, migrate, okf

BEGIN, END = "<!-- BEGIN ORAENA -->", "<!-- END ORAENA -->"  # 0.3과 같은 표지라 0.3 블록을 바로 바꾼다
CODEX_BEGIN, CODEX_END = "<!-- BEGIN ORAENA CODEX -->", "<!-- END ORAENA CODEX -->"

# (사건, matcher, 훅 이름, 덧붙일 설정)
CLAUDE_HOOKS = (
    ("SessionStart", None, "session-start", {"timeout": 15}),
    ("UserPromptSubmit", None, "prompt", {"timeout": 10}),
    ("PreToolUse", "Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit|Agent|Task|Workflow|mcp__.*",
     "pre-tool", {"timeout": 15}),
    # Claude는 검색을 Grep·Glob 도구로 한다. Bash까지 걸면 매 명령마다 약 85ms가 는다.
    ("PostToolUse", "Write|Edit|MultiEdit|NotebookEdit|Grep|Glob|mcp__.*", "post-tool", {"timeout": 15}),
    ("Stop", None, "stop", {"timeout": 60}),
)
CODEX_HOOKS = (
    ("SessionStart", None, "session-start", {"timeout": 15, "additionalContextLimit": 8000}),
    ("UserPromptSubmit", None, "prompt", {"timeout": 10, "additionalContextLimit": 3000}),
    ("PreToolUse", "Bash|apply_patch|mcp__.*", "pre-tool", {"timeout": 15}),
    ("PostToolUse", "Bash|apply_patch|mcp__.*", "post-tool", {"timeout": 15}),
    ("Stop", None, "stop", {"timeout": 60}),
)
# 훅 스크립트가 고장 나도 남는 막기(Claude 권한 규칙). Edit 규칙은 파일을 고치는 모든 내장 도구에 걸린다.
DENY_EDITS = (
    "Edit(//**/.claude/settings*.json)",
    "Edit(~/.claude/hooks/**)",
    "Edit(//**/.codex/config.toml)",
    "Edit(//**/.codex/hooks.json)",
    "Edit(//**/uv/tools/oraena/**)",
    "Edit(~/.oraena.json)",
)
OPENAI_YAML = "policy:\n  allow_implicit_invocation: false\n"
ON_FAILURE_MIN = (2, 1, 295)  # Claude 훅 onFailure: "block" 최소 버전


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def agents_skills() -> Path:
    return Path.home() / ".agents" / "skills"


# --- 바꿀 내용을 모으고, 보여 주거나 쓴다 ----------------------------------------

@dataclass
class Change:
    path: Path
    before: str | None
    after: str | None  # None이면 지운다


class Plan:
    def __init__(self) -> None:
        self.changes: list[Change] = []
        self.links: list[tuple[str, Path, Path | None]] = []  # (make|remove, 링크, 대상)
        self.notes: list[str] = []

    def text(self, path: Path, after: str | None) -> None:
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before != after:
            self.changes.append(Change(path, before, after))

    def show(self) -> str:
        out = []
        for c in self.changes:
            out.append(f"=== {c.path}" + (" (지움)" if c.after is None else ""))
            diff = difflib.unified_diff((c.before or "").splitlines(), (c.after or "").splitlines(),
                                        lineterm="", n=1)
            out += list(diff)[2:]
        for op, link, target in self.links:
            out.append(f"=== {'정션 만들기' if op == 'make' else '정션 지우기'}: {link}" + (f" → {target}" if target else ""))
        out += [f"- {n}" for n in self.notes]
        return "\n".join(out) if out else "바꿀 것이 없습니다."

    def apply(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        for c in self.changes:
            if c.path.exists():
                shutil.copy2(c.path, c.path.with_name(f"{c.path.name}.oraena-backup-{stamp}"))
            if c.after is None:
                if c.path.exists():
                    c.path.unlink()
                continue
            c.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = c.path.with_name(c.path.name + ".oraena-tmp")
            tmp.write_text(c.after, encoding="utf-8", newline="\n")
            os.replace(tmp, c.path)
        for op, link, target in self.links:
            if op == "remove":
                _remove_link(link)
            else:
                link.parent.mkdir(parents=True, exist_ok=True)
                _make_link(target, link)


# --- 파일 조각 -------------------------------------------------------------

def _json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _is_ours(handler: dict) -> bool:
    text = " ".join([str(handler.get("command", "")), str(handler.get("commandWindows", "")),
                     *map(str, handler.get("args") or [])])
    return "oraena" in text and "hook" in text


def _strip_hooks(settings: dict) -> None:
    hooks = settings.get("hooks") or {}
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if not _is_ours(h)]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)


def _add_hooks(settings: dict, table, handler_of) -> None:
    hooks = settings.setdefault("hooks", {})
    for event, matcher, name, extra in table:
        group = {"hooks": [{**handler_of(name), **extra}]}
        if matcher:
            group["matcher"] = matcher
        hooks.setdefault(event, []).append(group)


def _set_block(text: str, begin: str, end: str, body: str | None) -> str | None:
    if begin in text and end in text:
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
        text = head.rstrip("\n") + ("\n\n" if head.strip() and tail.strip() else "") + tail.lstrip("\n")
    text = text.strip("\n")
    if body is not None:
        block = f"{begin}\n{body}\n{end}"
        text = f"{text}\n\n{block}" if text else block
    return text + "\n" if text else None


def _import_path(path: Path) -> str:
    """`@` 가져오기 경로. 빈칸은 백슬래시로 escape한다(따옴표는 가져오지 않는다)."""
    return "@" + path.as_posix().replace(" ", "\\ ")


def _version(cmd: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out.stdout)
    return tuple(int(x) for x in m.groups()) if m else None


def _root_mark(root: Path) -> str:
    return f"<!-- oraena root: {root.resolve().as_posix()} -->"


def codex_block(root: Path) -> str:
    """Codex 전역 AGENTS.md에 넣을 글. Codex는 `@` 가져오기가 없어 지침과 지도를 그대로 넣는다."""
    agents = (config.agent(root) / "AGENTS.md").read_text(encoding="utf-8").strip()
    map_path = config.wiki(root) / "index.md"
    body = okf.read(map_path).body.strip() if map_path.exists() else ""
    return f"{_root_mark(root)}\n{agents}\n\n# 지식 지도 ({map_path.as_posix()}, 링크는 이 폴더 기준)\n\n{body}"


def refresh_codex_block(root: Path) -> bool:
    """Codex에 이 데이터 폴더가 연결돼 있으면 표시 블록을 지금의 지침·지도로 다시 쓴다.

    턴 끝 훅이 목차를 만든 뒤 부른다. 블록의 데이터 폴더 표지가 같을 때만 쓴다. 다른 폴더(시험용 사본 등)로
    돈 훅이 사용자의 연결을 덮어쓰지 않게 하기 위해서다(2026-10-13 시험 사본 경로가 실제 파일에 들어간 일).
    """
    path = codex_home() / "AGENTS.md"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if CODEX_BEGIN not in text or _root_mark(root) not in text:
        return False
    new = _set_block(text, CODEX_BEGIN, CODEX_END, codex_block(root))
    if new != text:
        path.write_text(new or "", encoding="utf-8", newline="\n")
        return True
    return False


# --- 스킬 정션 --------------------------------------------------------------

def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(path))


def _link_target(link: Path) -> Path | None:
    try:
        raw = os.readlink(link)
    except OSError:
        return None
    return Path(raw[4:] if raw.startswith("\\\\?\\") else raw)


def _make_link(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _remove_link(link: Path) -> None:
    # 정션은 rmdir로 링크만 지운다. rmtree는 대상 내용까지 지운다.
    if sys.platform == "win32" and os.path.isjunction(link):
        os.rmdir(link)
    else:
        link.unlink()


def _inside(path: Path, folder: Path) -> bool:
    a, b = os.path.normcase(str(path)), os.path.normcase(str(folder))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def _skill_links(plan: Plan, root: Path, home: Path, wanted: dict[str, Path], clean_only: bool = False) -> None:
    """home 안에서 데이터 폴더를 가리키는 연결을 맞춘다. 사용자 폴더와 다른 곳을 가리키는 연결은 두지 않는다."""
    if home.is_dir():
        for link in sorted(home.iterdir()):
            if not _is_link(link):
                continue
            target = _link_target(link)
            if target is None or not _inside(target, root):
                continue
            if clean_only or link.name not in wanted or os.path.normcase(str(target)) != os.path.normcase(str(wanted[link.name])):
                plan.links.append(("remove", link, None))
    if clean_only:
        return
    for name, target in wanted.items():
        link = home / name
        if _is_link(link) and os.path.normcase(str(_link_target(link))) == os.path.normcase(str(target)):
            continue
        if link.exists() and not _is_link(link):
            plan.notes.append(f"건너뜀: {link}는 사용자 폴더입니다. 이름을 바꾸면 연결합니다.")
            continue
        plan.links.append(("make", link, target))


def _skills(root: Path) -> dict[str, Path]:
    source = config.agent(root) / "skills"
    if not source.is_dir():
        return {}
    return {d.name: d for d in sorted(source.iterdir()) if (d / "SKILL.md").is_file()}


# --- 연결과 해제 -------------------------------------------------------------

def plan_connect(root: Path, python: str, host: str = "all") -> Plan:
    plan = Plan()
    root = root.resolve()
    skills = _skills(root)
    if host in ("all", "claude"):
        home = claude_home()
        path = home / "settings.json"
        settings = _json(path)
        _strip_hooks(settings)
        on_failure = {}
        version = _version("claude")
        if version and version >= ON_FAILURE_MIN:
            on_failure = {"onFailure": "block"}
        else:
            plan.notes.append(f"Claude {'.'.join(map(str, version)) if version else '버전 모름'}: 훅이 실패하면 막는 "
                              "onFailure는 2.1.295부터라 넣지 않았습니다. 설정 파일 편집 막기는 권한 규칙으로 남습니다.")

        def claude_handler(name: str) -> dict:
            extra = on_failure if name == "pre-tool" else {}
            return {"type": "command", "command": python,
                    "args": ["-m", "oraena", "hook", name, "--host", "claude"], **extra}
        _add_hooks(settings, CLAUDE_HOOKS, claude_handler)
        perms = settings.setdefault("permissions", {})
        dirs = perms.setdefault("additionalDirectories", [])
        if str(root) not in dirs:
            dirs.append(str(root))
        deny = perms.setdefault("deny", [])
        deny += [r for r in DENY_EDITS if r not in deny]
        settings["autoMemoryEnabled"] = False  # 설계서 3.7: 자동 메모리는 끈 채로 둔다
        plan.text(path, _dump(settings))
        md = home / "CLAUDE.md"
        text = md.read_text(encoding="utf-8") if md.exists() else ""
        body = "\n".join([_import_path(config.agent(root) / "AGENTS.md"), _import_path(config.wiki(root) / "index.md")])
        plan.text(md, _set_block(text, BEGIN, END, body))
        _skill_links(plan, root, home / "skills", skills)
    if host in ("all", "codex"):
        home = codex_home()
        path = home / "hooks.json"
        data = _json(path)
        _strip_hooks(data)

        def codex_handler(name: str) -> dict:
            cmd = subprocess.list2cmdline([python, "-m", "oraena", "hook", name, "--host", "codex"])
            return {"type": "command", "command": cmd, "commandWindows": cmd}
        _add_hooks(data, CODEX_HOOKS, codex_handler)
        plan.text(path, _dump(data))
        md = home / "AGENTS.md"
        text = md.read_text(encoding="utf-8") if md.exists() else ""
        plan.text(md, _set_block(text, CODEX_BEGIN, CODEX_END, codex_block(root)))
        _skill_links(plan, root, agents_skills(), skills)
        _skill_links(plan, root, home / "skills", {}, clean_only=True)  # 0.3이 쓰던 자리
        for name, folder in skills.items():
            yaml_path = folder / "agents" / "openai.yaml"
            if not yaml_path.exists():
                plan.text(yaml_path, OPENAI_YAML)
            elif "allow_implicit_invocation: false" not in yaml_path.read_text(encoding="utf-8"):
                plan.notes.append(f"{yaml_path}에 allow_implicit_invocation: false가 없습니다. Codex가 이 스킬을 스스로 부를 수 있습니다.")
        plan.notes.append("Codex를 열고 /hooks에서 oraena 훅 5개를 검토하고 신뢰합니다. 신뢰하기 전에는 돌지 않습니다.")
    cfg = config.load()
    if cfg.get("root") != str(root):
        plan.text(config.CONFIG, json.dumps({**cfg, "root": str(root)}, ensure_ascii=False, indent=2) + "\n")
    if any(part in python.lower() for part in ("oraena-rebuild", "\\.venv\\", "/.venv/")):
        plan.notes.append(f"훅 실행 파일이 개발 폴더입니다: {python}. 설치본(`uv tool install`)에서 다시 실행합니다.")
    return plan


def plan_disconnect(root: Path, host: str = "all") -> Plan:
    plan = Plan()
    root = root.resolve()
    if host in ("all", "claude"):
        home = claude_home()
        path = home / "settings.json"
        if path.exists():
            settings = _json(path)
            _strip_hooks(settings)
            perms = settings.get("permissions") or {}
            if str(root) in perms.get("additionalDirectories", []):
                perms["additionalDirectories"].remove(str(root))
            if "deny" in perms:
                perms["deny"] = [r for r in perms["deny"] if r not in DENY_EDITS]
            plan.text(path, _dump(settings))
        md = home / "CLAUDE.md"
        if md.exists():
            plan.text(md, _set_block(md.read_text(encoding="utf-8"), BEGIN, END, None))
        _skill_links(plan, root, home / "skills", {}, clean_only=True)
        plan.notes.append("autoMemoryEnabled 값은 그대로 두었습니다.")
    if host in ("all", "codex"):
        home = codex_home()
        path = home / "hooks.json"
        if path.exists():
            data = _json(path)
            _strip_hooks(data)
            plan.text(path, _dump(data))
        md = home / "AGENTS.md"
        if md.exists():
            plan.text(md, _set_block(md.read_text(encoding="utf-8"), CODEX_BEGIN, CODEX_END, None))
        _skill_links(plan, root, agents_skills(), {}, clean_only=True)
        _skill_links(plan, root, home / "skills", {}, clean_only=True)
    return plan


def init_data(folder: Path) -> list[str]:
    """빈 폴더에 데이터 층(wiki/, raw/, agent/)과 로컬 git을 만든다."""
    root = folder.resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"폴더가 비어 있지 않습니다: {root}. 이미 데이터 폴더면 `oraena connect --root`를 씁니다.")
    (config.wiki(root)).mkdir(parents=True, exist_ok=True)
    (config.raw(root)).mkdir(parents=True, exist_ok=True)
    (config.raw(root) / "README.md").write_text("원시 기록. 새 파일만 쓴다. 이미 있는 파일은 고치지 않는다.\n",
                                                 encoding="utf-8", newline="\n")
    migrate.write_agent(root)
    (root / ".gitignore").write_text(".oraena/\n", encoding="utf-8", newline="\n")
    index.build(root)
    made = [f"데이터 폴더: {root} (wiki/, raw/, agent/)"]
    try:
        ok = localgit.init(root, "oraena init")
    except (OSError, subprocess.SubprocessError):
        ok = False
    made.append("로컬 git 저장소(원격 없음)" if ok else
                "로컬 git을 만들지 못했습니다(git 설치 확인). 지난 판 되살리기가 안 됩니다.")
    return made


# --- 명령 -----------------------------------------------------------------

def add_args(parser) -> None:
    parser.add_argument("--root", help="데이터 폴더(기본: 설정의 root)")
    parser.add_argument("--host", choices=["all", "claude", "codex"], default="all")
    parser.add_argument("--python", help="훅이 부를 Python(기본: 이 명령을 실행한 Python)")
    parser.add_argument("--dry-run", action="store_true", help="바꿀 내용만 보여 준다")


def add_init_args(parser) -> None:
    parser.add_argument("folder", help="데이터 폴더로 쓸 빈 폴더")
    parser.add_argument("--no-connect", action="store_true", help="폴더만 만들고 호스트에 걸지 않는다")
    parser.add_argument("--python", help="훅이 부를 Python(기본: 이 명령을 실행한 Python)")
    parser.add_argument("--dry-run", action="store_true", help="연결로 바꿀 내용만 보여 준다")


def _finish(plan: Plan, dry_run: bool) -> int:
    print(plan.show())
    if dry_run:
        print("\n(--dry-run: 아무것도 바꾸지 않았습니다)")
        return 0
    plan.apply()
    print("\n적용했습니다. 새 세션부터 걸립니다. 원본은 <이름>.oraena-backup-<시각>으로 남겼습니다.")
    return 0


def run_connect(args) -> int:
    root = Path(args.root) if args.root else config.data_root()
    if not config.wiki(root).is_dir() or not (config.agent(root) / "AGENTS.md").is_file():
        raise SystemExit(f"{root}에 wiki/와 agent/AGENTS.md가 없습니다. `oraena init` 또는 `oraena migrate`를 먼저 합니다.")
    return _finish(plan_connect(root, args.python or sys.executable, args.host), args.dry_run)


def run_disconnect(args) -> int:
    root = Path(args.root) if args.root else config.data_root()
    return _finish(plan_disconnect(root, args.host), args.dry_run)


def run_init(args) -> int:
    folder = Path(args.folder)
    if args.dry_run:
        print(f"{folder.resolve()}에 wiki/, raw/, agent/, 로컬 git을 만듭니다.")
        return 0
    for line in init_data(folder):
        print(line)
    if args.no_connect:
        return 0
    return _finish(plan_connect(folder, args.python or sys.executable), False)
