"""`oraena where`: 데이터 폴더 위치와 세 하위 폴더가 있는지 보여 준다."""

from __future__ import annotations

from oraena import config


def run(_args) -> int:
    try:
        root = config.data_root()
    except config.NotConfigured as exc:
        print(exc)
        return 1
    print(root)
    for name, path in (("wiki", config.wiki(root)), ("raw", config.raw(root)), ("agent", config.agent(root))):
        print(f"  {name}: {'있음' if path.is_dir() else '없음'}")
    return 0
