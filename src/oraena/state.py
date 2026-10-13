"""세션마다 훅이 나눠 쓰는 작은 상태(시작 시각, 인수인계서, 파일을 바꿨는가, 알림 횟수).

데이터 폴더의 `.oraena/state/`에 둔다. git에 넣지 않는다(.gitignore).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

KEEP_DAYS = 7


def _path(root: Path, host: str, session_id: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", f"{host}-{session_id or 'unknown'}")
    return root / ".oraena" / "state" / f"{safe}.json"


def load(root: Path, host: str, session_id: str) -> dict:
    path = _path(root, host, session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(root: Path, host: str, session_id: str, data: dict) -> None:
    path = _path(root, host, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def update(root: Path, host: str, session_id: str, **values) -> dict:
    data = load(root, host, session_id)
    data.update(values)
    save(root, host, session_id, data)
    return data


def cleanup(root: Path) -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for path in (root / ".oraena" / "state").glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass
