# 청약 데일리 리포트 봇

매일 아침 8시에 청약홈(한국부동산원) 분양정보를 조회해서 텔레그램으로 보내주는 스크립트.

- 🆕 어제~오늘 새로 올라온 공고 (APT / 무순위·잔여세대 / 오피스텔 등)
- 📬 오늘 접수 시작하는 단지
- ⏰ 오늘·내일 마감하는 단지

## 최초 설정 (한 번만)

### 1. 공공데이터포털 API 키 발급
1. https://www.data.go.kr 가입/로그인
2. **"한국부동산원_주택청약 분양정보 조회 서비스"** 검색 → 활용신청 (자동 승인)
3. 마이페이지에서 **일반 인증키(Decoding)** 값을 복사
4. `.env`의 `CHEONGYAK_SERVICE_KEY=` 에 붙여넣기

### 2. 텔레그램 봇 생성
1. 텔레그램에서 **@BotFather** 검색 → `/newbot` → 이름/아이디 입력
2. 발급된 토큰을 `.env`의 `TELEGRAM_BOT_TOKEN=` 에 붙여넣기
3. 만든 봇에게 아무 메시지나 하나 보내기 (그룹방에서 받으려면 봇을 그룹에 초대 후 메시지)
4. 아래 실행 후 나온 chat_id를 `.env`의 `TELEGRAM_CHAT_ID=` 에 입력
   ```bash
   python3 ~/cheongyak-bot/cheongyak_report.py --get-chat-id
   ```

### 3. 동작 확인
```bash
python3 ~/cheongyak-bot/cheongyak_report.py --test      # 텔레그램 연결 테스트
python3 ~/cheongyak-bot/cheongyak_report.py --dry-run   # 리포트 내용 미리보기
python3 ~/cheongyak-bot/cheongyak_report.py             # 실제 전송
```

## 스케줄

`~/Library/LaunchAgents/com.nuyhoos.cheongyak-report.plist` 가 매일 **08:00** 에 실행한다.
8시에 Mac이 잠들어 있었다면 깨어날 때 한 번 실행된다 (전원이 꺼져 있으면 그날은 건너뜀).

시간 변경: plist의 `Hour`/`Minute` 수정 후
```bash
launchctl bootout gui/$(id -u)/com.nuyhoos.cheongyak-report
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nuyhoos.cheongyak-report.plist
```

로그: `~/cheongyak-bot/logs/`

## 설정 (.env)

| 키 | 설명 |
|---|---|
| `CHEONGYAK_SERVICE_KEY` | 공공데이터포털 인증키 (Decoding) |
| `TELEGRAM_BOT_TOKEN` | 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 받을 채팅방 ID |
| `AREA_FILTER` | 지역 필터, 쉼표 구분 (예: `서울,경기,인천`). 비우면 전국 |
| `SEND_WHEN_EMPTY` | 소식 없는 날에도 메시지 보낼지 (`true`/`false`) |
