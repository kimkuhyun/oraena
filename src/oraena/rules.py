"""도구 호출 하나를 판정한다: 엔진의 핵심 규칙 3개와 데이터 폴더의 정책 규칙.

핵심 규칙은 하네스 설정, 정책 규칙 파일, raw/의 기존 파일을 지킨다. 그 밖의 막기·확인은 사용자가
`agent/policy/`에 둔다(oraena.policy). 확인(ask)은 Claude에서는 사용자에게 묻고, Codex에는 묻는
기능이 없어 막은 뒤 사용자가 직접 실행하게 한다. 판정은 문자열과 경로만 본다. 모델을 부르지 않는다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from oraena import patch

DENY, ASK = "deny", "ask"


@dataclass(frozen=True)
class Hit:
    rule: str
    level: str
    say: str


@dataclass
class Action:
    """두 호스트의 도구 호출을 같은 모양으로 편 것."""

    host: str
    tool: str
    cwd: str
    shell: list[str] = field(default_factory=list)
    writes: list[tuple[str, str]] = field(default_factory=list)  # (add|write|edit|delete|move, 정규화 경로)
    content: list[str] = field(default_factory=list)
    input: dict = field(default_factory=dict)


SAY = {
    "harness": "하네스 설정(훅, settings.json, config.toml, 플러그인, oraena 설치본)을 AI가 바꾸지 마세요. "
               "이유: AI가 자기 경계를 풀 수 있으면 경계가 아닙니다. 바꿀 내용과 명령을 사용자에게 보여 주세요.",
    "policy": "정책 규칙(agent/policy/)은 AI가 쓰거나 고칠 수 없습니다. 새 규칙은 raw/proposals/에 제안 파일로 쓰고 "
              "사용자에게 알리세요. 이유: AI가 자기 규칙을 바꿀 수 있으면 경계가 아닙니다.",
    "raw": "raw/의 기존 파일은 고치거나 옮기거나 지우지 마세요. 새 파일은 Write 도구나 새 경로로의 복사(cp, >)로 만드세요. "
           "이유: 원시 기록은 근거라서 바뀌면 안 됩니다.",
}
CODEX_ASK = " Codex에는 확인 창이 없어 막았습니다. 명령을 사용자에게 보여 주고 직접 실행하게 하세요."

I = re.I | re.S


def _any(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), I)


# --- 핵심 규칙의 표지 ------------------------------------------------------

# 경로는 소문자, 슬래시로 바꾼 뒤 맞춘다.
HARNESS_PATH = re.compile(
    r"\.claude/(?:settings[^/]*\.json|hooks/|plugins/)"
    r"|managed-settings\.json"
    r"|\.codex/(?:config\.toml|hooks\.json|requirements\.toml)"
    r"|openai/codex/requirements\.toml"
    r"|/uv/tools/oraena/"
    r"|\.oraena\.json"
)
HARNESS_SHELL = _any(
    r"\bclaude\s+(?:plugins?|mcp|config)\s+(?:install|uninstall|remove|rm|enable|disable|add|set|update|marketplace)\b",
    r"\bcodex\s+(?:mcp|features|plugins?)\s+(?:add|remove|enable|disable|install|uninstall)\b",
    r"\boraena\s+(?:connect|disconnect|init|install|uninstall)\b",
    r"\buv\s+tool\s+(?:install|uninstall|upgrade)\b[^\n]*\boraena\b",
)
HELP = re.compile(r"\s(?:--help|-h|--dry-run)\b")
# 빈칸이 든 따옴표 문자열은 검색어나 메시지다. 하네스 명령 판정에서는 빼고 본다(예: rg "oraena init").
# 따옴표는 왼쪽부터 짝지어야 한다. 빈칸 있는 것만 고르는 정규식은 `"$T" && oraena init "$T"`에서
# 앞 문자열의 닫는 따옴표와 뒤 문자열의 여는 따옴표를 짝지어 명령을 지운다.
QUOTED = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")


def _strip_phrases(cmd: str) -> str:
    return QUOTED.sub(lambda m: " " if re.search(r"\s", m.group(0)[1:-1]) else m.group(0), cmd)
DISABLE_HOOKS = re.compile(r"disableAllHooks", re.I)

# 쓰기·지우기·옮기기로 읽히는 셸 낱말. 경로 언급과 함께 있을 때만 본다.
SHELL_WRITE = _any(
    r"\b(?:Set-Content|Add-Content|Out-File|Clear-Content|Copy-Item|Move-Item|Remove-Item|Rename-Item|New-Item)\b",
    r"(?:^|[\s;&|(])(?:cp|mv|rm|del|erase|copy|move|ren|rename|tee|truncate|sc|ac|ni|ri|mi|ci)\s",
    r"\bsed\s+-i",
    r"\bWriteAll(?:Text|Bytes|Lines)\b|\bwrite_(?:text|bytes)\b|\bjson\.dump\b|\bshutil\.\w+|\bos\.(?:remove|replace|rename|unlink)\b",
)
REDIRECT_TARGET = re.compile(r"(?<![0-9&<>=-])>>?\s*['\"]?([^\s'\";|&)]+)")

MCP_FILE_TOOL = re.compile(r"write|edit|move|create|delete|remove|rename|append|patch", re.I)
MCP_SHELL_TOOL = re.compile(r"process|terminal|exec|shell|command|interact", re.I)
PATH_KEYS = ("path", "file_path", "filePath", "source", "destination", "target", "notebook_path", "dest")
CONTENT_KEYS = ("content", "text", "new_string", "newText", "new_source", "body", "data")
SHELL_KEYS = ("command", "cmd", "input")


# --- 호출을 펴기 -----------------------------------------------------------

def norm(path: str, cwd: str = "") -> str:
    """소문자, 슬래시, 절대 경로."""
    p = os.path.expandvars(os.path.expanduser(str(path).strip().strip("'\"")))
    if cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.normpath(p).replace("\\", "/").lower()


def _shell_norm(cmd: str) -> str:
    home = os.path.expanduser("~").replace("\\", "/").lower()
    s = cmd.replace("\\", "/").lower()
    for var in ("$env:userprofile", "%userprofile%", "${home}", "$home"):
        s = s.replace(var, home)
    return re.sub(r"(?<![\w.])~(?=/)", home, s)


def _command_text(value) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value or "")


HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
HERESTRING = re.compile(r"@(['\"])[ \t]*\r?\n(.*?)\r?\n\1@", re.S)
SPLIT = re.compile(r"\r?\n|;|&&|\|\||\|")
ASSIGN_PS = re.compile(r"^\s*\$(\w+)\s*=\s*(.+?)\s*$")
ASSIGN_SH = re.compile(r"(?:^|\s)(?:export\s+)?([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;]+)")
VAR_REF = re.compile(r"\$\{?(?!env:)(\w+)\}?")
TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|\S+")
COPY_VERB = re.compile(r"^\s*(?:cp|copy|Copy-Item|cpi)\b", re.I)
SED_INPLACE = re.compile(r"^\s*sed\s+-i", re.I)


TEXT_SINK = re.compile(r"\bgit\b[^\n]*\bcommit\b|\b(?:cat|tee)\b|\bgh\b", re.I)


def drop_text_heredocs(cmd: str) -> str:
    """커밋 메시지·파일 내용처럼 글로 넘기는 heredoc 본문을 뺀다. 실행되는 본문(python - 등)은 남긴다.

    예: 커밋 메시지의 영어 낱말 "move"가 Windows move 명령으로 읽혀 raw/ 보호에 걸리지 않게 한다.
    """
    def repl(m: re.Match) -> str:
        opener = cmd[cmd.rfind("\n", 0, m.start()) + 1:m.start()]
        return " " if TEXT_SINK.search(opener) else m.group(0)
    return HEREDOC.sub(repl, cmd)


def segments(cmd: str) -> list[str]:
    """명령을 판정 단위로 나눈다. heredoc·here-string 본문은 통째로 한 단위다(스크립트 하나)."""
    bodies: list[str] = []

    def take(m: re.Match) -> str:
        bodies.append(m.group(m.lastindex))
        return " "
    rest = HERESTRING.sub(take, HEREDOC.sub(take, cmd))
    return bodies + [s for s in SPLIT.split(rest) if s.strip()]


def variables(cmd: str) -> dict[str, str]:
    """`$x = 값`(PowerShell)과 `X=값`(sh) 대입을 모은다. 대상 경로가 변수에 들어 있을 때 쓴다."""
    out: dict[str, str] = {}
    for seg in SPLIT.split(cmd):
        m = ASSIGN_PS.match(seg)
        if m:
            out[m.group(1).lower()] = m.group(2).strip("'\"")
            continue
        for m in ASSIGN_SH.finditer(seg):
            out[m.group(1).lower()] = m.group(2).strip("'\"")
    return out


def expand(text: str, values: dict[str, str]) -> str:
    for _ in range(2):
        text = VAR_REF.sub(lambda m: values.get(m.group(1).lower(), m.group(0)), text)
    return text


def _destination(seg: str) -> str:
    m = re.search(r"-Destination\s+(\S+)", seg, re.I)
    if m:
        return m.group(1)
    toks = [t for t in TOKEN.findall(seg) if not t.startswith("-")]
    return toks[-1] if toks else ""


def _writes_to(cmd: str, segs: list[str], values: dict[str, str], test) -> bool:
    """명령이 test(경로)에 맞는 곳에 쓰거나 지우는가.

    리다이렉트 대상을 보고, 쓰기 낱말이 있는 단위에서 경로 언급을 본다. 복사와 sed -i는 대상 파일만 본다.
    """
    for m in REDIRECT_TARGET.finditer(_shell_norm(expand(cmd, values))):
        if test(m.group(1)):
            return True
    for seg in segs:
        if not SHELL_WRITE.search(seg):
            continue
        target = _destination(seg) if COPY_VERB.match(seg) or SED_INPLACE.match(seg) else seg
        if test(_shell_norm(expand(target, values))):
            return True
    return False


TEE = re.compile(r"^\s*tee\b", re.I)
GLOB = re.compile(r"[*?\[]")


def _real(path: str, cwd: str) -> str:
    """셸 글의 경로를 os가 찾을 수 있는 경로로 편다(Git Bash의 /c/... 포함)."""
    p = path.strip().strip("'\"")
    p = re.sub(r"^/([a-z])/", r"\1:/", p)
    return p if os.path.isabs(p) or not cwd else os.path.join(cwd, p)


def _changes_existing(cmd: str, segs: list[str], values: dict[str, str], test, cwd: str) -> bool:
    """_writes_to와 같되, 셸로 새 파일을 만드는 것은 뺀다(raw/ 보호용).

    새 경로로의 복사(cp, copy, Copy-Item), `>` 리다이렉트, tee(-a 없이)는 대상이 없을 때만 지나간다.
    이미 있는 파일을 덮거나, 덧붙이거나(>>, tee -a), 대상에 와일드카드가 있으면 바꾸는 것으로 본다.
    """
    def existing(token: str) -> bool:
        s = _shell_norm(expand(token, values)).strip("'\"")
        return bool(GLOB.search(s)) or os.path.exists(_real(s, cwd))

    for m in REDIRECT_TARGET.finditer(_shell_norm(expand(cmd, values))):
        if test(m.group(1)) and (m.group(0).startswith(">>") or existing(m.group(1))):
            return True
    for seg in segs:
        if not SHELL_WRITE.search(seg):
            continue
        toks = [t for t in TOKEN.findall(seg) if not t.startswith("-")][1:]
        if COPY_VERB.match(seg) and toks:
            dest = _destination(seg)
            if not test(_shell_norm(expand(dest, values))):
                continue
            real = _real(_shell_norm(expand(dest, values)), cwd)
            if GLOB.search(real) or os.path.isfile(real):
                return True
            if os.path.isdir(real):
                for src in (t for t in toks if t != dest):
                    name = os.path.basename(_shell_norm(expand(src, values)).strip("'\"").rstrip("/"))
                    if GLOB.search(name) or os.path.exists(os.path.join(real, name)):
                        return True
            continue
        if TEE.match(seg) and not re.search(r"\s-a\b|--append\b", seg):
            if any(test(_shell_norm(expand(t, values))) and existing(t) for t in toks):
                return True
            continue
        target = _destination(seg) if SED_INPLACE.match(seg) else seg
        if test(_shell_norm(expand(target, values))):
            return True
    return False


def _apply_patch(act: Action, text: str) -> None:
    for op, path in patch.operations(text):
        act.writes.append((op, norm(path, act.cwd)))
    added = patch.added_text(text)
    if added:
        act.content.append(added)


def action_of(host: str, tool: str, tool_input: dict, cwd: str = "") -> Action:
    ti = tool_input if isinstance(tool_input, dict) else {}
    act = Action(host=host, tool=tool or "", cwd=cwd or "", input=ti)
    if tool in ("Bash", "PowerShell", "shell", "local_shell", "exec_command", "shell_command"):
        cmd = _command_text(ti.get("command") or ti.get("cmd"))
        if "*** Begin Patch" in cmd:
            _apply_patch(act, cmd)
        act.shell.append(cmd)
    elif tool == "apply_patch":
        _apply_patch(act, _command_text(ti.get("command") or ti.get("patch") or ti.get("input")))
    elif tool == "Write":
        act.writes.append(("write", norm(ti.get("file_path", ""), cwd)))
        act.content.append(str(ti.get("content") or ""))
    elif tool == "Edit":
        act.writes.append(("edit", norm(ti.get("file_path", ""), cwd)))
        act.content.append(str(ti.get("new_string") or ""))
    elif tool == "MultiEdit":
        act.writes.append(("edit", norm(ti.get("file_path", ""), cwd)))
        act.content.extend(str(e.get("new_string") or "") for e in ti.get("edits") or [] if isinstance(e, dict))
    elif tool == "NotebookEdit":
        act.writes.append(("edit", norm(ti.get("notebook_path", ""), cwd)))
        act.content.append(str(ti.get("new_source") or ""))
    elif tool.startswith("mcp__"):
        short = tool.rsplit("__", 1)[-1]
        if MCP_SHELL_TOOL.search(short):
            act.shell.extend(_command_text(ti[k]) for k in SHELL_KEYS if ti.get(k))
        if MCP_FILE_TOOL.search(short):
            for k in PATH_KEYS:
                if isinstance(ti.get(k), str) and ti[k]:
                    act.writes.append(("write", norm(ti[k], cwd)))
            act.content.extend(str(ti[k]) for k in CONTENT_KEYS if isinstance(ti.get(k), str))
    return act


# --- 판정 ---------------------------------------------------------------

@dataclass(frozen=True)
class Dirs:
    """데이터 폴더와 지킬 폴더. 경로는 norm()으로 편 값이다."""

    root: str
    raw: str
    policy: str
    policy_path: str  # 정책 파일을 읽을 실제 경로


def _dirs() -> Dirs | None:
    try:
        from oraena import config
        root = config.data_root()
    except Exception:
        return None
    policy = config.agent(root) / "policy"
    return Dirs(norm(str(root)), norm(str(config.raw(root))), norm(str(policy)), str(policy))


def _under(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def _inside(folder: str, rel_name: str, rel: bool, whole: bool = False):
    """셸 글이 folder 아래를 가리키는지 보는 판정 함수. whole이면 folder 자체(폴더째 지우기·옮기기)도 본다.

    작업 폴더가 데이터 폴더 안이면 상대 경로(rel_name)도 본다.
    """
    end = r"(?:/|$|[\s'\";|&)])" if whole else "/"
    absolute = re.compile(re.escape(folder) + end)
    relative = re.compile(r"(?:^|[\s'\"=(])(?:\./)?" + re.escape(rel_name) + end)
    return lambda s: absolute.search(s) is not None or (rel and relative.search(s) is not None)


def _policy_hits(dirs: Dirs, act: Action) -> list[Hit]:
    """사용자 정책 규칙. 정책 파일이 없으면 YAML을 읽지 않는다(훅이 빨리 끝나게).

    읽지 못한 규칙 파일은 건너뛴다. `oraena check`와 세션 시작 훅이 알린다.
    """
    folder = dirs.policy_path
    if not os.path.isdir(folder) or not any(n.endswith(".md") and n.lower() != "readme.md"
                                            for n in os.listdir(folder)):
        return []
    from pathlib import Path

    from oraena import policy
    return [Hit(f"policy:{r.id}", r.level, r.say)
            for r in policy.load_folder(Path(folder))[0] if policy.matches(r, act)]


def judge(act: Action) -> list[Hit]:
    hits: list[Hit] = []

    def hit(rule: str, level: str = DENY, say: str = "") -> None:
        if all(h.rule != rule for h in hits):
            hits.append(Hit(rule, level, say or SAY[rule]))

    dirs = _dirs()
    cwd = norm(act.cwd) if act.cwd else ""
    rel = bool(dirs) and _under(cwd, dirs.root)
    if dirs:
        in_raw = _inside(dirs.raw, "raw", rel)
        in_policy = _inside(dirs.policy, "agent/policy", rel, whole=True)

    for full in act.shell:
        # 글로 넘기는 heredoc 본문(커밋 메시지 등)은 빼고 본다.
        cmd = drop_text_heredocs(full)
        values = variables(cmd)
        segs = segments(cmd)
        low = _shell_norm(expand(cmd, values))
        if (any(HARNESS_SHELL.search(s) and not HELP.search(s) for s in segments(_strip_phrases(cmd)))
                or _writes_to(cmd, segs, values, lambda s: bool(HARNESS_PATH.search(s)))):
            hit("harness")
        if DISABLE_HOOKS.search(cmd) and (any(DISABLE_HOOKS.search(s) and SHELL_WRITE.search(s) for s in segs)
                                          or REDIRECT_TARGET.search(low)):
            hit("harness")
        if dirs:
            if _changes_existing(cmd, segs, values, in_raw, act.cwd):
                hit("raw")
            if _writes_to(cmd, segs, values, in_policy):
                hit("policy")

    text = "\n".join(act.content)
    for op, path in act.writes:
        if HARNESS_PATH.search(path) or (path.endswith(".json") and DISABLE_HOOKS.search(text)):
            hit("harness")
        if dirs and _under(path, dirs.raw) and (op in ("edit", "update", "delete") or os.path.exists(path)):
            hit("raw")
        if dirs and _under(path, dirs.policy):
            hit("policy")

    if dirs:
        for h in _policy_hits(dirs, act):
            hit(h.rule, h.level, h.say)
    return hits


def decide(hits: list[Hit], host: str) -> tuple[str, str] | None:
    """(deny|ask, 이유) 또는 None. 막기가 하나라도 있으면 막는다."""
    if not hits:
        return None
    denies = [h for h in hits if h.level == DENY]
    if denies:
        return DENY, " ".join(h.say for h in denies)
    reason = " ".join(h.say for h in hits)
    if host == "codex":
        return DENY, reason + CODEX_ASK
    return ASK, reason
