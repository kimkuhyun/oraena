"""`oraena mv <문서...> <폴더>`: 위키 문서를 옮기고 위키 전체의 상대 링크를 고친다.

폴더 목차가 예산을 넘으면 AI가 하위 폴더로 나눈다(설계서 3.3). 손으로 옮기면 링크가 깨지므로 이 명령을 쓴다.
`agent/`의 링크도 고친다. `raw/`는 고치지 않는다(원본 보존). 깨진 `raw/` 링크 수는 알린다.
"""

from __future__ import annotations

import os
from pathlib import Path

from oraena import config, index, okf
from oraena.migrate import rewrite_links


def _key(path: Path) -> Path:
    return Path(os.path.normcase(os.path.normpath(str(path))))


def plan(root: Path, sources: list[Path], dest: Path) -> dict[Path, Path]:
    wiki = config.wiki(root).resolve()
    dest = (dest if dest.is_absolute() else wiki / dest).resolve()
    if not dest.is_relative_to(wiki):
        raise SystemExit(f"대상 폴더가 wiki/ 밖입니다: {dest}")
    moves: dict[Path, Path] = {}
    for src in sources:
        src = (src if src.is_absolute() else wiki / src).resolve()
        if not src.is_file() or not src.is_relative_to(wiki) or src.suffix != ".md":
            raise SystemExit(f"wiki/ 안의 문서가 아닙니다: {src}")
        if src.name in okf.RESERVED:
            raise SystemExit(f"{src.name}은 목차가 만드는 파일이라 옮기지 않습니다.")
        new = dest / src.name
        if new.exists() and new != src:
            raise SystemExit(f"대상에 같은 이름이 있습니다: {new}")
        moves[src] = new
    return moves


def _texts(root: Path):
    for folder in (config.wiki(root), config.agent(root)):
        for path in folder.rglob("*.md"):
            if path.name in okf.RESERVED or any(p.startswith(".") for p in path.relative_to(folder).parts):
                continue
            yield path.resolve()


def move(root: Path, sources: list[Path], dest: Path, dry_run: bool = False) -> dict:
    moves = plan(root, sources, dest)
    mapping = {_key(a): b for a, b in moves.items()}
    # rewrite_links는 Path로 맞춘다. 대소문자 차이를 없애려고 열쇠를 normcase로 맞춘 사본을 쓴다.
    lookup = _CaseMap(mapping)
    changed_links, touched = 0, 0
    for path in list(_texts(root)):
        new_path = moves.get(path, path)
        doc = okf.read(path)
        body, n = rewrite_links(doc.body, path, new_path, lookup)
        if n == 0 and new_path == path:
            continue
        changed_links += n
        touched += 1
        if dry_run:
            continue
        doc.body, doc.path = body, new_path
        okf.write(doc)
        if new_path != path:
            path.unlink()
    raw_hits = 0
    raw = config.raw(root)
    if raw.is_dir():
        names = {a.name for a in moves}
        for path in raw.rglob("*.md"):
            text = path.read_text(encoding="utf-8", errors="replace")
            raw_hits += sum(1 for _s, _e, target in okf.links(text) if Path(okf.split_anchor(target)[0]).name in names)
    if not dry_run:
        index.build(root)
    return {"moved": len(moves), "files": touched, "links": changed_links, "raw_links": raw_hits}


class _CaseMap(dict):
    """경로 대소문자를 무시하고 찾는 대응표(Windows)."""

    def __init__(self, mapping: dict[Path, Path]):
        super().__init__(mapping)

    def get(self, key, default=None):
        return super().get(_key(key), default)


def add_args(parser) -> None:
    parser.add_argument("paths", nargs="+", help="옮길 문서들과 마지막에 대상 폴더(wiki/ 기준 또는 절대 경로)")
    parser.add_argument("--root", help="데이터 폴더(기본: 설정의 root)")
    parser.add_argument("--dry-run", action="store_true", help="고칠 파일·링크 수만 보인다")


def run(args) -> int:
    if len(args.paths) < 2:
        raise SystemExit("옮길 문서와 대상 폴더를 줍니다. 예: oraena mv projects/a/x.md projects/a/sub")
    root = Path(args.root) if args.root else config.data_root()
    *sources, dest = (Path(p) for p in args.paths)
    out = move(root, sources, dest, args.dry_run)
    print(f"문서 {out['moved']}개 옮김, 파일 {out['files']}개에서 링크 {out['links']}개 고침"
          + (" (--dry-run: 바꾸지 않음)" if args.dry_run else ""))
    if out["raw_links"]:
        print(f"raw/에서 옮긴 문서를 가리키는 링크 {out['raw_links']}개는 원본 보존 때문에 고치지 않았습니다.")
    return 0
