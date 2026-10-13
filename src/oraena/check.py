"""형식 검사: OKF v0.2 적합 3조건(SPEC §11)과 이 위키의 규칙(설계서 3.3).

메시지는 AI가 읽고 바로 고칠 수 있게 고칠 방법을 함께 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from oraena import config, okf

FOLDER_INDEX_BUDGET = 1500  # 토큰(추정). 넘으면 하위 폴더로 나눈다(설계서 3.3).
ROOT_INDEX_BUDGET = 2000  # 토큰(추정). 상시 지도 예산.
INDEX_LINE = re.compile(r"^(#\s+\S.*|\*\s+\[[^\]]+\]\([^)]+\)(\s+-\s+.*)?)$")
LOG_LINE = re.compile(r"^(##\s+\d{4}-\d{2}-\d{2}|\*\s+.+)$")


@dataclass
class Problem:
    path: Path
    code: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.code.startswith("E")


def check_doc(wiki: Path, path: Path) -> list[Problem]:
    doc = okf.read(path)
    out: list[Problem] = []
    if not doc.has_meta:
        return [Problem(path, "E001", "메타정보가 없습니다. 맨 위에 --- 로 감싼 YAML을 넣고 type, title, description을 씁니다.")]
    if doc.meta_error:
        return [Problem(path, "E002", f"메타정보 YAML을 읽지 못했습니다({doc.meta_error}). 따옴표와 들여쓰기를 고칩니다.")]
    t = doc.meta.get("type")
    if not t or not str(t).strip():
        out.append(Problem(path, "E003", f"type이 없습니다. 다음 중 하나를 씁니다: {', '.join(okf.TYPES)}"))
    elif t not in okf.TYPES:
        out.append(Problem(path, "E004", f"type '{t}'은 쓰지 않습니다. 다음 중 하나로 바꿉니다: {', '.join(okf.TYPES)}"))
    if not str(doc.meta.get("title") or "").strip():
        out.append(Problem(path, "E005", "title이 없습니다. 문서 제목을 title에 씁니다."))
    desc = str(doc.meta.get("description") or "").strip()
    if not desc:
        out.append(Problem(path, "E006", "description이 없습니다. '무엇이고 언제 여는지'를 한 문장으로 씁니다. 목차에 그대로 실립니다."))
    elif len(desc) > 200:
        out.append(Problem(path, "W003", f"description이 {len(desc)}자입니다. 200자 안의 한 문장으로 줄입니다."))
    aliases = doc.meta.get("aliases")
    if aliases is not None and not isinstance(aliases, list):
        out.append(Problem(path, "E007", "aliases는 목록으로 씁니다. 예: aliases: [오라에나, ORAENA]"))
    for _a, _b, target in okf.links(doc.body):
        rel, _anchor = okf.split_anchor(target)
        if rel and not (path.parent / rel).exists():
            out.append(Problem(path, "E008", f"깨진 링크: {target}. 대상 경로를 고치거나 링크를 지웁니다."))
    return out


def check_index(wiki: Path, path: Path) -> list[Problem]:
    text = path.read_text(encoding="utf-8")
    out: list[Problem] = []
    doc = okf.parse(text, path)
    if doc.has_meta and (path.parent != wiki or set(doc.meta) - {"okf_version"}):
        out.append(Problem(path, "E009", "index.md에는 메타정보를 두지 않습니다(루트의 okf_version만 허용). `oraena index`로 다시 만듭니다."))
    for line in doc.body.splitlines():
        if line.strip() and not INDEX_LINE.match(line):
            out.append(Problem(path, "E009", f"index.md에 목록이 아닌 줄이 있습니다: {line[:40]}. `oraena index`로 다시 만듭니다."))
            break
    budget = ROOT_INDEX_BUDGET if path.parent == wiki else FOLDER_INDEX_BUDGET
    tokens = okf.approx_tokens(text)
    if tokens > budget:
        out.append(Problem(path, "W001", f"목차가 약 {tokens}토큰으로 예산 {budget}을 넘습니다. 문서를 주제별 하위 폴더로 나눕니다."))
    for _a, _b, target in okf.links(text):
        rel, _anchor = okf.split_anchor(target)
        if rel and not (path.parent / rel).exists():
            out.append(Problem(path, "E008", f"깨진 링크: {target}. `oraena index`로 다시 만듭니다."))
    return out


def check_log(path: Path) -> list[Problem]:
    text = path.read_text(encoding="utf-8")
    if okf.parse(text, path).has_meta:
        return [Problem(path, "E010", "log.md에는 메타정보를 두지 않습니다. `oraena index`로 다시 만듭니다.")]
    for line in text.splitlines():
        if line.strip() and not LOG_LINE.match(line):
            return [Problem(path, "E010", f"log.md 형식이 아닌 줄: {line[:40]}. `## YYYY-MM-DD` 아래 `* ` 목록으로 씁니다.")]
    return []


def run(root: Path, paths: list[Path] | None = None) -> list[Problem]:
    wiki = config.wiki(root)
    targets = paths if paths is not None else sorted(wiki.rglob("*.md"))
    out: list[Problem] = []
    for path in targets:
        path = Path(path)
        try:
            rel = path.resolve().relative_to(wiki.resolve())
        except ValueError:
            continue  # 번들 밖(raw/, agent/)은 OKF 검사 대상이 아니다.
        if any(part.startswith(".") for part in rel.parts) or not path.exists():
            continue
        if path.name == "index.md":
            out += check_index(wiki, path)
        elif path.name == "log.md":
            out += check_log(path)
        else:
            out += check_doc(wiki, path)
    return out


def add_args(parser) -> None:
    parser.add_argument("paths", nargs="*", help="검사할 파일(기본: wiki/ 전체)")
    parser.add_argument("--root", help="데이터 폴더(기본: 설정의 root)")
    parser.add_argument("--limit", type=int, default=50, help="보여 줄 문제 수")


def run_cli(args) -> int:
    root = Path(args.root) if args.root else config.data_root()
    problems = run(root, [Path(p) for p in args.paths] or None)
    errors = [p for p in problems if p.is_error]
    for p in problems[: args.limit]:
        try:
            shown = p.path.relative_to(root)
        except ValueError:
            shown = p.path
        print(f"{p.code} {shown}: {p.message}")
    by_code: dict[str, int] = {}
    for p in problems:
        by_code[p.code] = by_code.get(p.code, 0) + 1
    summary = ", ".join(f"{c} {n}" for c, n in sorted(by_code.items())) or "문제 없음"
    print(f"합계: 오류 {len(errors)}, 경고 {len(problems) - len(errors)} ({summary})")
    return 1 if errors else 0
