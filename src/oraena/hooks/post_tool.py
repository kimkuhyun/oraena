"""행동 뒤 훅.

- 위키 문서를 쓰면 OKF 형식을 검사해 문제만 알린다.
- 작업 폴더나 데이터 폴더의 파일을 바꿨다고 세션 상태에 적는다(턴 끝 인수인계서 알림이 쓴다).
- 데이터 폴더 검색이 비면 이름이 비슷한 위키 문서 3개를 알린다(설계서 3.3 찾기 실패).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from oraena import check, config, index, rules, state
from oraena.hooks.run import context, data_root

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"}
SEARCH_SHELL = re.compile(r"(?:^|[\s;&|(])(?:rg|grep|findstr|Select-String|sls)\b(.*)", re.I | re.S)
EMPTY = re.compile(r"^\s*$|No (?:files|matches) found", re.I)
WORD = re.compile(r"[0-9A-Za-z가-힣]{2,}")
NOISE = {"md", "the", "and", "or", "path", "type", "include", "glob", "rn"}
MAX_PROBLEMS = 5


def _empty(resp) -> bool:
    if isinstance(resp, dict):
        for key in ("numFiles", "numMatches", "numLines"):
            if key in resp:
                return not resp[key]
        if "filenames" in resp:
            return not resp["filenames"] and not resp.get("content")
        for key in ("stdout", "output", "content", "result"):
            if key in resp:
                return bool(EMPTY.match(str(resp[key] or "")))
        return False
    if isinstance(resp, list):
        return not resp
    return bool(EMPTY.match(str(resp or "")))


def _shell_query(cmd: str) -> str:
    m = SEARCH_SHELL.search(cmd)
    if not m:
        return ""
    rest = m.group(1)
    q = re.search(r"\"([^\"]+)\"|'([^']+)'", rest)
    if q:
        return q.group(1) or q.group(2)
    tokens = [t for t in rest.split() if not t.startswith("-")]
    return tokens[0] if tokens else ""


def similar(root: Path, query: str, n: int = 3) -> list[index.Entry]:
    words = [w.lower() for w in WORD.findall(query) if w.lower() not in NOISE]
    if not words:
        return []
    scored = []
    for e in index.catalog(root):
        hay = " ".join([e.title, e.description, " ".join(e.aliases), e.path]).lower()
        score = sum(1 for w in words if w in hay)
        if score:
            scored.append((-score, e.path, e))
    return [e for *_, e in sorted(scored, key=lambda x: (x[0], x[1]))[:n]]


def handle(host: str, data: dict) -> dict | None:
    root = data_root()
    if root is None:
        return None
    tool = str(data.get("tool_name") or "")
    ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    cwd = str(data.get("cwd") or os.getcwd())
    root_n, cwd_n = rules.norm(str(root)), rules.norm(cwd)

    if tool in WRITE_TOOLS or (tool.startswith("mcp__") and rules.MCP_FILE_TOOL.search(tool.rsplit("__", 1)[-1])):
        act = rules.action_of(host, tool, ti, cwd)
        paths = [p for op, p in act.writes if op != "delete"]
        if any(rules._under(p, cwd_n) or rules._under(p, root_n) for p in paths):
            sid = str(data.get("session_id") or "")
            if not state.load(root, host, sid).get("wrote"):
                state.update(root, host, sid, wrote=True)
        wiki_n = rules.norm(str(config.wiki(root)))
        targets = [Path(p) for p in paths if p.endswith(".md") and rules._under(p, wiki_n)]
        problems = check.run(root, targets) if targets else []
        if not problems:
            return None
        lines = [f"- {Path(p.path).name} {p.code}: {p.message}" for p in problems[:MAX_PROBLEMS]]
        return context("PostToolUse", "위키 형식 문제를 고치세요. 이유: 목차와 찾기가 메타정보에 기댑니다.\n" + "\n".join(lines))

    query = ""
    if tool in ("Grep", "Glob") and _empty(data.get("tool_response")):
        where = rules.norm(str(ti.get("path") or cwd), cwd)
        if rules._under(where, root_n):
            query = str(ti.get("pattern") or "")
    elif tool in ("Bash", "PowerShell") and _empty(data.get("tool_response")):
        cmd = rules._command_text(ti.get("command"))
        if SEARCH_SHELL.search(cmd) and (root_n in rules._shell_norm(cmd) or rules._under(cwd_n, root_n)):
            query = _shell_query(cmd)
    found = similar(root, query) if query else []
    if not found:
        return None
    lines = [f"- {e.title} — {e.description[:80]} (wiki/{e.path})" for e in found]
    return context("PostToolUse", "검색 결과가 없습니다. 이름이 비슷한 위키 문서:\n" + "\n".join(lines))
