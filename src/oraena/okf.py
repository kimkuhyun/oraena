"""OKF 문서 읽기·쓰기. 메타정보는 YAML이고 본문은 Markdown이다.

시각 값은 쓴 문자열 그대로 둔다(OKF 참조 구현과 같이 YAML 1.1 자동 변환을 끈다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RESERVED = {"index.md", "log.md"}

# 이 위키가 쓰는 type 7개(설계서 3.3).
TYPES = ("Reference", "HowTo", "Explanation", "Decision", "Handoff", "WorkDoc", "Record")


class _Loader(yaml.SafeLoader):
    """시각·날짜를 문자열로 남기는 로더."""


_Loader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)


@dataclass
class Doc:
    path: Path
    meta: dict = field(default_factory=dict)
    body: str = ""
    has_meta: bool = False
    meta_error: str | None = None


FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)


def parse(text: str, path: Path) -> Doc:
    m = FRONT.match(text)
    if not m:
        return Doc(path=path, body=text)
    body = text[m.end():]
    try:
        meta = yaml.load(m.group(1), Loader=_Loader) or {}
    except yaml.YAMLError as exc:
        return Doc(path=path, body=body, has_meta=True, meta_error=str(exc).splitlines()[0])
    if not isinstance(meta, dict):
        return Doc(path=path, body=body, has_meta=True, meta_error="메타정보가 키-값 묶음이 아닙니다")
    return Doc(path=path, meta=meta, body=body, has_meta=True)


def read(path: Path) -> Doc:
    return parse(path.read_text(encoding="utf-8"), path)


def dump_meta(meta: dict) -> str:
    # default_flow_style=None: 값이 스칼라뿐인 목록·묶음은 한 줄([a, b])로 쓴다.
    # aliases와 type을 줄 단위 검색으로 찾기 때문이다(설계서 11절).
    return yaml.dump(
        meta, Dumper=_Dumper, allow_unicode=True, sort_keys=False,
        default_flow_style=None, width=10_000,
    )


def render(doc: Doc) -> str:
    if not doc.meta and not doc.has_meta:
        return doc.body
    body = doc.body if doc.body.startswith("\n") or not doc.body else "\n" + doc.body
    return f"---\n{dump_meta(doc.meta)}---{body}"


def write(doc: Doc) -> None:
    doc.path.parent.mkdir(parents=True, exist_ok=True)
    doc.path.write_text(render(doc), encoding="utf-8", newline="\n")


LINK = re.compile(r"(!?\[[^\]\n]*\]\()(<[^>\n]+>|[^)\s]+)(\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^(```|~~~)", re.M)


def _outside_code(text: str) -> list[tuple[int, int]]:
    """코드 블록 밖 구간 목록. 코드 블록 안의 링크 모양은 링크로 보지 않는다."""
    spans, start, inside = [], 0, False
    for m in FENCE.finditer(text):
        if not inside:
            spans.append((start, m.start()))
        else:
            start = text.find("\n", m.end())
            start = len(text) if start < 0 else start
        inside = not inside
    if not inside:
        spans.append((start, len(text)))
    return spans


def is_local(target: str) -> bool:
    t = target.strip("<>")
    return bool(t) and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", t) and not t.startswith(("#", "/"))


INLINE_CODE = re.compile(r"(`+)[^`\n].*?\1")


def links(text: str) -> list[tuple[int, int, str]]:
    """본문의 로컬 링크 (시작, 끝, 대상). 코드 블록과 인라인 코드 안의 링크 모양은 뺀다."""
    out = []
    for a, b in _outside_code(text):
        code = [(m.start(), m.end()) for m in INLINE_CODE.finditer(text, a, b)]
        for m in LINK.finditer(text, a, b):
            if any(s <= m.start() < e for s, e in code):
                continue
            target = m.group(2)
            if is_local(target):
                out.append((m.start(2), m.end(2), target.strip("<>")))
    return out


def split_anchor(target: str) -> tuple[str, str]:
    path, sep, anchor = target.partition("#")
    return path, (sep + anchor)


def approx_tokens(text: str) -> int:
    """토큰 수 추정(추정치). 한글 한 글자 ≈ 1토큰, 그 밖 4글자 ≈ 1토큰."""
    hangul = sum(1 for ch in text if "가" <= ch <= "힣")
    return hangul + (len(text) - hangul) // 4
