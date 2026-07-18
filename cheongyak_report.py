#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""청약홈(한국부동산원) 분양정보를 조회해 텔레그램으로 데일리 리포트를 보낸다.

사용법:
  python3 cheongyak_report.py               # 리포트 생성 후 텔레그램 전송
  python3 cheongyak_report.py --dry-run     # 전송하지 않고 터미널에 출력
  python3 cheongyak_report.py --get-chat-id # 봇에게 말 건 사람의 chat_id 조회
  python3 cheongyak_report.py --test        # 텔레그램으로 테스트 메시지 전송

설정은 같은 폴더의 .env 파일에서 읽는다 (환경변수가 있으면 그 값이 우선).
"""

import html
import json
import sys
import os
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

API_BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
ENDPOINTS = [
    ("APT", "getAPTLttotPblancDetail"),
    ("무순위·잔여", "getRemndrLttotPblancDetail"),
    ("오피스텔 등", "getUrbtyOfctlLttotPblancDetail"),
]

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def load_config():
    cfg = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            cfg[key.strip()] = val.strip().strip('"').strip("'")
    for key in ("CHEONGYAK_SERVICE_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "AREA_FILTER", "SEND_WHEN_EMPTY"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def http_get_json(url, params=None, retries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cheongyak-report/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as err:  # noqa: BLE001 - 재시도 후 마지막 에러를 올림
            last_err = err
            time.sleep(2 * (attempt + 1))
    raise last_err


def http_post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_notices(service_key, since):
    """모집공고일이 since 이후인 공고를 세 개 엔드포인트에서 모두 수집."""
    items = []
    for type_label, endpoint in ENDPOINTS:
        page = 1
        while True:
            body = http_get_json(API_BASE + "/" + endpoint, {
                "page": page,
                "perPage": 300,
                "serviceKey": service_key,
                "cond[RCRIT_PBLANC_DE::GTE]": since.isoformat(),
            })
            rows = body.get("data") or []
            for row in rows:
                row["_type"] = type_label
                items.append(row)
            if len(rows) < 300 or page >= 5:
                break
            page += 1
    return items


def field(row, *names):
    for name in names:
        val = row.get(name)
        if val:
            return str(val)
    return ""


def rcept_begin(row):
    return field(row, "RCEPT_BGNDE", "SUBSCRPT_RCEPT_BGNDE")


def rcept_end(row):
    return field(row, "RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE")


def format_line(row):
    area = field(row, "SUBSCRPT_AREA_CODE_NM") or "지역미상"
    name = html.escape(field(row, "HOUSE_NM") or "이름미상")
    house_type = field(row, "HOUSE_DTL_SECD_NM") or row["_type"]
    households = field(row, "TOT_SUPLY_HSHLDCO")
    hh = " {}세대".format(households) if households else ""
    begin, end = rcept_begin(row), rcept_end(row)
    period = "접수 {} ~ {}".format(begin[5:], end[5:]) if begin and end else ""
    url = field(row, "PBLANC_URL")
    link = ' · <a href="{}">공고</a>'.format(html.escape(url, quote=True)) if url else ""
    return "• [{}] {} ({}{})\n   {}{}".format(area, name, house_type, hh, period, link)


def build_report(items, today):
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    today_s = today.isoformat()

    new_notices = [r for r in items if field(r, "RCRIT_PBLANC_DE") >= yesterday]
    opening = [r for r in items if rcept_begin(r) == today_s]
    closing = [r for r in items if rcept_end(r) in (today_s, tomorrow)]

    header = "🏠 <b>청약 데일리 리포트</b> — {} ({})".format(
        today_s, WEEKDAY_KO[today.weekday()])
    sections = []

    def add_section(title, rows):
        if rows:
            rows = sorted(rows, key=lambda r: (field(r, "SUBSCRPT_AREA_CODE_NM"),
                                               rcept_begin(r)))
            sections.append("<b>{}</b>\n{}".format(
                title, "\n".join(format_line(r) for r in rows)))

    add_section("🆕 새로 올라온 공고 (어제~오늘)", new_notices)
    add_section("📬 오늘 접수 시작", opening)
    add_section("⏰ 마감 임박 (오늘·내일)", closing)

    if not sections:
        return header + "\n\n오늘은 새로운 공고·접수 소식이 없습니다.", False
    return header + "\n\n" + "\n\n".join(sections), True


def split_message(text, limit=3800):
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks


def send_telegram(token, chat_id, text):
    for chunk in split_message(text):
        result = http_post_json(
            "https://api.telegram.org/bot{}/sendMessage".format(token),
            {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
             "disable_web_page_preview": True})
        if not result.get("ok"):
            raise RuntimeError("텔레그램 전송 실패: {}".format(result))


def cmd_get_chat_id(cfg):
    token = cfg.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit(".env에 TELEGRAM_BOT_TOKEN을 먼저 넣어주세요.")
    body = http_get_json("https://api.telegram.org/bot{}/getUpdates".format(token))
    chats = {}
    for update in body.get("result", []):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("username") \
                or "{} {}".format(chat.get("first_name", ""), chat.get("last_name", "")).strip()
    if not chats:
        print("아직 수신된 메시지가 없습니다. 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
    else:
        for cid, name in chats.items():
            print("chat_id: {}  ({})".format(cid, name))


def main():
    args = sys.argv[1:]
    cfg = load_config()

    if "--get-chat-id" in args:
        cmd_get_chat_id(cfg)
        return

    token = cfg.get("TELEGRAM_BOT_TOKEN")
    chat_id = cfg.get("TELEGRAM_CHAT_ID")

    if "--test" in args:
        if not (token and chat_id):
            sys.exit(".env에 TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 먼저 넣어주세요.")
        send_telegram(token, chat_id, "✅ 청약 리포트 봇 연결 테스트 성공!")
        print("테스트 메시지를 보냈습니다.")
        return

    service_key = cfg.get("CHEONGYAK_SERVICE_KEY")
    missing = [k for k, v in (("CHEONGYAK_SERVICE_KEY", service_key),
                              ("TELEGRAM_BOT_TOKEN", token),
                              ("TELEGRAM_CHAT_ID", chat_id)) if not v]
    if missing and not ("--dry-run" in args and service_key):
        sys.exit("[설정 필요] .env에 다음 값이 비어 있습니다: " + ", ".join(missing))

    today = date.today()
    items = fetch_notices(service_key, today - timedelta(days=45))

    area_filter = [a.strip() for a in cfg.get("AREA_FILTER", "").split(",") if a.strip()]
    if area_filter:
        items = [r for r in items
                 if any(a in field(r, "SUBSCRPT_AREA_CODE_NM") for a in area_filter)]

    report, has_news = build_report(items, today)

    if "--dry-run" in args:
        print(report)
        return

    if not has_news and cfg.get("SEND_WHEN_EMPTY", "true").lower() == "false":
        print("새 소식 없음, 전송 생략 (SEND_WHEN_EMPTY=false)")
        return

    send_telegram(token, chat_id, report)
    print("{} 리포트 전송 완료 (공고 {}건 조회)".format(today.isoformat(), len(items)))


if __name__ == "__main__":
    main()
