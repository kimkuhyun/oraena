"""데이터 폴더의 로컬 git(원격 없음). 지난 판을 되살리는 데 쓴다(설계서 6절 결정 3).

git 사용자 이름이 없으면 커밋이 조용히 실패한다. 그때는 `oraena <oraena@localhost>`로 커밋한다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FALLBACK = ["-c", "user.name=oraena", "-c", "user.email=oraena@localhost"]


def git(root: Path, *args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=root, capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout)


def _identity(root: Path) -> list[str]:
    email = git(root, "config", "user.email")
    return [] if email.returncode == 0 and email.stdout.strip() else FALLBACK


def changed(root: Path) -> list[str]:
    """바뀐 경로(데이터 폴더 기준). git이 없거나 저장소가 아니면 빈 목록."""
    if not (root / ".git").exists():
        return []
    status = git(root, "status", "--porcelain")
    if status.returncode != 0:
        return []
    return [line[3:].strip('"') for line in status.stdout.splitlines()]


def commit(root: Path, message: str) -> bool:
    if git(root, "add", "-A").returncode != 0:
        return False
    return git(root, *_identity(root), "commit", "-q", "-m", message).returncode == 0


def init(root: Path, message: str) -> bool:
    if git(root, "init", "-q").returncode != 0:
        return False
    return commit(root, message)
