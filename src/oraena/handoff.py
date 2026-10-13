"""작업 폴더의 인수인계서를 찾고, 세션에 실을 만큼 줄인다.

인수인계서 메타정보의 `work_folder`가 작업 폴더와 같거나 그 위 폴더면 그 인수인계서다.
git worktree에서는 주 작업 트리 경로로 한 번 더 찾는다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from oraena import config, index, okf

BUDGET = 1000  # 토큰(추정). 설계서 3.3
# 앞에 둘수록 먼저 싣는다. 0.3 제목(현재 상황, 주의할 점)도 받는다.
SECTION_ORDER = (r"지금 위치|현재 상황", r"다음 작업", r"정한 것|주의할 점")
HEADING = re.compile(r"^##\s+(.+?)\s*$", re.M)


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").rstrip("/").lower()


def _main_worktree(cwd: str) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return str(Path(out.stdout.strip()).parent)


def find(root: Path, cwd: str) -> Path | None:
    entries = [e for e in index.catalog(root)
               if e.type == "Handoff" and e.work_folder and e.status != "deprecated"]
    if not entries or not cwd:
        return None
    for place in (cwd, None):
        if place is None:
            place = _main_worktree(cwd)
            if not place:
                return None
        here = _norm(place)
        best = None
        for e in entries:
            folder = _norm(e.work_folder)
            if (here == folder or here.startswith(folder + "/")) and (best is None or len(folder) > len(best[0])):
                best = (folder, e)
        if best:
            return config.wiki(root) / best[1].path
    return None


def brief(path: Path, budget: int = BUDGET) -> str:
    """예산 안에 들면 본문 전체, 넘으면 SECTION_ORDER의 절만 순서대로 담는다."""
    doc = okf.read(path)
    head = f"인수인계서: {path.as_posix()}"
    body = doc.body.strip()
    if okf.approx_tokens(body) <= budget:
        return f"{head}\n\n{body}"
    marks = list(HEADING.finditer(body))
    sections = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        sections.append((m.group(1), body[m.start():end].strip()))
    picked, used = [], 0
    for pattern in SECTION_ORDER:
        for title, text in sections:
            if not re.search(pattern, title):
                continue
            room = budget - used
            if room <= 50:
                break
            if okf.approx_tokens(text) > room:
                text = _cut(text, room) + "\n…(줄임)"
            picked.append(text)
            used += okf.approx_tokens(text)
    picked.append(f"전체는 {path.as_posix()}를 연다.")
    return head + "\n\n" + "\n\n".join(picked)


def _cut(text: str, tokens: int) -> str:
    out, used = [], 0
    for line in text.splitlines():
        cost = okf.approx_tokens(line) + 1
        if used + cost > tokens:
            break
        out.append(line)
        used += cost
    return "\n".join(out)
