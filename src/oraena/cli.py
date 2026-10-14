"""명령 분기. 각 명령의 모듈은 실행할 때만 불러온다(훅이 빨리 뜨도록)."""

from __future__ import annotations

import argparse
import importlib
import sys

# (명령, 모듈, 함수, 한 줄 설명). 모듈의 함수는 argparse 하위 파서를 받아 인자를 더하는
# `add_args(parser)`와 실행하는 `<함수>(args) -> int`를 가진다.
COMMANDS: list[tuple[str, str, str, str]] = [
    ("where", "oraena.config_cmd", "run", "데이터 폴더 위치를 보여 준다"),
    ("index", "oraena.index", "run", "wiki/의 index.md, log.md, 파생 색인을 다시 만든다"),
    ("check", "oraena.check", "run_cli", "OKF 적합 조건, 위키 규칙, 정책 규칙 파일을 검사한다"),
    ("migrate", "oraena.migrate", "run", "0.3 OKF를 새 형식으로 새 폴더에 옮긴다"),
    ("skills", "oraena.skills", "run", "스킬 목록을 보여 준다(검색어로 좁힘)"),
    ("analyze", "oraena.analyze", "run", "대화 기록에서 지표, 교정 후보, 별칭 후보를 뽑는다"),
    ("link", "oraena.link", "run", "작업 폴더에 인수인계서를 붙인다"),
    ("mv", "oraena.move", "run", "위키 문서를 옮기고 위키 전체의 링크를 고친다"),
    ("connect", "oraena.install", "run_connect", "Claude·Codex에 하네스를 건다(사용자가 직접 실행)"),
    ("disconnect", "oraena.install", "run_disconnect", "하네스 연결을 푼다(사용자가 직접 실행)"),
    ("init", "oraena.install", "run_init", "빈 폴더에 데이터 폴더를 만들고 하네스를 건다(사용자가 직접 실행)"),
]
# add_args 이름이 기본과 다른 명령
ARG_BUILDERS = {"init": "add_init_args"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oraena",
        description="개인 OKF 지식 저장소 위에 얹는 Claude Code·Codex 하네스",
    )
    sub = parser.add_subparsers(dest="command", metavar="명령")
    for name, module, _func, help_text in COMMANDS:
        sp = sub.add_parser(name, help=help_text, description=help_text)
        mod = importlib.import_module(module)
        builder = ARG_BUILDERS.get(name, "add_args")
        if hasattr(mod, builder):
            getattr(mod, builder)(sp)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    # 훅은 매 도구 호출마다 뜨므로 파서 전체를 만들지 않고 바로 넘긴다.
    if argv[:1] == ["hook"]:
        from oraena.hooks.run import main as hook_main

        return hook_main(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    for name, module, func, _help in COMMANDS:
        if name == args.command:
            return int(getattr(importlib.import_module(module), func)(args) or 0)
    return 2
