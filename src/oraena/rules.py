"""반드시 목록 11개(설계서 3.5)를 도구 호출 하나에 대해 판정한다.

막기 7개는 늘 막는다. 확인 4개는 Claude에서는 사용자에게 묻고, Codex에는 묻는 기능이 없어
막은 뒤 사용자가 직접 실행하게 한다. 판정은 문자열과 경로만 본다. 모델을 부르지 않는다.
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
    "trailer": "커밋 메시지에 Co-Authored-By 줄을 넣지 마세요. 이유: 사용자 규칙입니다. 트레일러를 빼고 다시 커밋하세요.",
    "firewall": "방화벽 허용 규칙을 만들거나 방화벽을 끄지 마세요. 이유: 이 PC는 공인 IP에 바로 붙어 있습니다. 필요하면 명령을 사용자에게 보여 주고 직접 실행하게 하세요.",
    "bind": "서버를 0.0.0.0에 바인드하지 마세요. 127.0.0.1을 쓰세요. 이유: 2026-09-03 Ollama가 외부 IP 393개에 무단 사용됐습니다.",
    "harness": "하네스 설정(훅, settings.json, config.toml, 플러그인, oraena 설치본)을 AI가 바꾸지 마세요. 이유: AI가 자기 경계를 풀 수 있으면 경계가 아닙니다. 바꿀 내용과 명령을 사용자에게 보여 주세요.",
    "raw": "raw/의 기존 파일은 고치거나 옮기거나 지우지 마세요. 새 파일은 Write 도구로 만드세요. 이유: 원시 기록은 근거라서 바뀌면 안 됩니다.",
    "secret": "API 키·토큰 같은 비밀을 파일이나 커밋에 쓰지 마세요. 환경 변수나 커밋하지 않는 .env를 가리키게 하세요. 이유: 한 번 올라가면 회수할 수 없습니다.",
    "model": "Agent 호출에 model을 지정하세요(예: sonnet, opus). 이유: 지정하지 않아 쿼터 사고가 6번 났습니다.",
    "delete": "영구 삭제나 강제 덮어쓰기입니다. 대상을 확인하세요. 이유: 다른 작업 트리 파일 222개를 옮긴 사고가 있었습니다.",
    "outward": "외부로 내보내는 행동(push, PR, 게시, 메시지)입니다. 이유: 개인 기록이 나가는 마지막 관문입니다.",
    "system": "Windows 시스템 설정을 바꾸는 명령입니다. 이유: 되돌리기 어렵습니다.",
    "install": "전역 설치·삭제입니다. 이유: PC 전체 환경이 바뀝니다.",
}
CODEX_ASK = " Codex에는 확인 창이 없어 막았습니다. 명령을 사용자에게 보여 주고 직접 실행하게 하세요."

I = re.I | re.S


def _any(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), I)


# --- 막기 ---------------------------------------------------------------

TRAILER = re.compile(r"\bgit\b[^\n|;&]*?\bcommit\b.*Co-Authored-By", I)

FIREWALL = _any(
    r"\bNew-NetFirewallRule\b(?![^\n]*-Action\s+Block)",
    r"netsh\s+advfirewall\s+firewall\s+add\s+rule(?![^\n]*action\s*=\s*block)",
    r"\bEnable-NetFirewallRule\b",
    r"\bSet-NetFirewallRule\b[^\n]*-Enabled\s+True",
    r"netsh\s+advfirewall\s+set\s+\w+\s+state\s+off",
    r"\bSet-NetFirewallProfile\b[^\n]*-Enabled\s+False",
)
SCRIPT_FILE = re.compile(r"\.(?:ps1|psm1|bat|cmd|sh)$", re.I)

BIND_SHELL = _any(
    r"--host[= ]+['\"]?0\.0\.0\.0",
    r"\s-H\s+0\.0\.0\.0",
    r"--bind[= ]+['\"]?0\.0\.0\.0",
    r"\bOLLAMA_HOST\s*=\s*['\"]?0\.0\.0\.0",
    r"bind-address\s*=\s*0\.0\.0\.0",
    r"\s-p\s+0\.0\.0\.0:",
    r"docker\s+run[^\n]*\s(?:-p|--publish)\s+(?!127\.0\.0\.1:)\d",
)
BIND_FILE = _any(
    r"\bhost\s*[=:]\s*['\"]0\.0\.0\.0",
    r"\blisten\([^)]*['\"]0\.0\.0\.0",
    r"bind-address\s*=\s*0\.0\.0\.0",
    r"\bOLLAMA_HOST\s*[=:]\s*['\"]?0\.0\.0\.0",
    r"--host[= ]+['\"]?0\.0\.0\.0",
)
DOC_FILE = re.compile(r"\.(?:md|txt|rst|jsonl|log)$", re.I)

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
# 앞 문자열의 닫는 따옴표와 뒤 문자열의 여는 따옴표를 짝지어 명령을 지웠다(2026-10-13).
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

SECRET = _any(
    r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}",
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{50,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bAIza[0-9A-Za-z_-]{35}\b",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    r"\bgsk_[A-Za-z0-9]{40,}",
    r"\bhf_[A-Za-z0-9]{30,}",
    r"\b[rs]k_live_[A-Za-z0-9]{20,}",
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
)
SECRET_ASSIGN = re.compile(
    r"(?:api[_-]?key|secret|token|password|passwd)['\"]?\s*[:=]\s*['\"]([A-Za-z0-9_\-/+=.]{24,})['\"]", re.I)
PLACEHOLDER = re.compile(r"example|your|xxxx|placeholder|dummy|sample|changeme|redacted|<|\.\.\.", re.I)
GIT_COMMIT = re.compile(r"\bgit\b[^\n|;&]*?\bcommit\b", re.I)

# --- 확인 ---------------------------------------------------------------

# 폴더째 지우기와 덮어쓰며 옮기기. 대상이 모두 임시 폴더면 묻지 않는다.
# 파일 하나 지우기(rm, Remove-Item)와 복사 덮어쓰기는 묻지 않는다. 기본 동작이 이미 덮어쓰기라
# -f/-Force가 위험을 더하지 않는다(지난 30일 재생에서 묻기의 절반이 이것이었다).
DELETE_FS = _any(
    r"(?:^|[\s;&|(])rm\s+(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b(?![^\n;|&]*--cached)",
    r"\b(?:Remove-Item|ri)\b[^\n|;]*\s-(?:Recurse|r)\b",
    r"\b(?:rmdir|rd)\s+/s\b",
    r"\b(?:del|erase)\s+[^\n]*/s\b",
    r"(?:^|[\s;&|(])mv\s+-[a-zA-Z]*f",
    r"\b(?:Move-Item|mi)\b[^\n|;]*\s-Force\b",
    r"\bshutil\.rmtree\b",
    r"\brobocopy\b[^\n]*/(?:MIR|PURGE)\b",
)
# 저장소의 커밋하지 않은 변경이나 이력을 버리는 git 명령과 되돌릴 수 없는 지우기.
DELETE_HARD = _any(
    r"\bgit\s+clean\b[^\n]*\s-[a-z]*f",
    r"\bgit\s+reset\b[^\n]*--hard\b",
    r"\bgit\s+checkout\s+(?:--\s|-f\b|--force\b|\.(?:\s|$))",
    r"\bgit\s+restore\b(?![^\n;|&]*--staged)",
    r"\bgit\s+push\b[^\n]*(?:--force|\s-f\b|\s\+\S)",
    r"\bgit\s+branch\s+(?-i:-D)\b|\bgit\s+branch\b[^\n]*--delete\s+--force",
    r"\bgit\s+stash\s+(?:drop|clear)\b",
    r"\bgit\s+worktree\s+remove\b[^\n]*--force",
    r"\bClear-RecycleBin\b",
    r"\bformat\s+[a-z]:|\bClear-Disk\b|\bFormat-Volume\b|\bdiskpart\b",
)
TEMP_MARK = re.compile(r"/temp/|/temp$|/tmp/|scratchpad|\$env:temp|%temp%|gettemppath|mktemp|tempfile", re.I)
OUTWARD = _any(
    r"\bgit\s+push\b",
    r"\bgh\s+pr\s+(?:create|merge|comment|review|close|edit|ready|reopen)\b",
    r"\bgh\s+issue\s+(?:create|comment|close|edit|reopen|delete)\b",
    r"\bgh\s+(?:release\s+(?:create|upload|edit|delete)|repo\s+(?:create|edit|delete|rename|fork)|gist\s+(?:create|edit))\b",
    r"\bgh\s+api\b[^\n]*(?:-X\s*(?:POST|PUT|PATCH|DELETE)|--method\s+(?:POST|PUT|PATCH|DELETE)|\s-[fF]\s|--(?:raw-)?field|--input)",
    r"\b(?:npm|pnpm|yarn|uv|poetry|cargo)\s+publish\b|\btwine\s+upload\b|\b(?:docker|gem)\s+push\b",
    r"\b(?:vercel|netlify|firebase|wrangler|fly)\b[^\n]*\b(?:deploy|publish)\b|\bvercel\b[^\n]*--prod",
    r"\bSend-MailMessage\b",
    r"(?:^|[\s;&|(])(?:scp|sftp)\s",
)
HTTP_WRITE = _any(
    r"\bcurl\b[^\n]*(?:-X\s*(?:POST|PUT|PATCH|DELETE)|--request\s+(?:POST|PUT|PATCH|DELETE)|\s-d\s|--data|\s-F\s|--form|\s-T\s|--upload-file)",
    r"\b(?:Invoke-RestMethod|Invoke-WebRequest|irm|iwr)\b[^\n]*-Method\s+['\"]?(?:Post|Put|Patch|Delete)",
)
URL_HOST = re.compile(r"https?://([^/\s'\":?]+)", re.I)
LOCAL_HOST = re.compile(r"^(?:localhost|127\.\d+\.\d+\.\d+|\[::1\]|0\.0\.0\.0|[\w.-]+\.(?:localhost|test))$", re.I)

SYSTEM = _any(
    r"\breg(?:\.exe)?\s+(?:add|delete|import|restore|load|unload|copy)\b",
    r"\b(?:Set|New|Remove|Rename|Clear)-ItemProperty\b[^\n]*(?:HK(?:LM|CU|CR|U|CC)[:\\]|Registry::)",
    r"\b(?:New-Item|Remove-Item|Set-Item)\b[^\n]*(?:HK(?:LM|CU|CR|U|CC):|Registry::)",
    r"\bbcdedit\b|\bSet-ExecutionPolicy\b|(?:^|[\s;&|(])setx\s",
    r"\[(?:System\.)?Environment\]::SetEnvironmentVariable\([^)]*(?:Machine|User)",
    r"\b(?:Set|New|Remove|Stop|Restart|Start|Suspend)-Service\b|\bsc(?:\.exe)?\s+(?:config|create|delete|stop|start)\b",
    r"\bnet\s+(?:stop|start)\b|\bnet\s+(?:user|localgroup)\b[^\n]*\s/(?:add|delete|del|active)\b",
    r"\b(?:Enable|Disable)-WindowsOptionalFeature\b|\bdism(?:\.exe)?\s|\b(?:Add|Remove)-WindowsCapability\b",
    r"\bschtasks(?:\.exe)?\s+/(?:create|delete|change)\b|\b(?:Register|Unregister|Set|Disable|Enable)-ScheduledTask\b",
    r"\bpowercfg\b|\bSet-(?:NetIPAddress|NetIPInterface|DnsClientServerAddress|NetAdapter\w*|NetConnectionProfile)\b",
    r"\bnetsh\s+(?:interface|int|winhttp|wlan|advfirewall)\b|\b(?:New|Set|Remove|Disable)-NetFirewall\w+\b",
    r"\b(?:Set|Add|Remove)-MpPreference\b",
    r"\btakeown\b|\bicacls\b[^\n]*/(?:grant|deny|reset|setowner)",
    r"\b(?:Restart|Stop)-Computer\b|\bshutdown(?:\.exe)?\s+/[rsp]\b|\bRename-Computer\b|\bSet-TimeZone\b|\btzutil\s+/s\b",
    r"\b(?:Disable|Enable)-ComputerRestore\b|\bvssadmin\s+delete\b",
    r"\bwsl(?:\.exe)?\s+--(?:unregister|install|set-default-version)\b",
)
INSTALL = _any(
    r"\b(?:npm|pnpm)\s+(?:i|install|add|uninstall|un|rm|remove|update|up|link)\b[^\n]*(?:\s-g\b|--global\b|--location[= ]global)",
    r"\byarn\s+global\s+(?:add|remove|upgrade)\b|\bbun\s+(?:add|install|remove|i)\b[^\n]*(?:\s-g\b|--global\b)",
    r"\buv\s+tool\s+(?:install|uninstall|upgrade)\b|\buv\s+python\s+(?:install|uninstall)\b",
    r"\bpipx\s+(?:install|uninstall|upgrade|reinstall|inject)\b",
    r"\b(?:winget|choco|scoop)\s+(?:install|uninstall|upgrade|remove|update)\b",
    r"\b(?:Install|Uninstall|Update)-(?:Module|Package|Script|PSResource)\b",
    r"\b(?:cargo|go|gem)\s+(?:install|uninstall)\b|\bdotnet\s+tool\s+(?:install|uninstall|update)\b[^\n]*(?:-g\b|--global)",
    r"\bmsiexec\b|\b(?:Add|Remove)-AppxPackage\b",
)
# 가상 환경 밖의 pip. 명령에 venv가 보이면 전역이 아니다.
PIP_GLOBAL = re.compile(r"(?:^|[\s;&|(])(?:pip3?|py\s+-m\s+pip|python3?\s+-m\s+pip)\s+(?:install|uninstall)\b", re.I)
VENV = re.compile(r"venv|virtualenv|conda|--target|--prefix|\buv\s+pip\b", re.I)

# 이 PC 안에서만 움직이는 MCP 서버. 여기 밖의 서버에서 바꾸는 도구는 외부로 내보내기로 본다.
LOCAL_MCP = re.compile(
    r"desktop.?commander|ccd_|computer-use|claude_browser|claude-in-chrome|playwright|chrome-devtools"
    r"|blender|pdf-viewer|terminal|visualize|scheduled-tasks|mcp-registry|^oraena$", re.I)
MCP_MUTATE = re.compile(
    r"(?:^|[_-])(?:create|update|send|post|publish|reply|forward|share|comment|upload|delete|trash|move|label"
    r"|archive|sync|put|duplicate|restore|spawn|stop|set|write|apply|mark|import|generate|batch|resolve|role"
    r"|invite|add|remove|edit|insert|submit)(?:[_-]|$)", re.I)
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
SKIP_TOKEN = re.compile(r"^(?:-.*|/[A-Za-z]{1,10}|\d?>.*|[{}()]+|&|\|)$")
PARAM_WITH_VALUE = re.compile(r"^-(?:ErrorAction|ea|WarningAction|wa)$", re.I)


TEXT_SINK = re.compile(r"\bgit\b[^\n]*\bcommit\b|\b(?:cat|tee)\b|\bgh\b", re.I)


def drop_text_heredocs(cmd: str) -> str:
    """커밋 메시지·파일 내용처럼 글로 넘기는 heredoc 본문을 뺀다. 실행되는 본문(python - 등)은 남긴다.

    2026-10-13 커밋 메시지의 영어 낱말 "move"가 Windows move 명령으로 읽혀 raw/ 보호에 잘못 걸렸다.
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


def _temp_only(text: str, values: dict[str, str], cwd_is_temp: bool) -> bool:
    """지우기 명령의 대상이 모두 임시 폴더인가. text는 명령 낱말부터 시작한다."""
    targets: list[str] = []
    skip = False
    for tok in TOKEN.findall(text)[1:]:
        if skip:
            skip = False
            continue
        if PARAM_WITH_VALUE.match(tok):
            skip = True
            continue
        if not SKIP_TOKEN.match(tok):
            targets.append(_shell_norm(expand(tok, values)).strip("'\""))
    if not targets:
        return False
    return all(TEMP_MARK.search(t) or (cwd_is_temp and not re.match(r"[a-z]:|/|~|\$", t)) for t in targets)


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

def _raw_dir() -> tuple[str, str] | None:
    try:
        from oraena import config
        root = config.data_root()
    except Exception:
        return None
    return norm(str(root)), norm(str(config.raw(root)))


def _under(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


def _has_secret(text: str) -> bool:
    if SECRET.search(text):
        return True
    return any(not PLACEHOLDER.search(m.group(1)) and re.search(r"\d", m.group(1)) and re.search(r"[A-Za-z]", m.group(1))
               for m in SECRET_ASSIGN.finditer(text))


def _outward_url(cmd: str) -> bool:
    hosts = URL_HOST.findall(cmd)
    return not hosts or any(not LOCAL_HOST.match(h) for h in hosts)


def judge(act: Action) -> list[Hit]:
    hits: list[Hit] = []

    def hit(rule: str, level: str = DENY) -> None:
        if all(h.rule != rule for h in hits):
            hits.append(Hit(rule, level, SAY[rule]))

    raw = _raw_dir()
    cwd = norm(act.cwd) if act.cwd else ""
    cwd_is_temp = bool(TEMP_MARK.search(cwd + "/"))

    for full in act.shell:
        # 트레일러·비밀·방화벽·바인드는 글 본문까지 본다. 나머지는 글로 넘기는 heredoc 본문을 빼고 본다.
        cmd = drop_text_heredocs(full)
        values = variables(cmd)
        segs = segments(cmd)
        low = _shell_norm(expand(cmd, values))
        if TRAILER.search(full):
            hit("trailer")
        if FIREWALL.search(full):
            hit("firewall")
        if BIND_SHELL.search(full):
            hit("bind")
        if (any(HARNESS_SHELL.search(s) and not HELP.search(s) for s in segments(_strip_phrases(cmd)))
                or _writes_to(cmd, segs, values, lambda s: bool(HARNESS_PATH.search(s)))):
            hit("harness")
        if DISABLE_HOOKS.search(cmd) and (any(DISABLE_HOOKS.search(s) and SHELL_WRITE.search(s) for s in segs)
                                          or REDIRECT_TARGET.search(low)):
            hit("harness")
        if raw:
            root_dir, raw_dir = raw
            rel = _under(cwd, root_dir)

            def in_raw(s: str, raw_dir=raw_dir, rel=rel) -> bool:
                return raw_dir + "/" in s or (rel and re.search(r"(?:^|[\s'\"=(])(?:\./)?raw/", s) is not None)
            if _writes_to(cmd, segs, values, in_raw):
                hit("raw")
        if _has_secret(full) and (GIT_COMMIT.search(full) or SHELL_WRITE.search(full) or REDIRECT_TARGET.search(low)
                                  or full != cmd):
            hit("secret")
        for seg in segs:
            m = DELETE_FS.search(seg)
            if m and not _temp_only(seg[m.start():], values, cwd_is_temp):
                hit("delete", ASK)
        if DELETE_HARD.search(cmd):
            hit("delete", ASK)
        if OUTWARD.search(cmd) or (HTTP_WRITE.search(cmd) and _outward_url(cmd)):
            hit("outward", ASK)
        if SYSTEM.search(cmd) and not FIREWALL.search(full):
            hit("system", ASK)
        if (INSTALL.search(cmd) or (PIP_GLOBAL.search(cmd) and not VENV.search(cmd))) and not HARNESS_SHELL.search(cmd):
            hit("install", ASK)

    text = "\n".join(act.content)
    for op, path in act.writes:
        if HARNESS_PATH.search(path) or (path.endswith(".json") and DISABLE_HOOKS.search(text)):
            hit("harness")
        if raw and _under(path, raw[1]) and (op in ("edit", "update", "delete") or os.path.exists(path)):
            hit("raw")
        if SCRIPT_FILE.search(path) and FIREWALL.search(text):
            hit("firewall")
        if not DOC_FILE.search(path) and BIND_FILE.search(text):
            hit("bind")
    if act.writes and _has_secret(text):
        hit("secret")

    if act.host == "claude":
        if act.tool in ("Agent", "Task") and not act.input.get("model"):
            hit("model")
        if act.tool == "Workflow":
            script = str(act.input.get("script") or "")
            if re.search(r"\bagent\(", script) and not re.search(r"\bmodel\s*:", script):
                hit("model")

    if act.tool.startswith("mcp__"):
        server, _, short = act.tool[5:].rpartition("__")
        if not LOCAL_MCP.search(server) and MCP_MUTATE.search(short):
            hit("outward", ASK)
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
