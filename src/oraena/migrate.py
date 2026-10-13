"""0.3 OKF를 새 형식으로 옮긴다(설계서 3.13). 원본은 읽기만 하고, 새 폴더에 만든다.

- knowledge/, projects/, personal/ → wiki/. 메타정보를 OKF 키로 바꾸고 type을 붙인다.
- records/ → raw/records/, corrections/ → raw/corrections/ (형식 그대로).
- rules/, skills/, AGENTS.md → raw/archive-0.3/ (보관).
- 생성 파일(index.md)은 옮기지 않고 다시 만든다. 숨김 폴더는 .git만 옮긴다(--with-git).
- 모든 Markdown의 상대 링크를 새 경로로 다시 쓴다.
"""

from __future__ import annotations

import os
import re
import shutil
from importlib import resources
from pathlib import Path

from oraena import check, config, index, okf

WIKI_DIRS = ("knowledge", "projects", "personal")
RAW_DIRS = {"records": "records", "corrections": "corrections"}
ARCHIVE = "archive-0.3"
ARCHIVE_DIRS = ("rules", "skills")
DROP_KEYS = {"summary", "updated", "private", "handoff", "when", "enforce", "load", "forbid",
             "rules", "status", "folder", "title", "description", "type"}
DONE_STATUS = {"done", "dropped", "archived"}
H1_LINE = re.compile(r"\A\s*#\s+(.+?)\s*\n")


def target_of(rel: Path) -> Path | None:
    """원본 상대 경로 → 새 상대 경로. None이면 옮기지 않는다."""
    parts = rel.parts
    if not parts or any(p.startswith(".") for p in parts):
        return None
    top = parts[0]
    if len(parts) == 1:
        if top == "AGENTS.md":
            return Path(config.RAW) / ARCHIVE / "AGENTS.md"
        return None  # 루트 index.md 같은 생성 파일
    if top in WIKI_DIRS:
        if rel.name == "index.md":
            return None  # 다시 만든다
        return Path(config.WIKI) / rel
    if top in RAW_DIRS:
        return Path(config.RAW) / RAW_DIRS[top] / Path(*parts[1:])
    if top in ARCHIVE_DIRS:
        return Path(config.RAW) / ARCHIVE / rel
    return None


def type_of(rel: Path, meta: dict) -> str:
    old = str(meta.get("type") or "").strip().lower()
    for t in okf.TYPES:
        if old == t.lower():
            return t
    tags = [str(t) for t in (meta.get("tags") or [])] if isinstance(meta.get("tags"), list) else []
    if rel.name == "handoff.md" or meta.get("handoff") or "인수인계서" in tags:
        return "Handoff"
    if rel.name == "design-decisions.md":
        return "Explanation"  # 지난 결정 이력 한 장(설계서 11절 G3)
    if "작업 문서" in tags or rel.stem.endswith("-plan") or rel.stem.startswith("work-"):
        return "WorkDoc"
    return "Reference"


def convert_meta(rel: Path, doc: okf.Doc) -> okf.Doc:
    meta = doc.meta if isinstance(doc.meta, dict) else {}
    body = doc.body
    title = str(meta.get("title") or "").strip()
    m = H1_LINE.match(body)
    if m:
        if not title:
            title = m.group(1).strip()
        if m.group(1).strip() == title:
            body = body[m.end():].lstrip("\n")
    if not title:
        title = rel.stem
    description = " ".join(str(meta.get("description") or meta.get("summary") or "").split())
    new: dict = {"type": type_of(rel, meta), "title": title, "description": description}
    for key in ("tags", "aliases"):
        if meta.get(key):
            new[key] = meta[key]
    old_status = str(meta.get("status") or "").strip()
    if new["type"] == "Handoff":
        if old_status:
            new["work_status"] = old_status
        if old_status in DONE_STATUS:
            new["status"] = "deprecated"
        if meta.get("folder"):
            new["work_folder"] = meta["folder"]
    elif old_status in DONE_STATUS:
        new["status"] = "deprecated"
    for key, value in meta.items():
        if key not in DROP_KEYS and key not in new:
            new[key] = value
    return okf.Doc(path=doc.path, meta=new, body=body, has_meta=True)


def rewrite_links(text: str, old_file: Path, new_file: Path, mapping: dict[Path, Path]) -> tuple[str, int]:
    """old_file 기준 상대 링크를 new_file 기준으로 다시 쓴다. 바꾼 수를 돌려준다."""
    out, last, changed = [], 0, 0
    for start, end, target in okf.links(text):
        rel, anchor = okf.split_anchor(target)
        if not rel:
            continue
        old_target = Path(os.path.normpath(old_file.parent / rel))
        new_target = mapping.get(old_target, old_target)
        try:
            new_rel = Path(os.path.relpath(new_target, new_file.parent)).as_posix()
        except ValueError:
            continue  # 다른 드라이브
        if rel.endswith("/") and not new_rel.endswith("/"):
            new_rel += "/"
        replacement = new_rel + anchor
        original = text[start:end]
        if original.startswith("<"):
            replacement = f"<{replacement}>"
        if replacement != original:
            out.append(text[last:start])
            out.append(replacement)
            last = end
            changed += 1
    out.append(text[last:])
    return "".join(out), changed


def write_agent(dst: Path) -> None:
    agent = config.agent(dst)
    (agent / "skills").mkdir(parents=True, exist_ok=True)
    tpl = resources.files("oraena") / "templates"
    text = (tpl / "AGENTS.md").read_text(encoding="utf-8").replace("{root}", dst.as_posix())
    (agent / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
    rules = agent / "rules"
    rules.mkdir(exist_ok=True)
    (rules / "okf-writing.md").write_text(
        (tpl / "rules" / "okf-writing.md").read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
    )


def migrate(src: Path, dst: Path, with_git: bool = False) -> dict:
    src, dst = src.resolve(), dst.resolve()
    if dst.exists() and any(dst.iterdir()):
        raise SystemExit(f"대상 폴더가 비어 있지 않습니다: {dst}")
    dst.mkdir(parents=True, exist_ok=True)

    plan: list[tuple[Path, Path]] = []  # (원본 절대, 새 절대)
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        new_rel = target_of(path.relative_to(src))
        if new_rel is not None:
            plan.append((path, dst / new_rel))

    # 링크 대응표: 파일, 그 파일이 든 폴더, 다시 만들 index.md.
    mapping: dict[Path, Path] = {old: new for old, new in plan}
    for old, new in plan:
        for o, n in zip(old.parents, new.parents):
            if o == src or n == dst:
                break
            mapping.setdefault(o, n)
    for top in WIKI_DIRS:
        for d in [src / top, *[p for p in (src / top).rglob("*") if p.is_dir()]]:
            if (d / "index.md").exists():
                mapping[d / "index.md"] = dst / config.WIKI / d.relative_to(src) / "index.md"
    mapping[src / "index.md"] = dst / config.WIKI / "index.md"
    mapping[src / "rules" / "always.md"] = dst / config.RAW / ARCHIVE / "rules" / "always.md"

    stats = {"wiki": 0, "raw": 0, "other": 0, "links": 0}
    for old, new in plan:
        new.parent.mkdir(parents=True, exist_ok=True)
        if old.suffix != ".md":
            shutil.copy2(old, new)
            stats["other"] += 1
            continue
        text = old.read_text(encoding="utf-8")
        if new.is_relative_to(dst / config.WIKI):
            doc = convert_meta(old.relative_to(src), okf.parse(text, new))
            doc.body, n = rewrite_links(doc.body, old, new, mapping)
            okf.write(doc)
            stats["wiki"] += 1
        else:
            text, n = rewrite_links(text, old, new, mapping)
            new.write_text(text, encoding="utf-8", newline="\n")
            stats["raw"] += 1
        stats["links"] += n

    restructure = src / ".oraena" / "restructure-map.json"
    if restructure.exists():
        shutil.copy2(restructure, dst / config.RAW / ARCHIVE / "restructure-map.json")
    gitignore = src / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    if ".oraena/" not in lines:
        lines.append(".oraena/")
    (dst / ".gitignore").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    if with_git and (src / ".git").exists():
        shutil.copytree(src / ".git", dst / ".git")

    write_agent(dst)
    built = index.build(dst)
    problems = check.run(dst)
    stats["documents"] = built["documents"]
    stats["errors"] = sum(1 for p in problems if p.is_error)
    stats["warnings"] = sum(1 for p in problems if not p.is_error)
    codes: dict[str, int] = {}
    for p in problems:
        codes[p.code] = codes.get(p.code, 0) + 1
    stats["codes"] = codes
    return stats


def add_args(parser) -> None:
    parser.add_argument("src", help="0.3 형식 OKF 폴더(읽기만 함)")
    parser.add_argument("dst", help="새 형식으로 만들 빈 폴더")
    parser.add_argument("--with-git", action="store_true", help="원본의 .git도 옮긴다")


def run(args) -> int:
    stats = migrate(Path(args.src), Path(args.dst), args.with_git)
    print(f"wiki 문서 {stats['wiki']}, raw 문서 {stats['raw']}, 그 밖 파일 {stats['other']}, "
          f"다시 쓴 링크 {stats['links']}")
    print(f"검사: 문서 {stats['documents']}, 오류 {stats['errors']}, 경고 {stats['warnings']} {stats['codes']}")
    return 0 if stats["errors"] == 0 else 1
