"""턴 끝 훅.

1. 이번 턴에 "쓸 스킬: X"라고 밝히고 X의 SKILL.md를 읽지 않았으면 한 번 멈추지 않게 하고 알린다.
2. 작업 폴더에 인수인계서가 있는데 이번 세션에 파일을 바꾸고 인수인계서를 고치지 않았으면 세션당 한 번 알린다.
3. 데이터 폴더에 바뀐 것이 있으면 목차를 다시 만들고 로컬 git에 커밋한다(원격 없음, 설계서 6절 결정 3).

반복 상한: 호스트가 이미 한 번 이어 가게 한 턴(stop_hook_active)에는 다시 막지 않는다.
Codex에는 호스트 상한이 보이지 않아 스킬 알림도 세션당 3번으로 묶는다.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from oraena import index, localgit, skills, state, transcripts
from oraena.hooks.run import block, data_root

DECLARE = re.compile(r"쓸\s*스킬\s*[:：]\s*([^\n]+)")
NAME = re.compile(r"[A-Za-z0-9][\w.:-]*")
SKILL_BLOCK_LIMIT = 3


HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")
CODE = re.compile(r"```.*?```|`[^`\n]*`|https?://\S+|[A-Za-z]:[\\/]\S+", re.S)


def english_reply(prompt: str, reply: str) -> bool:
    """한국어 발화에 영어 답인가. 코드·경로·주소는 빼고 글자 수로 판정한다.

    2026-10-13 같은 세션에서 "한국어로" 교정이 두 번 연달아 나왔다. 기계가 판정할 수 있어 훅으로 옮겼다.
    """
    if not HANGUL.search(prompt or ""):
        return False
    body = CODE.sub(" ", reply or "")
    hangul, latin = len(HANGUL.findall(body)), len(LATIN.findall(body))
    return latin >= 200 and hangul < latin * 0.25


def check_skills(root: Path, turn: transcripts.Turn, data: dict) -> tuple[list[str], list[str]]:
    """(이번 턴에 밝힌 스킬, 그중 SKILL.md를 읽지 않은 스킬)."""
    texts = turn.texts + [str(data.get("last_assistant_message") or "")]
    declared: list[str] = []
    for text in texts:
        for m in DECLARE.finditer(text):
            declared += NAME.findall(m.group(1))
    known = {s.name: s for s in skills.all_skills(root)}
    declared = [n for n in dict.fromkeys(declared) if n in known]
    if not declared:
        return [], []
    # Codex 코드 모드 JS 안의 경로는 이스케이프가 겹친다. 구분자 덩어리를 / 하나로 접는다.
    blob = re.sub(r"[\\/]+", "/", "\n".join(json.dumps(c.input, ensure_ascii=False) for c in turn.tools)).lower()
    invoked = {str(c.input.get("skill", "")).split(":")[-1] for c in turn.tools if c.name == "Skill"}
    unread = [n for n in declared
              if n not in invoked and f"{known[n].path.parent.name.lower()}/skill.md" not in blob]
    return declared, unread


def commit(root: Path, host: str, sid: str) -> None:
    try:
        changed = localgit.changed(root)
        if not changed:
            return
        if any(p.startswith("wiki/") for p in changed):
            index.build(root)
        if any(p.startswith(("wiki/", "agent/")) for p in changed):
            from oraena import install
            install.refresh_codex_block(root)  # Codex는 가져오기가 없어 지침·지도를 글로 넣어 둔다
        localgit.commit(root, f"{host} 세션 {sid[:8]} 기록")
    except (OSError, subprocess.SubprocessError):
        pass  # 다른 세션이 동시에 커밋하면 잠금에 걸린다. 다음 턴 끝에 다시 한다.


def handle(host: str, data: dict) -> dict | None:
    root = data_root()
    if root is None:
        return None
    sid = str(data.get("session_id") or "")
    st = state.load(root, host, sid)
    reasons = []
    if not data.get("stop_hook_active"):
        turn = transcripts.last_turn(host, data.get("transcript_path"))
        reply = str(data.get("last_assistant_message") or (turn.texts[-1] if turn.texts else ""))
        if english_reply(turn.prompt, reply):
            reasons.append("사용자는 한국어로 말했는데 답이 영어입니다. 같은 내용을 한국어로 다시 쓰세요. "
                           "이유: 사용자 규칙이고 같은 교정이 반복됐습니다.")
        declared, missing = check_skills(root, turn, data)
        if declared:
            # 압축 뒤 세션 시작 훅이 이 스킬 경로를 다시 알린다(독립 검토 14번).
            st["skills"] = sorted(set(st.get("skills", [])) | set(declared))
        if missing and st.get("skill_blocks", 0) < SKILL_BLOCK_LIMIT:
            st["skill_blocks"] = st.get("skill_blocks", 0) + 1
            reasons.append(f"'쓸 스킬'로 밝힌 {', '.join(missing)}의 SKILL.md를 읽지 않았습니다. "
                           "읽고 그 절차대로 했는지 확인하세요. 이유: 스킬은 읽어야 효과가 있습니다.")
        handoff = st.get("handoff")
        if handoff and st.get("wrote") and not st.get("reminded"):
            try:
                touched = Path(handoff).stat().st_mtime >= st.get("started", time.time())
            except OSError:
                touched = True
            if not touched:
                st["reminded"] = True
                reasons.append(f"이번 세션에 파일을 바꿨는데 인수인계서({handoff})를 고치지 않았습니다. "
                               "'지금 위치'와 '다음 작업'만 고쳐 쓰세요. 이유: 다음 세션이 여기서 시작합니다.")
    state.save(root, host, sid, st)
    commit(root, host, sid)
    return block(" ".join(reasons)) if reasons else None
