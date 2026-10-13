"""`oraena link <일 이름>`: 작업 폴더에 인수인계서를 붙인다.

`wiki/projects/<이름>/handoff.md`가 없으면 뼈대를 만들고, 있으면 `work_folder`만 이 폴더로 바꾼다.
세션 시작 훅이 `work_folder`로 인수인계서를 찾는다. 작업 폴더에는 아무 파일도 만들지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

from oraena import config, index, okf

NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
BODY = """
## 지금 위치

- (한두 문장. 세션 끝에 고쳐 쓴다)

## 다음 작업

1. (다음 세션이 바로 할 일)

## 정한 것

- (결정 문서 링크만 둔다)
"""


def link(root: Path, name: str, folder: Path) -> tuple[Path, str]:
    path = config.wiki(root) / "projects" / name / "handoff.md"
    folder_text = str(folder.resolve())
    if path.exists():
        doc = okf.read(path)
        if doc.meta.get("work_folder") == folder_text:
            return path, "이미 연결돼 있습니다"
        doc.meta["work_folder"] = folder_text
        okf.write(doc)
        index.build_catalog(root)
        return path, "작업 폴더를 바꿨습니다"
    meta = {
        "type": "Handoff",
        "title": f"{name} 인수인계서",
        "description": f"{name} 일을 이어 갈 때 먼저 여는 문서. 지금 위치와 다음 작업이 있다",
        "aliases": [name],
        "work_folder": folder_text,
    }
    okf.write(okf.Doc(path=path, meta=meta, body=BODY, has_meta=True))
    index.build_catalog(root)
    return path, "만들었습니다"


def add_args(parser) -> None:
    parser.add_argument("name", help="일 이름(kebab-case). wiki/projects/<이름>/에 둔다")
    parser.add_argument("--folder", default=".", help="작업 폴더(기본: 지금 폴더)")
    parser.add_argument("--root", help="데이터 폴더(기본: 설정의 root)")


def run(args) -> int:
    if not NAME.match(args.name):
        raise SystemExit("일 이름은 소문자·숫자·하이픈(kebab-case)으로 씁니다. 예: oraena-rebuild")
    root = Path(args.root) if args.root else config.data_root()
    path, what = link(root, args.name, Path(args.folder))
    print(f"{what}: {path}")
    return 0
