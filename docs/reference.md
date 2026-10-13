# ORAENA 레퍼런스

## 명령

| 명령 | 하는 일 |
|---|---|
| `oraena init <폴더>` | 빈 폴더에 `wiki/`·`raw/`·`agent/`와 로컬 git을 만들고 두 호스트에 건다 |
| `oraena connect [--dry-run]` | 두 호스트에 훅·지침·스킬 연결을 건다. `--dry-run`은 바꿀 내용만 보인다 |
| `oraena disconnect` | 건 것만 푼다. 다른 설정은 그대로 둔다 |
| `oraena link <이름> --folder <작업 폴더>` | 작업 폴더에 인수인계서를 붙인다 |
| `oraena check` | OKF 형식과 깨진 링크를 검사한다 |
| `oraena index` | 목차(`index.md`), 변경 기록(`log.md`), 검색 색인을 다시 만든다 |
| `oraena mv <문서...> <폴더>` | 위키 문서를 옮기고 위키 전체의 링크를 고친다 |
| `oraena skills [검색어]` | 스킬 목록을 보인다 |
| `oraena analyze --days 7` | 대화 기록에서 지표, 교정 후보, 별칭 후보를 뽑는다 |
| `oraena migrate <0.3 폴더> <새 폴더>` | 0.3 형식 저장소를 새 형식으로 옮긴다 |
| `oraena where` | 데이터 폴더 위치를 보인다 |

`connect`, `disconnect`, `init`은 사람이 직접 실행한다. AI가 실행하면 막힌다.

## 막기 7가지

| 행동 | 판정 |
|---|---|
| 커밋 메시지에 공동 작성자 줄 | `git commit` 명령 |
| 방화벽 허용 규칙 만들기·방화벽 끄기 | 명령, 스크립트 파일 내용 |
| 서버를 0.0.0.0에 바인드 | 명령, 설정·코드 내용 |
| 하네스 설정 수정(훅, `settings.json`, `config.toml`, 설치본) | 경로, 명령 |
| `raw/`의 기존 파일 수정·삭제 | 경로와 파일이 있는가 |
| 비밀(API 키, 토큰)을 파일·커밋에 씀 | 내용 패턴 |
| 하위 에이전트에 model 없이 위임(Claude) | `Agent` 입력 |

## 확인 4가지

| 행동 | 판정 |
|---|---|
| 폴더째 지우기, 덮어쓰며 옮기기, 변경을 버리는 git 명령 | 명령. 임시 폴더 대상은 제외 |
| 외부로 내보내기(push, PR, 게시, 메시지) | 명령, 외부 MCP 도구 이름 |
| Windows 시스템 설정 변경 | 명령 |
| 전역 설치·삭제 | 명령 |

Codex 훅에는 묻는 기능이 없어 확인 4가지도 막는다. 사용자에게 명령을 보여 주고 직접 실행하게 한다.

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
