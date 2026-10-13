# ORAENA

ORAENA는 AI가 관리하는 개인 위키형 기억저장소입니다. 작업 경험, 결정, 지식, 개인 기록, 스킬을 Markdown 폴더 하나에 모으고, Claude Code와 Codex가 세션마다 필요한 기억을 읽고 쓰게 합니다.

ORAENA는 Claude Code·Codex의 기본 메모리 위에 얹는 **작업 기억·규칙 층**입니다. 목표는 같은 교정이 반복되지 않게 하는 것이고, 성공 기준도 그것입니다. 호스트 메모리가 "무엇이 있었나"를 남긴다면, ORAENA는 "무엇이 맞고 무엇을 지켜야 하나"를 정리하고 강제합니다. 에이전트의 능력을 올린다고 주장하지 않습니다.

쓰기와 정리는 대화 중인 AI가 일반 파일 도구로 합니다. 라이브러리는 AI가 놓치기 쉬운 기계적인 일만 맡습니다.

| 라이브러리가 하는 일 | AI가 하는 일 |
|---|---|
| 목차(index.md) 자동 생성 | 페이지 쓰기와 고쳐 쓰기 |
| 세션 시작 때 현재 폴더의 인수인계서 주입 | 인수인계서의 현재 상황·다음 작업 갱신 |
| 직접 찾기(`find`, `outline`)와 발화별 후보 기록 | 교훈을 규칙·스킬·스크립트로 바꾸기 |
| 작업량이 쌓이면 작업 끝 확인 요청 | 주 1회 정리 세션 |
| 스킬 폴더 연결, git 기록, 형식 검사, 사용 기록 | |

## 설치

Python 3.12 이상과 `uv`가 필요합니다. 아래 경로는 예시입니다.

```bash
uv tool install --editable C:\Users\kimkuhyn\Desktop\oraena
```

```bash
oraena init C:\Users\kimkuhyn\Desktop\OKF
```

`init`은 다음을 합니다.

- 기억저장소 폴더에 `AGENTS.md`(사용 규칙)와 `index.md`(목차)만 만들고 git 저장소로 초기화합니다.
- `~/.claude/settings.json`에 훅 여섯 개를 등록하고, 기억저장소를 `permissions.additionalDirectories`에 넣고, Claude auto memory를 끕니다. 기존 설정은 `settings.json.oraena-backup-<시각>`으로 남깁니다.
- `~/.claude/CLAUDE.md`에 `@<기억저장소>/AGENTS.md` 한 줄을 넣어, 어느 폴더에서 열어도 규칙과 목차가 실리게 합니다.

auto memory를 그대로 쓰려면 `--keep-auto-memory`, Claude 설정을 건드리지 않으려면 `--no-claude`를 붙입니다. Claude Code를 새로 열면 적용됩니다.

이미 만든 저장소를 Codex에도 연결하려면 `oraena connect --codex --root C:\Users\kimkuhyn\Desktop\OKF`를 실행합니다. `~/.codex/AGENTS.md`에 OKF 규칙 위치를 기록하고, `~/.codex/hooks.json`에 세션 시작·관련 페이지 후보 기록·행동 규칙·작업 끝 확인·동기화 훅을 등록합니다. 기존 Codex 지침과 다른 훅은 보존합니다. Codex 새 대화를 열고 `/hooks`에서 새 훅을 신뢰해야 훅이 실행됩니다. Codex에서도 페이지는 일반 파일 도구로 직접 읽고 고칩니다.

## 기억저장소 구조

처음에는 파일 두 개뿐입니다. 나머지 구조는 AI가 쓰면서 만듭니다.

```text
<기억저장소>/
  AGENTS.md     사용 규칙. 모든 세션에 실림
  index.md      루트 목차. 자동 생성, 모든 세션에 실림
  .oraena/      캐시·세션 상태·사용 기록 (git 제외)
```

고정된 약속은 다음 다섯 가지입니다.

1. 모든 페이지 맨 앞에 `summary`와 `updated` 메타정보를 둡니다. 목차와 주입이 이 두 줄로 만들어집니다.
2. 메타정보에 `folder`가 있는 페이지가 그 작업 폴더의 인수인계서입니다. 코드 저장소뿐 아니라 코드 없는 일의 작업 폴더도 같습니다. 폴더 없이 잠깐 하는 일은 `handoff: true`를 씁니다.
3. `index.md`는 손으로 고치지 않습니다. 예외는 폴더 목차의 `<!-- oraena:scope -->` 블록입니다. 그 폴더가 무엇을 다루고 언제 여는지 한두 문장을 적으면 다시 만들 때 보존되고 상위 목차의 폴더 줄에 쓰입니다.
4. 인수인계서에는 `status`(active, paused, done, dropped)를 둡니다. 더는 현재 사실이 아닌 페이지는 `status: archived`로 내립니다. 루트 목차는 진행 중 → 멈춘 일 순으로, 폴더 목차는 인수인계서 → 현재 페이지 → 지난 기록 순으로 배치되고, 끝난 일과 지난 기록은 자동 주입에서 뒤로 밀립니다.
5. 스킬은 `skills/<이름>/SKILL.md`에 둡니다. 연결된 Claude와 Codex의 `skills/<이름>`으로 자동 연결됩니다(Windows는 junction).

메타정보 키 전체와 쓰기 규칙은 `oraena init`이 만드는 `AGENTS.md`에 있습니다.

## 훅

| 사건 | 처리 |
|---|---|
| SessionStart | 현재 폴더를 `folder`로 가진 인수인계서를 주입합니다. 없으면 없다고 알립니다. `when` 정규식이 깨진 규칙이 있으면 함께 알립니다. 압축(compact) 뒤에는 규칙 확인 기록을 지워 규칙을 다시 보여 주게 합니다 |
| UserPromptSubmit | 제목·별칭·요약·본문 앞부분을 점수화해 기준을 넘는 페이지를 최대 5개 고릅니다. 기본(`shadow`)에서는 넣지 않고 후보만 사용 기록에 남기며, `ORAENA_INJECT=on`이나 `~/.oraena.json`의 `"inject": "on"`이면 넣고, `off`이면 계산하지 않습니다. 비공개가 아닌 작업 폴더(코드 저장소 등)에서 연 세션에서는 `private: true` 페이지를 빼고, 같은 세션에서 최근 10번 안에 고른 페이지는 다시 고르지 않습니다. 세션 중 `AGENTS.md`가 바뀌었으면 바뀐 절을 한 번 알리고, 교정으로 보이는 발화면 교정 기록을 남기라고 알립니다 |
| PreToolUse | 규칙 페이지의 `when`(도구와 정규식)에 맞는 행동이면 `enforce: deny`는 늘 막고, 그 밖의 규칙은 세션(하위 에이전트는 따로)에서 처음 해당할 때 실행 전에 한 번 막고 규칙을 돌려줍니다(`once`, 다시 실행하면 통과). PreToolUse 알림은 도구가 실행된 뒤에 보이기 때문입니다. `enforce: notice`, `ORAENA_RULES=notice`(또는 `~/.oraena.json`의 `"rules"`)는 막지 않고 알립니다. `enforce` 값이 없는 규칙은 입력이 4,000자를 넘으면(긴 Write 등) 다시 보내는 비용 때문에, 기억저장소 안 페이지를 쓰는 호출이면 위키 기록이 규칙의 산출물이 아니기 때문에 알림으로 낮춥니다. `enforce: once`를 직접 적은 규칙은 길어도 한 번 막습니다. 세션 상태는 세션별 잠금으로 읽고 고칩니다. 위키 페이지에 컴파일되지 않는 `when` 정규식을 쓰려 하면 실행 전에 막습니다(Bash, PowerShell, Write, Edit, Agent, Workflow) |
| PostToolUse (비동기) | 기억저장소 페이지 열람·쓰기, 스킬 사용, 기억저장소 안의 Grep·Glob(낱말과 결과 수: content 방식은 줄 수, count 방식은 일치 수, 그 밖에는 파일 수)을 기록합니다 |
| Stop | 마지막 기억 쓰기나 마지막 요청 이후 도구 호출이 20번, 또는 사용자 발화가 10번 쌓이면 작업 끝 확인을 한 번 요청합니다(`ORAENA_NUDGE_TOOL_USES`, `ORAENA_NUDGE_TURNS`로 조정). 확인 항목 4번이 교정 기록입니다 |
| Stop (비동기) | 목차를 다시 만들고, 스킬을 연결하고, 변경을 git에 커밋합니다 |

훅은 실패해도 입력이나 작업을 막지 않습니다. 오류는 `.oraena/errors.log`에 남습니다. 훅은 셸을 거치지 않고 Python 실행 파일을 직접 실행합니다.

## 명령

| 명령 | 설명 |
|---|---|
| `oraena init <경로> [--codex]` | 기억저장소를 만들고 Claude Code, 선택하면 Codex에도 연결 |
| `oraena index` | 목차 다시 만들기 |
| `oraena find <질의>` | 질의와 관련 있는 페이지를 관련 순서로: 경로·요약, 일치한 섹션의 줄 범위(`L120-168`, Read의 offset·limit), 제목·요약에는 없어도 본문에 낱말이 있는 페이지. 빈 결과와 잘림에는 다음 행동을 안내합니다 |
| `oraena outline <경로>` | 페이지의 제목과 줄 번호(큰 페이지의 일부만 Read의 offset·limit으로 열 때) |
| `oraena lint [--notes]` | 메타정보 누락·형식, `when` 정규식, 깨진 링크, 크기 상한, 같은 summary, 교정 기록 형식 검사. `--notes`는 12KB 넘는 페이지와 범위 설명이 없는 폴더 |
| `oraena sync` | 목차·스킬 연결 갱신과 git 기록 |
| `oraena status [--days 30]` | 후보·주입·열람·스킬 사용, 규칙 작동 횟수(`rules`), 교정 후보 발화 수, 한 번도 열리지 않은 페이지, 실제 기록 기간(`span_hours`)과 엄격 지표(`strict`) 요약 |
| `oraena corrections [--weeks 8] [--json]` | 오늘이 든 주까지 N주의 교정 기록을 주 단위로 집계: `반복 교정 수 / 전체 교정 수`, 원인별 수, 반복된 규칙, 사용 기록과 어긋나 다시 볼 원인, 같은 기간의 교정 후보 발화 수. 형식이 틀리거나 미래 날짜인 행은 세지 않고 알리며 종료 코드 1 |
| `oraena connect` / `disconnect` | Claude Code 연결 다시 하기 / 풀기. `--codex`는 Codex 연결 대상으로 사용. `connect --allow-find`는 `oraena find`·`outline`을 권한 허용 목록에 넣습니다(사용자 설정 변경이라 기본으로는 하지 않음) |

`--root`를 생략하면 `ORAENA_ROOT` 환경 변수, 그다음 `~/.oraena.json`에 기록된 위치를 씁니다.

## 효과 판단

구조는 성능 향상의 조건을 만들 뿐 효과를 보장하지 않습니다. `oraena status`로 다음을 봅니다.

- 실제 기록 기간(`span_hours`). `--days`는 조회 창일 뿐이라 기록이 짧으면 비율로 결론 내지 않습니다
- 후보(넣은 것과 shadow로 기록만 한 것)가 발화 3번 안에 실제로 열린 비율. `strict`는 고치려고 먼저 연 것과 목차·`AGENTS.md` 열람을 뺀 값입니다
- AI가 후보 밖에서 스스로 연 페이지, 기억저장소 안 검색(Grep·Glob)에서 결과가 없던 비율
- 작업 끝 확인 요청 횟수와 그 뒤의 기억 쓰기
- 한 번도 열리지 않은 페이지와 쓰이지 않는 스킬

성공 기준(같은 교정의 반복 감소)은 `oraena corrections`의 주별 반복률로 봅니다. 교정은 AI가 그 턴 안에 `corrections/YYYY-MM.md`에 기록하고, 원인이 "찾지 못함"이면 찾기를, "읽고도 어김"이면 규칙 단계를 고칩니다.

## 이전 판

0.2.1까지의 구현(SQLite 원장, MCP 도구, Codex 훅)은 `legacy-v0.2.1` 태그에 있습니다.
