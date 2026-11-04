#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""청약홈(한국부동산원)·LH·SH 분양/임대 공고를 조회해 텔레그램으로 데일리 리포트를 보냅니다.

사용법:
  python3 cheongyak_report.py               # 리포트 생성 후 텔레그램 전송
  python3 cheongyak_report.py --dry-run     # 전송하지 않고 터미널에 출력
  python3 cheongyak_report.py --get-chat-id # 봇에게 말 건 사람의 chat_id 조회
  python3 cheongyak_report.py --test        # 텔레그램으로 테스트 메시지 전송

설정은 같은 폴더의 .env 파일에서 읽는다 (환경변수가 있으면 그 값이 우선).
"""

import html
import json
import re
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
# (유형 라벨, 엔드포인트, 모집공고일 조건의 날짜 형식). 날짜 형식은 API 명세를 따릅니다.
ENDPOINTS = [
    ("APT", "getAPTLttotPblancDetail", "%Y-%m-%d"),
    ("무순위·잔여", "getRemndrLttotPblancDetail", "%Y-%m-%d"),
    ("임의공급", "getOPTLttotPblancDetail", "%Y%m%d"),
    ("오피스텔 등", "getUrbtyOfctlLttotPblancDetail", "%Y-%m-%d"),
    ("공공지원 민간임대", "getPblPvtRentLttotPblancDetail", "%Y%m%d"),
]
# 주택형별 조회에서 공고 단위로 합산할 특별공급 세대수 필드입니다.
MODEL_ENDPOINTS = {
    "APT": ("getAPTLttotPblancMdl", (("신생아", "NWBB_HSHLDCO"), ("신혼", "NWWDS_HSHLDCO"))),
    "공공지원 민간임대": ("getPblPvtRentLttotPblancMdl", (("신혼", "SPSPLY_NEW_MRRG_HSHLDCO"),)),
}
# 접수 단계별 (라벨, 시작일 필드, 종료일 필드). 지역별로 나뉜 1순위는 가장 이른 시작~가장 늦은 종료로 묶습니다.
PHASES = [
    ("특공", ("SPSPLY_RCEPT_BGNDE",), ("SPSPLY_RCEPT_ENDDE",)),
    ("1순위",
     ("GNRL_RNK1_CRSPAREA_RCPTDE", "GNRL_RNK1_ETC_GG_RCPTDE", "GNRL_RNK1_ETC_AREA_RCPTDE"),
     ("GNRL_RNK1_CRSPAREA_ENDDE", "GNRL_RNK1_ETC_GG_ENDDE", "GNRL_RNK1_ETC_AREA_ENDDE")),
    ("일반", ("GNRL_RCEPT_BGNDE",), ("GNRL_RCEPT_ENDDE",)),
]
FALLBACK_PHASE = ("접수", ("RCEPT_BGNDE", "SUBSCRPT_RCEPT_BGNDE"),
                  ("RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE"))
UPCOMING_DAYS = 14

LH_LIST_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
LH_CATEGORIES = ("05", "06", "13")  # 분양주택, 임대주택, 주거복지(신혼희망타운 등). 토지·상가는 제외합니다.
LH_DAYS = 90  # LH 임대는 게시 후 40일 넘게 접수하는 공고가 있어 청약홈보다 길게 잡습니다.
SH_BOARD_URL = "https://www.i-sh.co.kr/app/lay2/program/S1T294C297/www/brd/m_247/{}.do"
SH_BOARDS = (("1", "SH 분양"), ("2", "SH 임대"))
SH_EXCLUDE = ("당첨", "결과", "명단", "발표", "동호", "서류")
SH_ROW_RE = re.compile(r"getDetailView\('(\d+)'\).*?>(.*?)</a>.*?(\d{4}-\d{2}-\d{2})", re.S)

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


def http_get(url, params=None, retries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cheongyak-report/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception as err:  # noqa: BLE001 - 재시도 후 마지막 에러를 올림
            last_err = err
            time.sleep(2 * (attempt + 1))
    raise last_err


def http_get_json(url, params=None, retries=3):
    return json.loads(http_get(url, params, retries))


def http_post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def norm_date(val):
    """YYYYMMDD·YYYY.MM.DD 등을 YYYY-MM-DD로 맞춥니다. 날짜가 아니면 그대로 둡니다."""
    text = str(val or "")
    digits = re.sub(r"\D", "", text)
    if len(digits) != 8:
        return text
    return "{}-{}-{}".format(digits[:4], digits[4:6], digits[6:])


def to_int(val):
    digits = re.sub(r"\D", "", str(val or ""))
    return int(digits) if digits else 0


def fetch_notices(service_key, since):
    """모집공고일이 since 이후인 청약홈 공고를 모든 엔드포인트에서 수집합니다."""
    items = []
    for type_label, endpoint, date_fmt in ENDPOINTS:
        page = 1
        while True:
            body = http_get_json(API_BASE + "/" + endpoint, {
                "page": page,
                "perPage": 300,
                "serviceKey": service_key,
                "cond[RCRIT_PBLANC_DE::GTE]": since.strftime(date_fmt),
            })
            rows = body.get("data") or []
            for row in rows:
                for key in row:
                    if key.endswith("DE") and row[key]:
                        row[key] = norm_date(row[key])
                row["_type"] = type_label
                items.append(row)
            if len(rows) < 300 or page >= 5:
                break
            page += 1
    return [r for r in items if field(r, "RCRIT_PBLANC_DE") >= since.isoformat()]


def attach_special_counts(service_key, rows):
    """공고별 신생아·신혼 특별공급 세대수를 row["_special"]에 붙이고, 조회에 실패한 건수를 돌려줍니다."""
    failed = 0
    for row in rows:
        endpoint, fields = MODEL_ENDPOINTS[row["_type"]]
        try:
            body = http_get_json(API_BASE + "/" + endpoint, {
                "page": 1,
                "perPage": 100,
                "serviceKey": service_key,
                "cond[HOUSE_MANAGE_NO::EQ]": field(row, "HOUSE_MANAGE_NO"),
            })
        except Exception:  # noqa: BLE001 - 세대수는 보조 정보라 실패해도 리포트는 보냅니다
            failed += 1
            continue
        models = body.get("data") or []
        row["_special"] = {label: sum(to_int(m.get(name)) for m in models)
                           for label, name in fields}
    return failed


def lh_rows(body):
    """LH 응답은 [{"dsSch": ...}, {"dsList": [...]}] 형태의 배열입니다."""
    parts = body if isinstance(body, list) else [body]
    for part in parts:
        if isinstance(part, dict) and part.get("dsList"):
            return part["dsList"]
    return []


def short_region(name):
    """청약홈 표기(서울·경기·인천)에 맞춰 '서울특별시', '경기도' 같은 행정구역 접미사를 뗍니다."""
    for suffix in ("특별자치도", "특별자치시", "특별시", "광역시"):
        name = name.replace(suffix, "")
    return name[:2] if len(name) == 3 and name.endswith("도") else name


def lh_to_row(raw):
    kind = field(raw, "AIS_TP_CD_NM", "UPP_AIS_TP_NM")
    closing = norm_date(field(raw, "CLSG_DT"))
    return {
        "_type": "LH",
        "SUBSCRPT_AREA_CODE_NM": short_region(field(raw, "CNP_CD_NM")),
        "HOUSE_NM": field(raw, "PAN_NM"),
        "HOUSE_DTL_SECD_NM": "LH " + kind if kind else "LH",
        "RCRIT_PBLANC_DE": norm_date(field(raw, "PAN_NT_ST_DT", "PAN_DT")),
        "PBLANC_URL": field(raw, "DTL_URL"),
        "_phases": [("마감", "", closing)] if closing else [],
    }


def fetch_lh(service_key, today):
    """LH청약플러스 분양·임대·주거복지 공고를 게시일 기준 최근 LH_DAYS일치 수집합니다.

    문서상 조건은 PAN_NT_ST_DT·CLSG_DT지만 실제로는 무시되고 PAN_ST_DT·PAN_ED_DT(YYYYMMDD)가 적용됩니다.
    """
    items = []
    for category in LH_CATEGORIES:
        for page in range(1, 11):
            rows = lh_rows(http_get_json(LH_LIST_URL, {
                "serviceKey": service_key,
                "PG_SZ": 100,
                "PAGE": page,
                "UPP_AIS_TP_CD": category,
                "PAN_ST_DT": (today - timedelta(days=LH_DAYS)).strftime("%Y%m%d"),
                "PAN_ED_DT": today.strftime("%Y%m%d"),
            }))
            items.extend(lh_to_row(r) for r in rows)
            if len(rows) < 100:
                break
    return items


def parse_sh_board(page, board, label):
    """SH 공고 게시판 HTML에서 입주자 모집 공고만 골라냅니다. 당첨자·결과 게시 글은 제외합니다."""
    body = page[page.find("<tbody"):page.find("</tbody>")]
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        match = SH_ROW_RE.search(tr)
        if not match:
            continue
        seq, raw_title, posted = match.groups()
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", raw_title)).split())
        if not ("입주" in title and "모집" in title) or any(w in title for w in SH_EXCLUDE):
            continue
        rows.append({
            "_type": "SH",
            "SUBSCRPT_AREA_CODE_NM": "서울",
            "HOUSE_NM": title,
            "HOUSE_DTL_SECD_NM": label,
            "RCRIT_PBLANC_DE": posted,
            "PBLANC_URL": SH_BOARD_URL.format("view") + "?" + urllib.parse.urlencode(
                {"multi_itm_seq": board, "seq": seq}),
            "_phases": [],
        })
    return rows


def fetch_sh():
    """SH 인터넷청약 공개 게시판(분양·임대) 첫 페이지를 읽습니다. 공식 API가 없어 HTML을 파싱합니다."""
    items = []
    for board, label in SH_BOARDS:
        page = http_get(SH_BOARD_URL.format("list"), {"multi_itm_seq": board})
        items.extend(parse_sh_board(page, board, label))
    return items


def collect_optional(label, fetch, warnings):
    try:
        return fetch()
    except Exception as err:  # noqa: BLE001 - 보조 소스 실패가 리포트 전체를 막지 않게 합니다
        warnings.append("{} 조회 실패: {}".format(label, err))
        return []


def field(row, *names):
    for name in names:
        val = row.get(name)
        if val:
            return str(val)
    return ""


def phases(row):
    """[(라벨, 시작일, 종료일)] 형태의 접수 일정을 돌려줍니다."""
    if "_phases" in row:
        return row["_phases"]
    result = []
    for label, begin_keys, end_keys in PHASES:
        begins = [str(row[k]) for k in begin_keys if row.get(k)]
        ends = [str(row[k]) for k in end_keys if row.get(k)]
        if begins:
            result.append((label, min(begins), max(ends) if ends else min(begins)))
    if result:
        return result
    label, begin_keys, end_keys = FALLBACK_PHASE
    begin, end = field(row, *begin_keys), field(row, *end_keys)
    return [(label, begin, end)] if begin or end else []


def sort_key(row):
    return field(row, "SUBSCRPT_AREA_CODE_NM"), min((b or e for _, b, e in phases(row)), default="")


def last_date(row):
    return max((e or b for _, b, e in phases(row)), default="")


def has_family_quota(row):
    return any(count > 0 for count in row.get("_special", {}).values())


def house_type(row):
    if row["_type"] == "APT":
        secd, dtl = field(row, "HOUSE_SECD_NM"), field(row, "HOUSE_DTL_SECD_NM")
        return " ".join(p for p in (secd if secd != "APT" else "", dtl) if p) or "APT"
    return field(row, "HOUSE_DTL_SECD_NM", "HOUSE_DETAIL_SECD_NM") or row["_type"]


def format_phase(label, begin, end):
    if not begin:
        return "{} {}".format(label, end[5:])
    if not end or begin == end:
        return "{} {}".format(label, begin[5:])
    return "{} {}~{}".format(label, begin[5:], end[5:])


def format_line(row):
    area = field(row, "SUBSCRPT_AREA_CODE_NM") or "지역미상"
    name = html.escape(field(row, "HOUSE_NM") or "이름미상")
    households = field(row, "TOT_SUPLY_HSHLDCO")
    hh = " {}세대".format(households) if households else ""
    details = [format_phase(*phase) for phase in phases(row)]
    url = field(row, "PBLANC_URL")
    if url:
        details.append('<a href="{}">공고</a>'.format(html.escape(url, quote=True)))
    line = "• [{}] {} ({}{})".format(area, name, house_type(row), hh)
    if details:
        line += "\n   " + " · ".join(details)
    if has_family_quota(row):
        line += "\n   👶 " + " · ".join("{} {}세대".format(label, count)
                                       for label, count in row["_special"].items() if count)
    return line


def build_report(items, today, warnings=()):
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    today_s = today.isoformat()
    upcoming_until = (today + timedelta(days=UPCOMING_DAYS)).isoformat()

    new_notices = [r for r in items if field(r, "RCRIT_PBLANC_DE") >= yesterday]
    family = [r for r in items if has_family_quota(r)
              and any(today_s <= b <= upcoming_until for _, b, _ in phases(r))]
    opening = [r for r in items if any(b == today_s for _, b, _ in phases(r))]
    closing = [r for r in items if any(e in (today_s, tomorrow) for _, _, e in phases(r))]

    header = "🏠 <b>청약 데일리 리포트</b> — {} ({})".format(
        today_s, WEEKDAY_KO[today.weekday()])
    sections = []

    def add_section(title, rows):
        if rows:
            rows = sorted(rows, key=sort_key)
            sections.append("<b>{}</b>\n{}".format(
                title, "\n".join(format_line(r) for r in rows)))

    add_section("🆕 새로 올라온 공고 (어제~오늘)", new_notices)
    add_section("👶 신생아·신혼 특공 접수 예정 ({}일 내)".format(UPCOMING_DAYS), family)
    add_section("📬 오늘 접수 시작", opening)
    add_section("⏰ 마감 임박 (오늘·내일)", closing)

    footer = "".join("\n⚠️ " + html.escape(w) for w in warnings)
    footer = "\n" + footer if footer else ""
    if not sections:
        return header + "\n\n오늘은 새로운 공고·접수 소식이 없습니다." + footer, False
    return header + "\n\n" + "\n\n".join(sections) + footer, True


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
    since = today - timedelta(days=45)
    area_filter = [a.strip() for a in cfg.get("AREA_FILTER", "").split(",") if a.strip()]
    warnings = []

    items = fetch_notices(service_key, since)
    items += collect_optional("LH", lambda: fetch_lh(service_key, today), warnings)
    if not area_filter or any("서울" in a for a in area_filter):
        items += collect_optional("SH", fetch_sh, warnings)

    if area_filter:
        items = [r for r in items
                 if field(r, "SUBSCRPT_AREA_CODE_NM") == "전국"
                 or any(a in field(r, "SUBSCRPT_AREA_CODE_NM") for a in area_filter)]

    targets = [r for r in items
               if r["_type"] in MODEL_ENDPOINTS and last_date(r) >= today.isoformat()]
    failed = attach_special_counts(service_key, targets)
    if failed:
        warnings.append("특공 세대수 조회 실패 {}건".format(failed))

    report, has_news = build_report(items, today, warnings)

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
