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
# 인수인계서 없이 이만큼 일한 세션은 남길지 한 번 묻는다. 프로젝트만이 아니라 조사·대화·브레인스토밍도
# 이어갈 일이 될 수 있어서, 종류를 가리지 않고 AI가 셋 중 하나를 고르게 한다.
RECORD_AFTER_TURNS = 3
RECORD_ASK = (
    "이 세션은 연결된 인수인계서 없이 {turns}턴 일했습니다. 셋 중 하나를 고르세요. "
    "(1) 이어갈 일(프로젝트·조사·대화·브레인스토밍)이면 인수인계서를 씁니다: "
    "`wiki/projects/<이름>/handoff.md`, type: Handoff, aliases에 사용자가 부를 이름, 작업 폴더가 있으면 work_folder. "
    "(2) 다시 쓸 사실이면 위키 문서로 씁니다. (3) 둘 다 아니면 아무것도 쓰지 않고 '기록할 것 없음' 한 줄로 끝냅니다. "
    "이유: 다음 세션이 이어받을 곳이 없습니다."
)


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
        st["turns"] = st.get("turns", 0) + 1
        if not handoff and not st.get("asked_record") and st["turns"] >= RECORD_AFTER_TURNS:
            st["asked_record"] = True
            reasons.append(RECORD_ASK.format(turns=st["turns"]))
    state.save(root, host, sid, st)
    commit(root, host, sid)
    return block(" ".join(reasons)) if reasons else None
