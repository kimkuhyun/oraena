"""목차 생성: 폴더 index.md(OKF SPEC §8), 폴더 log.md(git 기록, §9), 파생 색인 JSON.

모두 원본 Markdown에서 다시 만들 수 있는 파생물이다. 손으로 고치지 않는다.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from oraena import config, okf

OKF_VERSION = "0.2"
LOG_DAYS = 90
LOG_LIMIT = 20
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
# 목차 절 순서: 이어서 할 일(인수인계서·작업 문서)을 먼저 보이게 한다.
INDEX_ORDER = ("Handoff", "WorkDoc", "Decision", "Explanation", "HowTo", "Reference", "Record")


@dataclass
class Entry:
    path: str  # wiki/ 기준 posix 경로
    type: str
    title: str
    description: str
    aliases: list[str] = field(default_factory=list)
    status: str = ""
    work_folder: str = ""  # 인수인계서가 붙은 작업 폴더. 세션 시작 훅이 이것으로 인수인계서를 찾는다.


def iter_docs(wiki: Path):
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(wiki)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.name in okf.RESERVED:
            continue
        yield path


def title_of(doc: okf.Doc) -> str:
    t = doc.meta.get("title")
    if isinstance(t, str) and t.strip():
        return t.strip()
    m = H1.search(doc.body)
    return m.group(1).strip() if m else doc.path.stem


def entry_of(wiki: Path, doc: okf.Doc) -> Entry:
    aliases = doc.meta.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = [str(aliases)]
    return Entry(
        path=doc.path.relative_to(wiki).as_posix(),
        type=str(doc.meta.get("type") or ""),
        title=title_of(doc),
        description=" ".join(str(doc.meta.get("description") or "").split()),
        aliases=[str(a) for a in aliases],
        status=str(doc.meta.get("status") or ""),
        work_folder=str(doc.meta.get("work_folder") or ""),
    )


def catalog(root: Path) -> list[Entry]:
    """파생 색인을 읽는다. 없으면 만든다."""
    path = catalog_path(root)
    if not path.exists():
        return build_catalog(root)
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Entry(**item) for item in data["entries"]]


def catalog_path(root: Path) -> Path:
    return root / ".oraena" / "catalog.json"


def build_catalog(root: Path) -> list[Entry]:
    wiki = config.wiki(root)
    entries = [entry_of(wiki, okf.read(p)) for p in iter_docs(wiki)]
    out = catalog_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"entries": [asdict(e) for e in entries]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return entries


def _line(title: str, target: str, description: str) -> str:
    title = title.replace("[", "(").replace("]", ")")
    desc = f" - {description}" if description else ""
    return f"* [{title}]({target}){desc}"


def _subdir_summary(wiki: Path, sub: Path, by_dir: dict[Path, list[Entry]]) -> str:
    count = sum(len(v) for d, v in by_dir.items() if d == sub or sub in d.parents)
    titles = [e.title for e in sorted(by_dir.get(sub, []), key=lambda e: e.title)][:3]
    if not titles:
        titles = sorted(p.name for p in sub.iterdir() if p.is_dir() and not p.name.startswith("."))[:3]
    head = f"문서 {count}개"
    return f"{head}: {', '.join(titles)}" if titles else head


def render_index(wiki: Path, folder: Path, by_dir: dict[Path, list[Entry]]) -> str:
    lines: list[str] = []
    if folder == wiki:
        lines += ["---", f'okf_version: "{OKF_VERSION}"', "---", ""]
    subs = sorted(
        p for p in folder.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and any(d == p or p in d.parents for d in by_dir)
    )
    if subs:
        lines.append("# Subdirectories")
        lines.append("")
        for sub in subs:
            lines.append(_line(sub.name + "/", f"{sub.name}/index.md", _subdir_summary(wiki, sub, by_dir)))
        lines.append("")
    groups: dict[str, list[Entry]] = defaultdict(list)
    for e in by_dir.get(folder, []):
        groups[e.type or "Untyped"].append(e)
    order = [t for t in INDEX_ORDER if t in groups] + sorted(t for t in groups if t not in INDEX_ORDER)
    for t in order:
        lines.append(f"# {t}")
        lines.append("")
        for e in sorted(groups[t], key=lambda e: e.title):
            lines.append(_line(e.title, Path(e.path).name, e.description))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _git_log(root: Path) -> list[tuple[str, str, str]]:
    """(날짜, 상태, 데이터 폴더 기준 경로). git이 없으면 빈 목록."""
    if not (root / ".git").exists():
        return []
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=false", "log", f"--since={LOG_DAYS}.days",
             "--date=short", "--name-status", "--format=@%ad", "--", config.WIKI],
            capture_output=True, text=True, encoding="utf-8", check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    rows, date = [], ""
    for line in out.splitlines():
        if line.startswith("@"):
            date = line[1:]
        elif line.strip() and date:
            parts = line.split("\t")
            status, path = parts[0][:1], parts[-1]
            rows.append((date, status, path))
    return rows


VERB = {"A": "Creation", "M": "Update", "R": "Update", "D": "Deletion"}


def render_logs(root: Path, entries: list[Entry]) -> dict[Path, str]:
    wiki = config.wiki(root)
    titles = {e.path: e.title for e in entries}
    by_folder: dict[Path, list[tuple[str, str, str]]] = defaultdict(list)
    for date, status, path in _git_log(root):
        p = Path(path)
        if p.name in okf.RESERVED or p.suffix != ".md" or status not in VERB:
            continue
        rel = p.relative_to(config.WIKI).as_posix() if p.parts[0] == config.WIKI else p.as_posix()
        folder = wiki / Path(rel).parent
        if len(by_folder[folder]) < LOG_LIMIT:
            by_folder[folder].append((date, VERB[status], titles.get(rel, Path(rel).stem)))
    out = {}
    for folder, rows in by_folder.items():
        lines, current = [], None
        for date, verb, title in rows:
            if date != current:
                lines += ["", f"## {date}", ""]
                current = date
            lines.append(f"* **{verb}** {title}")
        out[folder / "log.md"] = "\n".join(lines).strip() + "\n"
    return out


def build(root: Path) -> dict:
    """index.md, log.md, 파생 색인을 다시 만든다. 바꾼 파일 수를 돌려준다."""
    wiki = config.wiki(root)
    entries = build_catalog(root)
    by_dir: dict[Path, list[Entry]] = defaultdict(list)
    for e in entries:
        by_dir[wiki / Path(e.path).parent].append(e)
    folders = {wiki}
    for d in by_dir:
        folders.add(d)
        folders.update(p for p in d.parents if p == wiki or wiki in p.parents)
    written = 0
    files = {f / "index.md": render_index(wiki, f, by_dir) for f in sorted(folders)}
    files.update(render_logs(root, entries))
    for path, text in files.items():
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old != text:
            path.write_text(text, encoding="utf-8", newline="\n")
            written += 1
    return {"documents": len(entries), "folders": len(folders), "written": written}


def add_args(parser) -> None:
    parser.add_argument("--root", help="데이터 폴더(기본: 설정의 root)")


def run(args) -> int:
    root = Path(args.root) if args.root else config.data_root()
    result = build(root)
    print(f"문서 {result['documents']}개, 폴더 {result['folders']}개, 바뀐 파일 {result['written']}개")
    return 0
