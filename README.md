# 🏠 청약 데일리 리포트 봇

> 매일 아침 8시, 청약홈·LH·SH 신규 분양/임대 공고를 텔레그램으로 받아보는 봇

[![daily-report](https://github.com/3dagger/cheongyak-bot/actions/workflows/daily-report.yml/badge.svg)](https://github.com/3dagger/cheongyak-bot/actions/workflows/daily-report.yml)
![python](https://img.shields.io/badge/python-3.x%20stdlib%20only-3776AB?logo=python&logoColor=white)
![runs on](https://img.shields.io/badge/runs%20on-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)

청약홈·LH청약플러스·SH 인터넷청약을 매일 들어가 보는 대신, 세 곳의 공고를 모아 아침마다 텔레그램으로 요약해 줍니다. 신생아·신혼부부 특별공급 물량이 있는 단지는 따로 묶어 보여줍니다.
GitHub Actions에서 돌아가므로 **서버도, 켜 둔 PC도 필요 없습니다.** 파이썬 표준 라이브러리만 쓰기 때문에 설치할 패키지도 없습니다.

## 📬 이런 메시지가 옵니다

```
🏠 청약 데일리 리포트 — 2026-10-27 (월)

🆕 새로 올라온 공고 (지난 리포트 이후)
• [서울] ○○자이 (민영 1,024세대)
   특공 11-03 · 1순위 11-04~11-05 · 공고
   👶 신생아 52세대 · 신혼 104세대
• [경기도] △△ 행복주택 입주자 모집 (LH 행복주택)
   마감 11-10 · 공고

👶 신생아·신혼 특공 접수 예정 (14일 내)
• [서울] ○○자이 (민영 1,024세대)
   특공 11-03 · 1순위 11-04~11-05 · 공고
   👶 신생아 52세대 · 신혼 104세대

📬 오늘 접수 시작
• [인천] □□ 민간임대 (공공지원민간임대 512세대)
   접수 10-27~10-29 · 공고
   👶 신혼 60세대

⏰ 마감 임박 (오늘·내일)
• [경기] ◇◇아이파크 (오피스텔 120세대)
   접수 10-24~10-28 · 공고
```

| 섹션 | 기준 |
|---|---|
| 🆕 새로 올라온 공고 | 지난 리포트 이후 처음 조회된 공고 (공고일 14일 이내). 실행이 빠지거나 API 등록이 늦어도 다음 리포트에 실립니다 |
| 👶 신생아·신혼 특공 접수 예정 | 신생아·신혼 특공 물량이 있고 14일 안에 접수가 시작되는 단지 |
| 📬 오늘 접수 시작 | 특공·1순위·일반 접수 중 하나라도 오늘 시작하는 단지 |
| ⏰ 마감 임박 | 특공·1순위·접수 마감일이 오늘·내일인 단지 |

각 줄에 지역 · 단지명 · 공급유형 · 세대수 · 단계별 접수일(특공 / 1순위 / 일반) · 공고 링크가 붙고, APT·공공지원 민간임대는 신생아·신혼 특공 세대수가 붙습니다. 소식이 없는 날엔 "소식 없음" 한 줄만 옵니다.

### 수집 범위

| 출처 | 유형 | 방식 |
|---|---|---|
| 청약홈 | APT(민영·국민·신혼희망타운·민간사전청약), 무순위·잔여, 임의공급, 오피스텔·도시형·민간임대, 공공지원 민간임대 | 한국부동산원 공공 API |
| LH청약플러스 | 분양주택, 임대주택(행복·국민·영구·매입·전세임대 등), 주거복지 | LH 공공 API (토지·상가 제외) |
| SH 인터넷청약 | 분양·임대 게시판의 입주자 모집 공고 (장기전세·미리내집 등) | 공개 게시판 HTML 파싱 (서울이 `AREA_FILTER`에 있을 때만) |

- LH 공고는 접수 시작일 없이 게시일·마감일만 나오고, SH 공고는 게시일만 나옵니다. 정확한 접수 일정은 공고문을 확인하세요.
- LH·SH 조회에 실패하거나 결과가 0건이면(응답·페이지 구조 변경 의심) 리포트는 그대로 발송되고 하단에 ⚠️ 경고가 붙습니다.
- 청약홈 조회 등으로 리포트 자체를 만들지 못하면 `❗ 청약 리포트 생성 실패` 메시지와 실행 로그 링크가 옵니다.

## 🚀 Fork해서 5분 만에 쓰기

1. 이 레포를 **Fork** 합니다.
2. 키 2개를 발급받습니다.
   - **공공데이터포털 API 키** — 같은 계정에서 아래 두 서비스를 각각 활용신청합니다 (둘 다 자동승인). 키는 하나로 공통이며 *일반 인증키 (Decoding)* 값을 씁니다.
     - [한국부동산원_청약홈 분양정보 조회 서비스](https://www.data.go.kr/data/15098547/openapi.do)
     - [한국토지주택공사_분양임대공고문 조회 서비스](https://www.data.go.kr/data/15058530/openapi.do) (LH 공고용)
   - **텔레그램 봇 토큰** — 텔레그램에서 [@BotFather](https://t.me/BotFather)에게 `/newbot`.
3. 만든 봇에게 아무 메시지나 하나 보낸 뒤, 채팅방 ID를 확인합니다.
   ```bash
   cp .env.example .env            # TELEGRAM_BOT_TOKEN 만 채우면 됩니다
   python3 cheongyak_report.py --get-chat-id
   ```
4. Fork한 레포에 Secrets 3개를 등록합니다. (**Settings → Secrets and variables → Actions**, 또는 아래 명령)
   ```bash
   gh secret set CHEONGYAK_SERVICE_KEY --body "발급받은_키"
   gh secret set TELEGRAM_BOT_TOKEN   --body "봇_토큰"
   gh secret set TELEGRAM_CHAT_ID    --body "채팅방_ID"
   ```
5. 바로 한 번 보내 봅니다.
   ```bash
   gh workflow run daily-report.yml
   ```

이후엔 매일 08:00 KST에 자동으로 옵니다. Fork한 레포의 **Actions 탭에서 워크플로우가 활성화되어 있는지** 한 번만 확인해 주세요.

## ⚙️ 동작 방식

```
GitHub Actions (매일 23:00 UTC = 08:00 KST)
        │
        ▼
cheongyak_report.py
        │  ① 청약홈 API 5종 + LH API + SH 게시판에서 최근 45일 공고 수집
        │  ② AREA_FILTER 로 지역 필터 (LH '전국' 공고는 항상 포함)
        │  ③ 진행 중인 APT·공공지원 민간임대는 주택형별 API로 신생아·신혼 특공 세대수 조회
        │  ④ 지난 리포트 기록(.state/seen.json)과 비교해 새 공고를 고르고, 오늘 날짜 기준으로 특공 예정 · 접수시작 · 마감임박 분류
        ▼
텔레그램 Bot API → 채팅방 발송 (HTML 서식, 4,000자 초과 시 자동 분할)
```

- **스케줄**: [.github/workflows/daily-report.yml](.github/workflows/daily-report.yml). GitHub 스케줄러 특성상 5~15분 늦어질 수 있습니다.
- **비활성화 방지**: 60일간 커밋이 없으면 GitHub이 스케줄 워크플로우를 끕니다. 매 실행 끝에 `gh workflow enable`을 호출해 타이머를 스스로 리셋합니다.
- **새 공고 기록**: 보낸 공고 ID를 `.state/seen.json`에 남기고 Actions 캐시로 다음 실행에 넘깁니다. 캐시가 없으면(첫 실행·7일 이상 미실행) 공고일이 어제·오늘인 공고를 새 공고로 봅니다.
- **재시도**: API 호출 실패 시 간격을 늘려가며 3회 재시도합니다.
- **실패 알림**: 리포트 생성이 실패하면 원인과 실행 로그 링크를 텔레그램으로 보냅니다.
- **의존성 없음**: `urllib` · `json` 등 표준 라이브러리만 사용합니다.

## 🔧 설정 옵션

`.env`(로컬) 또는 워크플로우 `env`(클라우드)에서 바꿉니다.

| 키 | 기본값 | 설명 |
|---|---|---|
| `AREA_FILTER` | (전국) | 지역 필터, 쉼표 구분. 예: `서울,경기,인천` |
| `SEND_WHEN_EMPTY` | `true` | 소식 없는 날에도 "소식 없음" 메시지를 보낼지 |

- **발송 시간 변경**: 워크플로우의 `cron` 값을 수정합니다. **UTC 기준**이라 KST에서 9시간을 뺍니다. 예: 아침 7시 KST → `0 22 * * *`
- **지역 변경**: 워크플로우 `env.AREA_FILTER` 값을 바꿉니다. 비우면 전국입니다.

## 🖥️ 로컬 실행

로컬에서는 `.env` 파일로 키를 읽습니다. 환경변수가 있으면 그 값이 우선합니다.
`.env`는 `.gitignore`에 들어 있으니 커밋되지 않습니다.

```bash
cp .env.example .env   # 키 채우기

python3 cheongyak_report.py --dry-run       # 전송 없이 리포트 미리보기 (API 키만 있으면 됨)
python3 cheongyak_report.py --get-chat-id   # 채팅방 ID 확인
python3 cheongyak_report.py --test          # 텔레그램 연결 테스트
python3 cheongyak_report.py                 # 실제 발송
```

## 📁 구조

```
cheongyak_report.py              # 조회 · 분류 · 발송 전부 (단일 파일)
.github/workflows/daily-report.yml  # 매일 08:00 KST 스케줄
.env.example                     # 로컬 실행용 설정 템플릿
```

## ❓ 트러블슈팅

| 증상 | 확인할 것 |
|---|---|
| 리포트가 안 옴 | [Actions 탭](https://github.com/3dagger/cheongyak-bot/actions) 실행 로그. Fork 직후라면 워크플로우가 꺼져 있을 수 있음 |
| API 인증 에러 | 공공데이터포털 키는 발급 후 반영까지 수 분~1시간 걸림. 개발계정 활용기간(24개월) 만료 시 연장신청 필요 |
| 리포트 하단에 `⚠️ LH 조회 실패` | LH 분양임대공고문 조회 서비스를 활용신청했는지 확인 |
| 리포트 하단에 `⚠️ SH 조회 실패` | SH 홈페이지 점검 중이거나 게시판 구조가 바뀐 경우. `SH_ROW_RE` 파싱 규칙 확인 |
| 같은 공고가 매일 🆕에 뜸 | Actions 로그의 `공고 기록 복원`·`공고 기록 저장` 단계 확인 |
| 봇이 메시지를 못 보냄 | 채팅방에서 봇을 차단했는지, 그룹방이면 봇이 초대돼 있는지 확인 |
| `--get-chat-id`에 아무것도 안 나옴 | 봇에게 먼저 메시지를 한 번 보내야 함 |

## 📄 라이선스

[MIT](LICENSE)
