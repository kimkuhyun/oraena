"""데이터 폴더 위치를 읽고 쓴다. 설정 파일은 ~/.oraena.json이다."""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG = Path.home() / ".oraena.json"

WIKI = "wiki"
RAW = "raw"
AGENT = "agent"


class NotConfigured(RuntimeError):
    """데이터 폴더가 정해지지 않았다."""


def load() -> dict:
    if not CONFIG.exists():
        return {}
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def save(values: dict) -> None:
    data = load()
    data.update(values)
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def data_root() -> Path:
    # 환경 변수가 설정 파일보다 앞선다. 사본으로 시험할 때 쓴다. 훅은 호스트의 환경을 받으므로
    # 모델이 셸에서 바꿔도 훅에는 닿지 않는다.
    root = os.environ.get("ORAENA_ROOT") or load().get("root")
    if not root:
        raise NotConfigured("데이터 폴더가 정해지지 않았습니다. `oraena init <폴더>`를 먼저 실행합니다.")
    return Path(root)


def wiki(root: Path) -> Path:
    return root / WIKI


def raw(root: Path) -> Path:
    return root / RAW


def agent(root: Path) -> Path:
    return root / AGENT
