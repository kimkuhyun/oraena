"""발화 훅: 발화에 "스킬"이 있으면 스킬 목록을 넣는다(설계서 6절 결정 4).

스킬은 모두 직접 부르기 전용이라 목록이 세션에 실리지 않는다. 그래서 사용자가 스킬을 말할 때만 넣는다.
"""

from __future__ import annotations

from oraena import skills
from oraena.hooks.run import context, data_root

ASK = ("작업 전에 '쓸 스킬: 이름' 또는 '쓸 스킬: 없음' 한 줄을 먼저 쓰세요. "
       "고른 스킬은 SKILL.md를 읽고 따르세요. 이유: 턴 끝 훅이 읽었는지 확인합니다.")


def handle(host: str, data: dict) -> dict | None:
    if "스킬" not in str(data.get("prompt") or ""):
        return None
    root = data_root()
    if root is None:
        return None
    return context("UserPromptSubmit", f"스킬 목록:\n{skills.render(skills.find(root))}\n\n{ASK}")
