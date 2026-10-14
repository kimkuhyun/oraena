# ORAENA 레퍼런스

## 명령

| 명령 | 하는 일 |
|---|---|
| `oraena init <폴더>` | 빈 폴더에 `wiki/`·`raw/`·`agent/`와 로컬 git을 만들고 두 호스트에 건다 |
| `oraena connect [--dry-run]` | 두 호스트에 훅·지침·스킬 연결을 건다. `--dry-run`은 바꿀 내용만 보인다 |
| `oraena disconnect` | 건 것만 푼다. 다른 설정은 그대로 둔다 |
| `oraena link <이름> --folder <작업 폴더>` | 작업 폴더에 인수인계서를 붙인다 |
| `oraena check` | OKF 형식, 깨진 링크, 정책 규칙 파일을 검사한다 |
| `oraena index` | 목차(`index.md`), 변경 기록(`log.md`), 검색 색인을 다시 만든다 |
| `oraena mv <문서...> <폴더>` | 위키 문서를 옮기고 위키 전체의 링크를 고친다 |
| `oraena skills [검색어]` | 스킬 목록을 보인다 |
| `oraena analyze --days 7` | 대화 기록에서 지표, 교정 카드 수, 교정 후보, 별칭 후보를 뽑는다 |
| `oraena migrate <0.3 폴더> <새 폴더>` | 0.3 형식 저장소를 새 형식으로 옮긴다 |
| `oraena where` | 데이터 폴더 위치를 보인다 |

`connect`, `disconnect`, `init`은 사람이 직접 실행한다. AI가 실행하면 막힌다.

## 핵심 규칙 3가지

엔진에는 하네스가 자기 경계를 지키는 규칙만 있다. 늘 막는다.

| 지키는 것 | 막는 행동 | 판정 |
|---|---|---|
| 하네스 설정(훅, `settings.json`, `config.toml`, 플러그인·MCP 설정 명령, oraena 설치본, `~/.oraena.json`) | 수정, 연결·설치 명령 | 경로, 명령 |
| 정책 규칙(`agent/policy/`) | 쓰기·수정·삭제, 폴더째 지우기·옮기기 | 경로, 명령 |
| `raw/`의 기존 파일 | 수정·삭제·옮기기 | 경로와 파일이 있는가, 명령 |

## 정책 규칙

그 밖의 막기·확인은 데이터 폴더의 `agent/policy/`에 파일 하나에 규칙 하나로 둔다. 처음에는 비어 있다. AI는 이 폴더를 고칠 수 없고, 새 규칙은 `raw/proposals/`에 제안 파일로 쓴다. 사람이 검토해 옮긴다.

```markdown
---
level: ask
shell: '\bgit\s+push\b'
---
push 전에 사용자에게 확인받습니다. 이유: 원격에 올라간 것은 되돌리기 어렵습니다.
```

```markdown
---
tool: 'Agent|Task'
missing: model
host: claude
---
하위 에이전트에 model을 지정하세요.
```

| 키 | 뜻 |
|---|---|
| `level` | `deny`(막기, 기본) 또는 `ask`(확인) |
| `shell` | 셸 명령 전체에 맞는 정규식 |
| `content` | 쓰는 내용에 맞는 정규식 |
| `path` | 쓰는 파일 경로(소문자, `/`, 절대 경로)에 맞는 정규식 |
| `tool` | 도구 이름 전체에 맞는 정규식 |
| `input` | 도구 입력의 글 값 전체(줄바꿈으로 이음)에 맞는 정규식. 예: Workflow 스크립트 |
| `missing` | `tool`과 함께 쓴다. 도구 입력에 이 키가 없거나 비었을 때만 걸린다 |
| `host` | `claude` 또는 `codex`. 비우면 둘 다 |
| 본문 | 걸렸을 때 AI에게 보일 말. 이유를 함께 쓴다 |

- 조건(`shell`, `content`, `path`, `tool`, `input`)은 하나 이상 쓴다. 쓴 조건이 모두 맞아야 걸린다.
- 정규식은 대소문자를 가리지 않는다. YAML에서는 작은따옴표로 감싼다.
- 막기가 하나라도 걸리면 막는다. Codex 훅에는 묻는 기능이 없어 확인도 막고, 사용자에게 명령을 보여 주고 직접 실행하게 한다.
- 읽지 못한 규칙 파일은 적용하지 않는다. `oraena check`(E011)와 세션 시작 훅이 알린다.

## 교정 카드

사용자가 AI의 행동을 바로잡으면 AI가 그 자리에서 `raw/corrections/YYYY-MM-DD-HHMM-<이름>.md`를 새 파일로 쓴다. 발화에 교정 낱말이 있으면 발화 훅이 형식을 알려 준다.

| 메타정보 | 뜻 |
|---|---|
| `date` | 교정 시각 |
| `action` | 바로잡은 행동 한 줄 |
| `repeat_of` | 같은 교정의 이전 카드 파일 이름. 처음이면 비운다 |
| `proposal` | 옮길 곳 제안. 두 번째부터 쓴다 |

- 본문은 발화 원문 인용과 요지 한 줄이다.
- `oraena analyze`가 기간 안의 카드 수와 반복 비율(`repeat_of`가 있는 카드)을 센다.
- 주간 정리는 카드가 없는 교정 후보만 라벨링하고 빠진 카드를 채운다.

## 스킬 제안

같은 절차가 반복되면 AI가 `raw/proposals/YYYY-MM-DD-HHMM-skill-<이름>.md`를 새 파일로 쓰고 사용자에게 만들지 묻는다. 승인하면 `agent/skills/<이름>/SKILL.md`로 만든다.

| 메타정보 | 뜻 |
|---|---|
| `kind` | `skill` |
| `name` | 스킬 이름 |
| `description` | 언제 쓰는지 한 문장 |
| `evidence` | 근거가 된 대화나 교정 카드 두 건 |

- 본문은 `절차`와 `실제로 겪은 실패`다. 모델 지식만으로 쓰지 않는다.
- 만든 `SKILL.md`의 메타정보에는 `name`, `description`, `disable-model-invocation: true`를 둔다. 목록 설명이 매 세션 실리지 않게 하려는 것이다.
- 이 폴더에 쓰는 것을 훅이 막지는 않는다. 승인 절차는 지침과 안내 글로 지킨다.

## 설치가 바꾸는 파일

| 호스트 | 파일 | 바꾸는 것 |
|---|---|---|
| Claude Code | `~/.claude/settings.json` | 훅 5개, 데이터 폴더 접근, 설정 파일 편집 막기 |
| Claude Code | `~/.claude/CLAUDE.md` | 표시 블록 안의 지침·지도 가져오기 두 줄 |
| Claude Code | `~/.claude/skills/<이름>` | 스킬 폴더 정션 |
| Codex | `~/.codex/hooks.json` | 훅 5개 |
| Codex | `~/.codex/AGENTS.md` | 표시 블록 안의 지침과 지도 |
| Codex | `~/.agents/skills/<이름>` | 스킬 폴더 정션 |
| 공통 | `~/.oraena.json` | 데이터 폴더 위치 |

- 고치기 전에 원본을 `<이름>.oraena-backup-<시각>`으로 남긴다.
- 표시 블록과 oraena 항목만 고친다. 사용자 폴더와 다른 훅은 건드리지 않는다.
