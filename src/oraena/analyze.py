"""`oraena analyze`: 대화 기록에서 지표와 후보를 뽑는다(설계서 2.1, 3.3, 3.7, 3.8).

교정인지, 같은 교정인지는 판단이 필요하다. 이 스크립트는 낱말 규칙으로 후보만 거르고,
판정은 주간 정리에서 AI가 초안을 쓰고 사용자가 확정한다.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from oraena import transcripts

CORRECTION_CUE = re.compile(
    r"(아니(야|라|고|지)?\b|아닌데|말고|하지\s?마|하지\s?말|왜\s|다시\s?해|틀렸|잘못|그게 아니|"
    r"제대로|똑바로|빼(고|라|줘)?\b|그만|쓸모없|낭비|이해 ?못|뭐하는|안 ?되잖|했잖아|말했잖)"
)
EMPTY_RESULT = re.compile(r"No (files|matches) found|^$")
SEARCH_TOOLS = {"Grep", "Glob"}


@dataclass
class Report:
    days: int
    sessions: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    corrections: list[dict] = field(default_factory=list)
    alias_candidates: list[dict] = field(default_factory=list)
    skill_use: dict = field(default_factory=dict)
    knowledge_candidates: list[dict] = field(default_factory=list)


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def _search_query(call: transcripts.ToolCall) -> str:
    return str(call.input.get("pattern") or call.input.get("query") or "")


def _wiki_matcher():
    """위키 문서 경로인지 가린다. 새 구조는 /wiki/, 그 전 구조는 데이터 폴더 안(raw/·records/ 밖)."""
    try:
        from oraena import config
        root = config.data_root().as_posix().lower().rstrip("/") + "/"
    except Exception:
        root = None

    def is_wiki(path: str) -> bool:
        p = path.lower()
        if "/wiki/" in p:
            return True
        return bool(root) and p.startswith(root) and not any(
            seg in p for seg in ("/raw/", "/records/", "/.oraena/", "/agent/"))
    return is_wiki


def analyze(days: int = 7) -> Report:
    rep = Report(days=days)
    is_wiki = _wiki_matcher()
    per_host: dict[str, list[transcripts.Session]] = defaultdict(list)
    skill_use: Counter = Counter()
    searches = empties = 0
    for s in transcripts.sessions(days):
        per_host[s.host].append(s)
        for i, prompt in enumerate(s.prompts):
            if CORRECTION_CUE.search(prompt[:300]):
                rep.corrections.append({"host": s.host, "session": s.id, "cwd": s.cwd, "turn": i,
                                        "before": s.before[i] if i < len(s.before) else "",
                                        "text": prompt[:300]})
        failed: list[str] = []
        wrote_wiki = False
        research = 0
        for call in s.tools:
            name = call.name
            if name == "Skill":
                skill_use[str(call.input.get("skill", ""))] += 1
            path = str(call.input.get("file_path") or "").replace("\\", "/")
            if name == "Read" and path.endswith("/SKILL.md"):
                skill_use[Path(path).parent.name] += 1
            if name in SEARCH_TOOLS:
                searches += 1
                if EMPTY_RESULT.search(call.result.strip()):
                    empties += 1
                    q = _search_query(call)
                    if q:
                        failed.append(q)
            if name == "Read" and is_wiki(path) and path.endswith(".md") and failed:
                for q in failed:
                    rep.alias_candidates.append({"query": q, "opened": path, "session": s.id})
                failed = []
            if name in ("Write", "Edit") and is_wiki(path):
                wrote_wiki = True
            if name in ("WebFetch", "WebSearch"):
                research += 1
        if research >= 5 and not wrote_wiki:
            rep.knowledge_candidates.append({"host": s.host, "session": s.id, "cwd": s.cwd,
                                             "web_calls": research, "first_prompt": s.prompts[0][:120]})
    for host, items in per_host.items():
        rep.sessions[host] = len(items)
        rep.metrics[host] = {
            "prompts_per_session": _median([len(x.prompts) for x in items]),
            "tool_calls_per_session": _median([len(x.tools) for x in items]),
            "interrupts_total": sum(x.interrupts for x in items),
            "hook_context_chars_per_session": _median([x.hook_context_chars for x in items]),
            "hook_blocks_total": sum(len(x.hook_blocks) for x in items),
        }
    rep.metrics["search"] = {"total": searches, "empty": empties,
                             "empty_rate": round(empties / searches, 3) if searches else 0.0}
    rep.metrics["correction_candidates"] = len(rep.corrections)
    rep.skill_use = dict(skill_use.most_common())
    return rep


def summary(rep: Report) -> str:
    lines = [f"기간: 최근 {rep.days}일, 세션 {rep.sessions}"]
    for host in ("claude", "codex"):
        m = rep.metrics.get(host)
        if m:
            lines.append(
                f"- {host}: 세션당 발화 {m['prompts_per_session']}, 도구 호출 {m['tool_calls_per_session']}, "
                f"끼어들기 {m['interrupts_total']}, 훅이 넣은 글 {m['hook_context_chars_per_session']}자(중앙값), "
                f"막힘 {m['hook_blocks_total']}"
            )
    sm = rep.metrics["search"]
    lines.append(f"- 검색(Grep·Glob): {sm['total']}회 중 빈 결과 {sm['empty']} ({sm['empty_rate']:.1%})")
    lines.append(f"- 교정 후보 발화: {len(rep.corrections)} (낱말 규칙, 판정 전)")
    lines.append(f"- 별칭 후보: {len(rep.alias_candidates)}, 지식 후보 세션: {len(rep.knowledge_candidates)}")
    top = ", ".join(f"{k} {v}" for k, v in list(rep.skill_use.items())[:5]) or "없음"
    lines.append(f"- 스킬 사용: {top}")
    return "\n".join(lines)


def add_args(parser) -> None:
    parser.add_argument("--days", type=int, default=7, help="볼 기간(일)")
    parser.add_argument("--json", help="전체 결과를 쓸 JSON 경로")


def run(args) -> int:
    rep = analyze(args.days)
    print(summary(rep))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(asdict(rep), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"전체 결과: {args.json}")
    return 0
