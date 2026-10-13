"""훅 입출력. 호스트가 `oraena hook <사건> --host claude|codex`로 부른다.

stdin의 JSON을 읽어 사건 모듈의 `handle(host, data)`에 넘기고, 돌려받은 JSON을 ASCII로 낸다.
두 호스트 모두 훅이 실패하면 도구 호출을 그대로 진행한다. 그래서 행동 직전 판정은 이 안에서
오류를 잡아 막는다. 나머지 사건은 실패해도 조용히 지나간다(알림이 빠질 뿐이다).
"""

from __future__ import annotations

import importlib
import json
import sys

EVENTS = {
    "pre-tool": "oraena.hooks.pre_tool",
    "session-start": "oraena.hooks.session",
    "prompt": "oraena.hooks.prompt",
    "post-tool": "oraena.hooks.post_tool",
    "stop": "oraena.hooks.stop",
}


def deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def ask(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                   "permissionDecisionReason": reason}}


def context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def block(reason: str) -> dict:
    """턴 끝(Stop)에서 멈추지 말고 이어 하게 한다. reason은 모델에게 간다."""
    return {"decision": "block", "reason": reason}


def data_root():
    """데이터 폴더. 정해지지 않았거나 없으면 None(훅은 조용히 지나간다)."""
    from oraena import config
    try:
        root = config.data_root()
    except config.NotConfigured:
        return None
    return root if root.exists() else None


def emit(obj: dict) -> None:
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=True).encode("ascii"))
    sys.stdout.buffer.flush()


def read_input() -> dict:
    text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    data = json.loads(text) if text.strip() else {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in EVENTS:
        sys.stderr.write("사용법: oraena hook <" + "|".join(EVENTS) + "> --host claude|codex\n")
        return 0
    event = argv[0]
    host = "codex" if "--host" in argv and argv[argv.index("--host") + 1:][:1] == ["codex"] else "claude"
    try:
        out = importlib.import_module(EVENTS[event]).handle(host, read_input())
    except Exception as exc:  # 훅은 어떤 경우에도 비정상 종료하지 않는다
        if event == "pre-tool":
            out = deny(f"oraena 판정 중 오류가 나서 막았습니다({type(exc).__name__}: {exc}). 사용자에게 알리세요.")
        else:
            sys.stderr.write(f"oraena hook {event}: {type(exc).__name__}: {exc}\n")
            out = None
    if out:
        emit(out)
    return 0
