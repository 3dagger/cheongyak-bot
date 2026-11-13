# CLAUDE.md

청약홈·LH청약플러스·SH 인터넷청약 공고를 모아 매일 08:00 KST 텔레그램으로 보내는 봇. `cheongyak_report.py` 하나를 GitHub Actions(`.github/workflows/daily-report.yml`)가 실행한다.

## 규칙
- 파이썬 표준 라이브러리만 쓴다. 외부 패키지를 추가하지 않는다(README 의 "설치할 패키지 없음").
- 공개 레포다. 키·토큰은 레포 Secrets(`CHEONGYAK_SERVICE_KEY`·`TELEGRAM_BOT_TOKEN`·`TELEGRAM_CHAT_ID`)로만 다루고 `.env` 는 커밋하지 않는다.
- 보낸 공고 기록(`.state/seen.json`)은 Actions 캐시에 둔다. 레포에 커밋하지 않는다.
- 테스트: `python3 -m unittest discover tests`(레포 루트에서, 네트워크 없이 순수 함수만). 동작을 바꾸면 `tests/` 에 테스트를 같이 고치거나 더한다.
- 확인: `python3 cheongyak_report.py --dry-run`(보내지 않고 출력), `--test`(텔레그램 테스트 메시지).

## Git 작업 방식
- main 에 직접 커밋·푸시하지 않는다. main 은 PR 로만 바뀐다(저장소 규칙이 직접 푸시를 막는다).
- 작업 하나 = 브랜치 하나(`feat/…`·`fix/…`·`docs/…`·`chore/…`·`ci/…`·`test/…`) = PR 하나.
- 커밋 메시지 끝에 `Co-Authored-By: Claude <noreply@anthropic.com>` 를 넣는다(전역 규칙의 예외 — 이름에 모델명이 붙어도 된다).
- 순서: 브랜치 → 커밋 → `git push -u origin <브랜치>` → `gh pr create --base main`(본문: 변경 내용 · 확인한 명령과 결과) → 확인 통과 → `gh pr merge --squash --delete-branch` → `git switch main && git pull`.
- 머지 전 확인: 바꾼 범위에 맞게 `--dry-run` 등을 돌리고 결과를 PR 본문에 적는다. CI 가 생기면 `gh pr checks --watch` 로 통과를 확인한다. 실패하면 머지하지 않는다.
