"""정책 규칙: 데이터 폴더 `agent/policy/`의 Markdown 파일 하나가 규칙 하나다.

엔진은 하네스 설정·정책 폴더·raw/만 지킨다(rules.py). 그 밖의 막기·확인은 사용자가 이 폴더에 둔다.
AI는 이 폴더를 쓰거나 고칠 수 없다. 새 규칙은 raw/proposals/에 제안하고 사람이 옮긴다.

    ---
    level: ask                  # deny(막기, 기본) 또는 ask(확인)
    shell: '\\bgit\\s+push\\b'    # 조건: shell, content, path, tool, input 중 하나 이상. 모두 맞아야 걸린다
    ---
    AI에게 보일 말. 이유를 함께 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from oraena import config, okf

LEVELS = ("deny", "ask")
HOSTS = ("claude", "codex")
PATTERN_KEYS = ("shell", "content", "path", "tool", "input")
FLAGS = re.I | re.S


@dataclass
class Rule:
    id: str
    level: str
    say: str
    patterns: dict[str, re.Pattern] = field(default_factory=dict)
    missing: str = ""  # tool과 함께: 도구 입력에 이 키가 없거나 비었을 때만 걸린다
    host: str = ""  # 비우면 두 호스트


def folder(root: Path) -> Path:
    return config.agent(root) / "policy"


def parse(path: Path) -> tuple[Rule | None, str]:
    """(규칙, "") 또는 (None, 고칠 방법이 든 문제)."""
    try:
        doc = okf.read(path)
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"파일을 읽지 못했습니다({exc})"
    if not doc.has_meta:
        return None, "메타정보가 없습니다. 맨 위 --- 사이에 level과 조건(shell, content, path, tool)을 씁니다"
    if doc.meta_error:
        return None, f"메타정보 YAML을 읽지 못했습니다({doc.meta_error}). 정규식은 작은따옴표로 감쌉니다"
    meta = doc.meta
    level = str(meta.get("level") or "deny").strip().lower()
    if level not in LEVELS:
        return None, f"level '{level}'은 쓰지 않습니다. deny 또는 ask를 씁니다"
    patterns: dict[str, re.Pattern] = {}
    for key in PATTERN_KEYS:
        value = meta.get(key)
        if value is None or str(value) == "":
            continue
        try:
            patterns[key] = re.compile(str(value), FLAGS)
        except re.error as exc:
            return None, f"{key} 정규식 오류({exc})"
    if not patterns:
        return None, "조건이 없습니다. shell, content, path, tool, input 중 하나 이상을 씁니다"
    missing = str(meta.get("missing") or "").strip()
    if missing and "tool" not in patterns:
        return None, "missing은 tool과 함께 씁니다"
    host = str(meta.get("host") or "").strip().lower()
    if host and host not in HOSTS:
        return None, f"host '{host}'는 쓰지 않습니다. claude 또는 codex를 쓰거나 비웁니다"
    say = " ".join(doc.body.split()) or f"정책 규칙 {path.stem}에 걸렸습니다."
    return Rule(path.stem, level, say, patterns, missing, host), ""


def load_folder(where: Path) -> tuple[list[Rule], list[tuple[Path, str]]]:
    """(읽은 규칙, 읽지 못한 파일과 문제). README.md는 설명 파일로 보고 건너뛴다."""
    rules: list[Rule] = []
    problems: list[tuple[Path, str]] = []
    if not where.is_dir():
        return rules, problems
    for path in sorted(where.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        rule, problem = parse(path)
        if rule:
            rules.append(rule)
        else:
            problems.append((path, problem))
    return rules, problems


def load(root: Path) -> tuple[list[Rule], list[tuple[Path, str]]]:
    return load_folder(folder(root))


def matches(rule: Rule, act) -> bool:
    """규칙의 조건이 모두 맞는가. act는 rules.Action이다.

    shell은 명령 전체, content는 쓰는 내용, path는 쓰는 파일 경로(소문자, 슬래시, 절대 경로),
    tool은 도구 이름 전체, input은 도구 입력의 글 값을 줄바꿈으로 이은 것(예: Workflow 스크립트)에 맞춘다.
    """
    if rule.host and rule.host != act.host:
        return False
    p = rule.patterns
    if "shell" in p and not any(p["shell"].search(cmd) for cmd in act.shell):
        return False
    if "content" in p and not (act.content and p["content"].search("\n".join(act.content))):
        return False
    if "path" in p and not any(p["path"].search(path) for _op, path in act.writes):
        return False
    if "tool" in p and not p["tool"].fullmatch(act.tool):
        return False
    if "input" in p:
        text = "\n".join(v for v in act.input.values() if isinstance(v, str))
        if not p["input"].search(text):
            return False
    return not (rule.missing and act.input.get(rule.missing))
