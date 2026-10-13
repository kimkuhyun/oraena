"""발화 훅.

- 발화에 열린 인수인계서의 이름·별칭이 있으면 그 인수인계서를 넣는다. 폴더 없이 시작한 세션도 이어받게 한다.
  세션당 인수인계서마다 한 번, 이미 실린 것은 다시 넣지 않는다.
- 발화에 "스킬"이 있으면 스킬 목록을 넣는다(설계서 6절 결정 4). 스킬은 모두 직접 부르기 전용이라
  목록이 세션에 실리지 않는다.
"""

from __future__ import annotations

import time

from oraena import handoff, skills, state, transcripts
from oraena.hooks.run import context, data_root

ASK = ("작업 전에 '쓸 스킬: 이름' 또는 '쓸 스킬: 없음' 한 줄을 먼저 쓰세요. "
       "고른 스킬은 SKILL.md를 읽고 따르세요. 이유: 턴 끝 훅이 읽었는지 확인합니다.")


def handle(host: str, data: dict) -> dict | None:
    root = data_root()
    if root is None:
        return None
    # 하위 에이전트 보고·작업 알림도 발화로 들어온다. 사람이 친 글만 본다(2026-10-13 보고문의 "구직"으로
    # 구직 인수인계서가 잘못 실린 일).
    prompt = transcripts._human(str(data.get("prompt") or "")) or ""
    if not prompt:
        return None
    sid = str(data.get("session_id") or "")
    parts = []
    st = state.load(root, host, sid)
    loaded = set(st.get("loaded", [])) | ({st["handoff"]} if st.get("handoff") else set())
    matches = [p for p in handoff.by_name(root, prompt) if str(p) not in loaded and p.exists()]
    if matches:
        first = matches[0]
        parts.append(handoff.brief(first))
        if len(matches) > 1:
            parts.append("이름이 맞은 다른 인수인계서: " + ", ".join(p.as_posix() for p in matches[1:3]))
        st["loaded"] = sorted(loaded | {str(first)})
        if not st.get("handoff"):
            st["handoff"] = str(first)  # 턴 끝 인수인계서 알림이 이 인수인계서를 본다
        st.setdefault("started", time.time())
        state.save(root, host, sid, st)
    if "스킬" in prompt:
        parts.append(f"스킬 목록:\n{skills.render(skills.find(root))}\n\n{ASK}")
    if not parts:
        return None
    return context("UserPromptSubmit", "\n\n".join(parts))
