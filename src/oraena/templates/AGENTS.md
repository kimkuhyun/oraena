# 하네스 사용법

- 지식은 `{root}/wiki/`에 있다. 지도는 `wiki/index.md`이다. 찾을 때는 메타정보의 `aliases:`와 `type:`을 검색한다. type은 Reference(사실) HowTo(방법) Explanation(배경·이유) Decision(결정) Handoff(인수인계서) WorkDoc(작업 문서) Record(기록)이다.
- 다시 쓸 사실·방법·결정은 `wiki/`에 쓴다. 대화에만 두면 다음 세션에서 사라진다.
- 원시 기록(로그, 조사 원문)은 `raw/`에 새 파일로 쓴다. 이름에 날짜와 시각을 넣는다(예: `raw/logs/2026-10-13-1530-oraena.md`). 이미 있는 파일은 고치지 못하게 막혀 있다.
- 사용자가 AI의 행동을 바로잡으면 `raw/corrections/`에 교정 카드를 새 파일로 남긴다. 같은 교정이 두 번째면 옮길 곳을 하나 제안한다. 카드 형식은 발화 훅이 알려 준다. 같은 절차가 반복되면 스킬 제안 파일을 `raw/proposals/`에 쓰고, 사용자가 승인하면 스킬로 만든다.
- 스킬 목록은 `oraena skills [검색어]`로 본다. 스킬을 쓰면 "쓸 스킬: 이름"을 한 줄로 밝히고 그 SKILL.md를 읽는다.
