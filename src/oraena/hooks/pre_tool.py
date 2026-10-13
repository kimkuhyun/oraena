"""행동 직전 훅: 반드시 목록 11개를 판정해 막거나 묻는다."""

from __future__ import annotations

from oraena import rules
from oraena.hooks.run import ask, deny


def handle(host: str, data: dict) -> dict | None:
    act = rules.action_of(host, str(data.get("tool_name") or ""), data.get("tool_input") or {},
                          str(data.get("cwd") or ""))
    verdict = rules.decide(rules.judge(act), host)
    if not verdict:
        return None
    level, reason = verdict
    return deny(reason) if level == rules.DENY else ask(reason)
