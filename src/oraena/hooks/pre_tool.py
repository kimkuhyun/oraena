"""행동 직전 훅: 반드시 목록 11개를 판정해 막거나 묻는다. 위키 문서를 처음 쓸 때 쓰기 안내를 한 번 넣는다.

쓰기 안내를 경로 규칙(`paths:`)이 아니라 훅으로 넣는 이유: 사용자 규칙의 경로가 작업 폴더 밖 OKF 파일에
걸린다는 근거가 없고(독립 검토 6번), Codex에는 경로 규칙이 없다. 두 호스트가 같은 방식을 쓴다.
"""

from __future__ import annotations

from oraena import rules
from oraena.hooks.run import ask, context, data_root, deny


def handle(host: str, data: dict) -> dict | None:
    act = rules.action_of(host, str(data.get("tool_name") or ""), data.get("tool_input") or {},
                          str(data.get("cwd") or ""))
    verdict = rules.decide(rules.judge(act), host)
    if verdict:
        level, reason = verdict
        return deny(reason) if level == rules.DENY else ask(reason)
    try:
        return _wiki_guide(host, data, act)
    except Exception:
        return None  # 안내는 실패해도 행동을 막지 않는다


def _wiki_guide(host: str, data: dict, act: rules.Action) -> dict | None:
    if not act.writes:
        return None
    root = data_root()
    if root is None:
        return None
    from oraena import config, okf, state
    wiki = rules.norm(str(config.wiki(root)))
    if not any(p.endswith(".md") and rules._under(p, wiki) for _op, p in act.writes):
        return None
    sid = str(data.get("session_id") or "")
    if state.load(root, host, sid).get("wiki_guide"):
        return None
    guide = config.agent(root) / "rules" / "okf-writing.md"
    if not guide.exists():
        return None
    state.update(root, host, sid, wiki_guide=True)
    return context("PreToolUse", "위키 쓰기 안내(세션에 한 번):\n" + okf.read(guide).body.strip())
