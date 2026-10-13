"""세션 시작 훅: 작업 폴더의 인수인계서를 싣는다. 압축 뒤에는 상시 지침과 지도도 다시 싣는다.

두 호스트 모두 이 훅으로 싣는다. Claude의 `CLAUDE.local.md` 가져오기는 쓰지 않는다.
이유: 작업 폴더 밖 가져오기는 프로젝트마다 승인 창이 뜨고 한 번 거절하면 영영 꺼진다.
그 파일이 있으면 그 폴더의 AGENTS.md를 읽지 않는다. gitignore 파일이라 다른 worktree에는 없다.
"""

from __future__ import annotations

import os
import time

from oraena import config, handoff, skills, state
from oraena.hooks.run import context, data_root


def handle(host: str, data: dict) -> dict | None:
    root = data_root()
    if root is None:
        return None
    sid = str(data.get("session_id") or "")
    source = str(data.get("source") or "startup")
    cwd = str(data.get("cwd") or os.getcwd())
    parts = []
    if source == "compact":
        # 압축 뒤 다시 실린다는 문서 보장이 없는 것을 넣는다(설계서 11절 G2).
        for path in (config.agent(root) / "AGENTS.md", config.wiki(root) / "index.md"):
            if path.exists():
                parts.append(path.read_text(encoding="utf-8").strip())
    found = handoff.find(root, cwd)
    if found and found.exists():
        parts.append(handoff.brief(found))
    if source == "startup":
        state.cleanup(root)
    st = state.load(root, host, sid)
    if source == "compact" and st.get("skills"):
        # 직접 부르기 전용 스킬은 Read로 읽어 호스트가 압축 뒤 다시 붙여 주지 않는다.
        paths = {s.name: s.path for s in skills.all_skills(root)}
        lines = [f"- {n}: {paths[n].as_posix()}" for n in st["skills"] if n in paths]
        if lines:
            parts.append("이 세션에서 쓴 스킬(압축으로 본문이 빠졌으면 다시 읽는다):\n" + "\n".join(lines))
    st.setdefault("started", time.time())
    st["handoff"] = str(found) if found else ""
    state.save(root, host, sid, st)
    if not parts:
        return None
    return context("SessionStart", "\n\n".join(parts))
