# 🏠 청약 데일리 리포트 봇

> 매일 아침 8시, 청약홈 신규 분양공고를 텔레그램으로 받아보는 봇

[![daily-report](https://github.com/3dagger/cheongyak-bot/actions/workflows/daily-report.yml/badge.svg)](https://github.com/3dagger/cheongyak-bot/actions/workflows/daily-report.yml)

한국부동산원 **청약홈 공공 API**에서 분양정보를 조회해 매일 아침 텔레그램으로 리포트를 발송합니다.
GitHub Actions에서 실행되므로 **로컬 PC가 꺼져 있어도 동작**합니다.

## 📬 리포트 내용

| 섹션 | 내용 |
|---|---|
| 🆕 새로 올라온 공고 | 어제~오늘 게시된 모집공고 |
| 📬 오늘 접수 시작 | 오늘부터 청약 접수하는 단지 |
| ⏰ 마감 임박 | 오늘·내일 접수 마감하는 단지 |

각 항목에 지역 · 공급유형(APT/무순위·잔여/오피스텔) · 세대수 · 접수기간 · 공고 링크가 포함됩니다.

## ⚙️ 동작 방식

```
GitHub Actions (매일 23:00 UTC = 08:00 KST)
        │
        ▼
cheongyak_report.py
        │  ① 청약홈 API 조회 (APT / 무순위·잔여 / 오피스텔 등 3종)
        │  ② 오늘 기준으로 신규·접수시작·마감임박 분류
        ▼
텔레그램 봇 → 채팅방 발송
```

- **스케줄**: [.github/workflows/daily-report.yml](.github/workflows/daily-report.yml) — 매일 08:00 KST (GitHub 스케줄러 특성상 5~15분 지연 가능)
- **의존성 없음**: Python 표준 라이브러리만 사용 (`pip install` 불필요)
- **비활성화 방지**: 60일 무활동 시 스케줄을 끄는 GitHub 정책에 대응해, 매 실행마다 워크플로우가 스스로 재활성화

## 🔑 필요한 키 (레포 Secrets)

| Secret | 설명 | 발급처 |
|---|---|---|
| `CHEONGYAK_SERVICE_KEY` | 청약홈 API 인증키 | [공공데이터포털](https://www.data.go.kr/data/15098547/openapi.do) → "한국부동산원_청약홈 분양정보 조회 서비스" 활용신청 (자동승인) |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 | 텔레그램 @BotFather → `/newbot` |
| `TELEGRAM_CHAT_ID` | 수신 채팅방 ID | 봇에게 메시지 1개 보낸 뒤 `--get-chat-id` 실행 |

등록: 레포 **Settings → Secrets and variables → Actions**, 또는

```bash
gh secret set CHEONGYAK_SERVICE_KEY --body "발급받은_키"
gh secret set TELEGRAM_BOT_TOKEN   --body "봇_토큰"
gh secret set TELEGRAM_CHAT_ID    --body "채팅방_ID"
```

## 🖥️ 로컬 실행 (테스트·수동 확인용)

로컬에서는 `.env` 파일로 키를 읽습니다 (`.env.example` 참고, **커밋 금지** — `.gitignore` 처리됨).

```bash
cp .env.example .env   # 키 채우기

python3 cheongyak_report.py --dry-run       # 전송 없이 리포트 미리보기
python3 cheongyak_report.py --get-chat-id   # 채팅방 ID 확인
python3 cheongyak_report.py --test          # 텔레그램 연결 테스트
python3 cheongyak_report.py                 # 실제 발송
```

클라우드에서 즉시 발송하려면:

```bash
gh workflow run daily-report.yml
```

## 🔧 설정 옵션

`.env`(로컬) 또는 워크플로우 `env`(클라우드)에 추가:

| 키 | 기본값 | 설명 |
|---|---|---|
| `AREA_FILTER` | (전국) | 지역 필터, 쉼표 구분 — 예: `서울,경기,인천` |
| `SEND_WHEN_EMPTY` | `true` | 소식 없는 날에도 "소식 없음" 메시지 발송 여부 |

발송 시간 변경: 워크플로우의 `cron` 값 수정 (**UTC 기준**, KST−9시간 — 예: 아침 7시 KST → `0 22 * * *`)

## ❓ 트러블슈팅

- **리포트가 안 옴** → [Actions 탭](https://github.com/3dagger/cheongyak-bot/actions)에서 실행 로그 확인
- **API 인증 에러** → 공공데이터포털 키는 발급 직후 반영까지 수 분~1시간 걸릴 수 있음. 개발계정 활용기간(24개월) 만료 시 연장신청 필요
- **봇이 메시지를 못 보냄** → 채팅방에서 봇을 차단했는지 확인. 그룹방이라면 봇이 방에 초대되어 있어야 함
