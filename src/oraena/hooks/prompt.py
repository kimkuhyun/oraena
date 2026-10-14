"""발화 훅.

- 발화에 열린 인수인계서의 이름·별칭이 있으면 그 인수인계서를 넣는다. 폴더 없이 시작한 세션도 이어받게 한다.
  세션당 인수인계서마다 한 번, 이미 실린 것은 다시 넣지 않는다.
- 발화에 "스킬"이 있으면 스킬 목록을 넣는다(설계서 6절 결정 4). 스킬은 모두 직접 부르기 전용이라
  목록이 세션에 실리지 않는다.
- 발화에 교정 낱말(analyze.CORRECTION_CUE)이 있으면 교정 카드를 남기라고 알린다. 교정을 주간 정리까지
  미루지 않고 그 자리에서 잡는다. 교정인지는 AI가 가린다. 안내 전문은 세션에 한 번, 그 뒤로는 짧게 넣는다.
"""

from __future__ import annotations

import time

from oraena import config, handoff, skills, state, transcripts
from oraena.analyze import CORRECTION_CUE
from oraena.hooks.run import context, data_root

ASK = ("작업 전에 '쓸 스킬: 이름' 또는 '쓸 스킬: 없음' 한 줄을 먼저 쓰세요. "
       "고른 스킬은 SKILL.md를 읽고 따르세요. 이유: 턴 끝 훅이 읽었는지 확인합니다.")

CORRECTION_FULL = (
    "교정 확인: 이 발화가 AI의 행동이나 결과를 바로잡은 것이면 `{cards}/`에 교정 카드를 새 파일로 남기세요. "
    "새 요구, 질문, 승인, 사용자가 자기 말을 고친 것이면 아무것도 하지 마세요.\n"
    "- 파일: `{cards}/YYYY-MM-DD-HHMM-<짧은-이름>.md`. 메타정보는 date, action(바로잡은 행동 한 줄), "
    "repeat_of(같은 교정의 이전 카드 파일 이름, 없으면 비움), proposal(옮길 곳 제안, 처음이면 비움). "
    "본문은 발화 원문 인용(`> `)과 요지 한 줄.\n"
    "- 쓰기 전에 `{cards}/`에서 같은 행동을 바로잡은 카드를 찾으세요. 있으면 두 번째이므로 옮길 곳 하나를 "
    "이번 턴에 사용자에게 제안하고 proposal에 적으세요. 위에서부터 처음 맞는 곳입니다: "
    "(1) 이미 있는 지침 줄 수정·삭제 (2) 기계가 판정할 수 있으면 정책 규칙 제안 파일(`{proposals}/`) "
    "(3) 몰라서 틀렸으면 위키 (4) 되풀이하는 절차면 스킬 제안 (5) 그 밖의 선호는 상시 지침.\n"
    "- 스킬 제안: `{proposals}/YYYY-MM-DD-HHMM-skill-<이름>.md`에 메타정보 kind: skill, name, description, "
    "evidence(근거가 된 대화나 카드 두 건)와 본문 '절차', '실제로 겪은 실패'를 쓰고 사용자에게 만들지 물으세요. "
    "승인하면 `agent/skills/<이름>/SKILL.md`로 만듭니다(메타정보에 disable-model-invocation: true). "
    "모델 지식만으로 쓰지 마세요.\n"
    "이유: 교정을 그 자리에서 남겨야 다음에 같은 교정을 알아보고 옮길 수 있습니다."
)
CORRECTION_SHORT = "교정 확인: 교정이면 앞의 안내대로 `{cards}/`에 카드를 남기세요. 아니면 무시하세요."


def correction_hint(root, st: dict, prompt: str) -> str:
    """교정 낱말이 있으면 카드 안내를 돌려준다. st에 안내한 횟수를 남긴다."""
    if not CORRECTION_CUE.search(prompt[:300]):
        return ""
    raw = config.raw(root).as_posix()
    shown = st.get("correction_hints", 0)
    st["correction_hints"] = shown + 1
    template = CORRECTION_SHORT if shown else CORRECTION_FULL
    return template.format(cards=f"{raw}/corrections", proposals=f"{raw}/proposals")


def handle(host: str, data: dict) -> dict | None:
    root = data_root()
    if root is None:
        return None
    # 하위 에이전트 보고·작업 알림도 발화로 들어온다. 사람이 친 글만 본다(보고문에 든 낱말로
    # 엉뚱한 인수인계서가 실리지 않게).
    prompt = transcripts._human(str(data.get("prompt") or "")) or ""
    if not prompt:
        return None
    sid = str(data.get("session_id") or "")
    parts = []
    st = state.load(root, host, sid)
    changed = False
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
        changed = True
    if "스킬" in prompt:
        parts.append(f"스킬 목록:\n{skills.render(skills.find(root))}\n\n{ASK}")
    hint = correction_hint(root, st, prompt)
    if hint:
        parts.append(hint)
        changed = True
    if changed:
        state.save(root, host, sid, st)
    if not parts:
        return None
    return context("UserPromptSubmit", "\n\n".join(parts))
