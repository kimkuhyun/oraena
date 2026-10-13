"""`oraena skills [검색어]`: agent/skills/의 스킬 목록. 출력은 약 1,500토큰 안으로 자른다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from oraena import config, okf

BUDGET = 1500


@dataclass
class Skill:
    name: str
    description: str
    path: Path


def all_skills(root: Path) -> list[Skill]:
    out = []
    for path in sorted((config.agent(root) / "skills").glob("*/SKILL.md")):
        doc = okf.read(path)
        out.append(Skill(
            name=str(doc.meta.get("name") or path.parent.name),
            description=" ".join(str(doc.meta.get("description") or "").split()),
            path=path,
        ))
    return out


def find(root: Path, query: str | None = None) -> list[Skill]:
    skills = all_skills(root)
    if not query:
        return skills
    words = query.lower().split()
    return [s for s in skills if all(w in f"{s.name} {s.description}".lower() for w in words)]


def render(skills: list[Skill]) -> str:
    if not skills:
        return "스킬이 없습니다."
    lines, used = [], 0
    for s in skills:
        line = f"- {s.name}: {s.description} ({s.path.as_posix()})"
        used += okf.approx_tokens(line)
        if used > BUDGET:
            lines.append(f"- 외 {len(skills) - len(lines)}개. 검색어를 더해 좁힙니다.")
            break
        lines.append(line)
    return "\n".join(lines)


def add_args(parser) -> None:
    parser.add_argument("query", nargs="*", help="이름·설명에서 찾을 말")
    parser.add_argument("--root", help="데이터 폴더(기본: 설정의 root)")


def run(args) -> int:
    root = Path(args.root) if args.root else config.data_root()
    print(render(find(root, " ".join(args.query) or None)))
    return 0
