"""Codex apply_patch 본문에서 바꾸는 파일 경로를 뽑는다.

0.3은 이것을 하지 않아 Codex의 파일 수정이 경로 규칙을 우회했다(2차 리뷰 H1).
"""

from __future__ import annotations

import re

HEADER = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M)


def operations(text: str) -> list[tuple[str, str]]:
    """[(add|update|delete|move, 경로)]."""
    out = []
    for m in HEADER.finditer(text or ""):
        if m.group(1):
            out.append((m.group(1).lower(), m.group(2)))
        else:
            out.append(("move", m.group(3)))
    return out


def added_text(text: str) -> str:
    """패치가 더하는 줄들(+로 시작)만 모은다. 비밀 검사에 쓴다."""
    return "\n".join(line[1:] for line in (text or "").splitlines()
                     if line.startswith("+") and not line.startswith("+++"))
