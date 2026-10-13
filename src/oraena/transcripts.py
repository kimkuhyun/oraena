"""Claude Code·Codex가 남긴 대화 기록을 같은 모양(Session)으로 읽는다.

사람이 친 발화만 prompts에 담는다. 훅·스킬·환경 정보가 넣은 글과, 다른 에이전트가 띄운
세션(Codex 하위 에이전트, exec, Claude가 부른 Codex)은 뺀다.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
CODEX_DIR = Path.home() / ".codex" / "sessions"

NOT_HUMAN_PREFIX = (
    "<", "# AGENTS.md instructions", "Base directory for this skill", "[Request interrupted",
    "Caveat:", "This session is being continued",
)
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


@dataclass
class ToolCall:
    name: str
    input: dict
    result: str = ""


@dataclass
class Session:
    host: str
    id: str
    cwd: str
    started: str
    prompts: list[str] = field(default_factory=list)
    tools: list[ToolCall] = field(default_factory=list)
    interrupts: int = 0
    hook_context_chars: int = 0  # 훅이 넣은 글자 수
    hook_blocks: list[str] = field(default_factory=list)  # 막힌 이유(앞부분)


def _human(text: str) -> str | None:
    text = REMINDER.sub("", text or "").strip()
    if not text or text.startswith(NOT_HUMAN_PREFIX):
        return None
    return text


def _recent(paths, days: int):
    cutoff = time.time() - days * 86400
    return [p for p in paths if p.stat().st_mtime >= cutoff]


def read_claude(path: Path) -> Session | None:
    s: Session | None = None
    pending: dict[str, ToolCall] = {}
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if s is None and d.get("sessionId"):
            s = Session("claude", d["sessionId"], d.get("cwd", ""), d.get("timestamp", ""))
        if s is None:
            continue
        kind = d.get("type")
        if kind == "user" and not d.get("isMeta"):
            content = d.get("message", {}).get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
            for b in blocks:
                if b.get("type") == "text":
                    if "[Request interrupted" in b.get("text", ""):
                        s.interrupts += 1
                    human = _human(b.get("text", ""))
                    if human:
                        s.prompts.append(human)
                elif b.get("type") == "tool_result":
                    call = pending.pop(b.get("tool_use_id", ""), None)
                    text = b.get("content")
                    if isinstance(text, list):
                        text = " ".join(x.get("text", "") for x in text if isinstance(x, dict))
                    text = str(text or "")
                    if call:
                        call.result = text[:500]
                    if b.get("is_error") and "hook" in text.lower():
                        s.hook_blocks.append(text[:200])
        elif kind == "assistant":
            for b in d.get("message", {}).get("content", []) or []:
                if b.get("type") == "tool_use":
                    call = ToolCall(b.get("name", ""), b.get("input") or {})
                    s.tools.append(call)
                    pending[b.get("id", "")] = call
        elif kind == "attachment":
            att = d.get("attachment") or {}
            if att.get("type") == "hook_additional_context":
                s.hook_context_chars += len(str(att.get("content", "")))
            elif att.get("type") == "hook_blocking_error":
                s.hook_blocks.append(str(att.get("blockingError") or att)[:200])
    return s


def read_codex(path: Path) -> Session | None:
    s: Session | None = None
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = d.get("payload") or {}
        if d.get("type") == "session_meta":
            source, origin = p.get("source"), str(p.get("originator") or "")
            if isinstance(source, dict) or source == "exec" or "claude" in origin.lower():
                return None  # 사람이 연 세션이 아니다
            s = Session("codex", p.get("id", path.stem), p.get("cwd", ""), p.get("timestamp", ""))
            continue
        if s is None or d.get("type") != "response_item":
            continue
        kind = p.get("type")
        if kind == "message" and p.get("role") == "user":
            for item in p.get("content", []):
                text = item.get("text", "")
                if text.startswith("<hook_prompt"):
                    s.hook_context_chars += len(text)
                human = _human(text)
                if human:
                    s.prompts.append(human)
        elif kind in CODEX_CALLS:
            s.tools.append(_codex_call(p))
    return s


CODEX_CALLS = ("function_call", "custom_tool_call", "local_shell_call")


def _codex_call(p: dict) -> ToolCall:
    raw = p.get("arguments") or p.get("input") or p.get("action") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {"text": raw}
    return ToolCall(p.get("name") or p.get("type", ""), raw if isinstance(raw, dict) else {"value": raw})


@dataclass
class Turn:
    """마지막 사람 발화 뒤의 모델 글과 도구 호출."""

    texts: list[str] = field(default_factory=list)
    tools: list[ToolCall] = field(default_factory=list)


TAIL_BYTES = 4_000_000  # 턴 끝 훅은 긴 대화 기록의 끝만 읽는다


def _tail(path: Path):
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            f.readline()
        data = f.read()
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def last_turn(host: str, transcript_path: str | None) -> Turn:
    turn = Turn()
    if not transcript_path or not Path(transcript_path).exists():
        return turn
    for d in _tail(Path(transcript_path)):
        if host == "codex":
            if d.get("type") != "response_item":
                continue
            p = d.get("payload") or {}
            kind = p.get("type")
            if kind == "message" and p.get("role") == "user":
                if any(_human(i.get("text", "")) for i in p.get("content", []) if isinstance(i, dict)):
                    turn = Turn()
            elif kind == "message" and p.get("role") == "assistant":
                turn.texts += [i.get("text", "") for i in p.get("content", []) if isinstance(i, dict) and i.get("text")]
            elif kind in CODEX_CALLS:
                turn.tools.append(_codex_call(p))
            continue
        kind = d.get("type")
        content = (d.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
        if kind == "user" and not d.get("isMeta"):
            if any(b.get("type") == "text" and _human(b.get("text", "")) for b in blocks if isinstance(b, dict)):
                turn = Turn()
        elif kind == "assistant":
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    turn.texts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    turn.tools.append(ToolCall(b.get("name", ""), b.get("input") or {}))
    return turn


def sessions(days: int = 30):
    for path in _recent(CLAUDE_DIR.glob("*/*.jsonl"), days):
        s = read_claude(path)
        if s and s.prompts:
            yield s
    for path in _recent(CODEX_DIR.rglob("*.jsonl"), days):
        s = read_codex(path)
        if s and s.prompts:
            yield s
