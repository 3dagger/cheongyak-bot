#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""청약홈(한국부동산원)·LH·SH 분양/임대 공고를 조회해 텔레그램으로 데일리 리포트를 보냅니다.

사용법:
  python3 cheongyak_report.py               # 리포트 생성 후 텔레그램 전송
  python3 cheongyak_report.py --dry-run     # 전송하지 않고 터미널에 출력
  python3 cheongyak_report.py --get-chat-id # 봇에게 말 건 사람의 chat_id 조회
  python3 cheongyak_report.py --test        # 텔레그램으로 테스트 메시지 전송

설정은 같은 폴더의 .env 파일에서 읽습니다 (환경변수가 있으면 그 값이 우선입니다).
"""

import argparse
import html
import json
import re
import sys
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
# 이미 리포트한 공고 ID를 기록합니다. GitHub Actions에서는 캐시로 실행 간에 이어집니다.
SEEN_PATH = BASE_DIR / ".state" / "seen.json"
SEEN_KEEP_DAYS = 180  # 수집 기간(청약홈 45일·LH 90일)보다 넉넉히 보관합니다.
NEW_LOOKBACK_DAYS = 14  # 처음 보는 공고라도 공고일이 이보다 오래되면 새 공고로 치지 않습니다.

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
DETAIL_FAILURE_LIMIT = 3  # 공고별 상세 조회가 연달아 이만큼 실패하면 API 장애로 보고 남은 공고는 조회하지 않습니다.

LH_LIST_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
LH_CATEGORIES = ("05", "06", "13")  # 분양주택, 임대주택, 주거복지(신혼희망타운 등). 토지·상가는 제외합니다.
LH_EXCLUDE_TYPES = ("가정어린이집",)  # 임대주택 분류에 섞여 오는 주거 외 공고입니다.
LH_DAYS = 90  # LH 임대는 게시 후 40일 넘게 접수하는 공고가 있어 청약홈보다 길게 잡습니다.
LH_DETAIL_URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"
LH_DETAIL_KEYS = ("PAN_ID", "SPL_INF_TP_CD", "CCR_CNNT_SYS_DS_CD", "UPP_AIS_TP_CD", "AIS_TP_CD")
LH_DATE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")
# LH 공공분양은 청약홈에도 올라오며, 공고 본문의 주택관리번호로 같은 공고인지 알 수 있습니다.
LH_HOUSE_NO_RE = re.compile(r"주택관리번호[^0-9]{0,10}(\d{10})")
SH_BOARD_URL = "https://www.i-sh.co.kr/app/lay2/program/S1T294C297/www/brd/m_247/{}.do"
SH_BOARDS = (("1", "SH 분양"), ("2", "SH 임대"))
SH_EXCLUDE = ("당첨", "결과", "명단", "발표", "동호", "서류")
SH_ROW_RE = re.compile(r"getDetailView\('(\d+)'\).*?>(.*?)</a>.*?(\d{4}-\d{2}-\d{2})", re.S)

KST = timezone(timedelta(hours=9))
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]
REGION_NAMES = (
    ("서울", ("서울",)), ("부산", ("부산",)), ("대구", ("대구",)), ("인천", ("인천",)),
    ("광주", ("광주",)), ("대전", ("대전",)), ("울산", ("울산",)), ("세종", ("세종",)),
    ("경기", ("경기",)), ("강원", ("강원",)), ("충북", ("충북", "충청북도")),
    ("충남", ("충남", "충청남도")), ("전북", ("전북", "전라북도")), ("전남", ("전남", "전라남도")),
    ("경북", ("경북", "경상북도")), ("경남", ("경남", "경상남도")), ("제주", ("제주",)),
)


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
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last_err


def http_get_json(url, params=None, retries=3):
    return json.loads(http_get(url, params, retries))


def http_post_json(url, payload):
    """JSON을 POST하고 응답 JSON을 돌려줍니다. 4xx·5xx라도 본문이 JSON이면 그 내용을 돌려줍니다."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        # 텔레그램은 거절할 때도 {"ok": false, "description": ...}으로 이유를 알려 줍니다.
        with err:
            body = err.read()
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError:
            raise err from None


def today_kst(now=None):
    """실행하는 기기의 시간대와 상관없이 한국 날짜를 돌려줍니다. 접수일·마감일이 한국 날짜이기 때문입니다."""
    return (now or datetime.now(timezone.utc)).astimezone(KST).date()


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
                row["_id"] = "{}:{}:{}".format(type_label, field(row, "HOUSE_MANAGE_NO"),
                                               field(row, "PBLANC_NO"))
                items.append(row)
            if len(rows) < 300 or page >= 5:
                break
            page += 1
    return [r for r in items if field(r, "RCRIT_PBLANC_DE") >= since.isoformat()]


def lookup_each(rows, lookup):
    """rows마다 lookup(row)을 부르고 실패한 건수를 돌려줍니다.

    공고별 상세 정보는 보조 정보라 실패해도 리포트는 보냅니다. 연달아 DETAIL_FAILURE_LIMIT번 실패하면
    API 장애로 보고 남은 공고는 조회하지 않고 실패로 셉니다. 응답이 없을 때는 한 건에 1분 넘게 걸려,
    끝까지 시도하면 리포트가 몇 시간 늦어지기 때문입니다.
    """
    failed = streak = 0
    for index, row in enumerate(rows):
        try:
            lookup(row)
        except Exception:  # noqa: BLE001 - 어떤 이유로 실패하든 그 공고만 보조 정보 없이 보냅니다
            failed += 1
            streak += 1
            if streak >= DETAIL_FAILURE_LIMIT:
                return failed + len(rows) - index - 1
        else:
            streak = 0
    return failed


def attach_special_counts(service_key, rows):
    """공고별 신생아·신혼 특별공급 세대수를 row["_special"]에 붙이고, 조회에 실패한 건수를 돌려줍니다."""
    def lookup(row):
        endpoint, fields = MODEL_ENDPOINTS[row["_type"]]
        body = http_get_json(API_BASE + "/" + endpoint, {
            "page": 1,
            "perPage": 100,
            "serviceKey": service_key,
            "cond[HOUSE_MANAGE_NO::EQ]": field(row, "HOUSE_MANAGE_NO"),
        })
        models = body.get("data") or []
        row["_special"] = {label: sum(to_int(m.get(name)) for m in models)
                           for label, name in fields}
    return lookup_each(rows, lookup)


def lh_rows(body):
    """LH 응답은 [{"dsSch": ...}, {"dsList": [...]}] 형태의 배열입니다."""
    parts = body if isinstance(body, list) else [body]
    for part in parts:
        if isinstance(part, dict) and part.get("dsList"):
            return part["dsList"]
    return []


def short_region(name):
    """청약홈 표기(서울·경기·충북)에 맞춰 '서울특별시', '경기도', '충청북도' 같은 이름을 줄입니다."""
    for suffix in ("특별자치도", "특별자치시", "특별시", "광역시"):
        name = name.replace(suffix, "")
    for short, names in REGION_NAMES:
        if name in names:
            return short
    return name[:2] if len(name) == 3 and name.endswith("도") else name


def regions_in(text):
    """제목에 나온 시·도를 짧은 이름(경남, 경기 등)으로 돌려줍니다."""
    return {short for short, names in REGION_NAMES if any(name in text for name in names)}


def parse_area_filter(text):
    """쉼표로 구분한 지역을 청약홈 표기(서울·경기·충북)로 맞춘 목록을 돌려줍니다.

    '서울특별시'·'경기도'처럼 써도 알아봅니다. 알아보지 못한 이름은 그대로 둡니다.
    비어 있거나 '전국'이 있으면 거르지 않도록 빈 목록을 돌려줍니다.
    """
    areas = [a.strip() for a in text.split(",") if a.strip()]
    if "전국" in areas:
        return []
    result = []
    for area in areas:
        result.extend(sorted(regions_in(area)) or [area])
    return result


def unknown_areas(area_filter):
    """지역 필터에서 시·도 이름으로 알아보지 못한 항목을 돌려줍니다. 이런 항목은 어떤 공고와도 맞지 않습니다."""
    known = {short for short, _ in REGION_NAMES}
    return [a for a in area_filter if a not in known]


def in_area(row, area_filter):
    """지역 필터를 통과하는지 봅니다.

    LH는 지역이 분명한 공고에도 '전국'을 다는 경우가 있어, 전국 공고는 제목에 나온 시·도로 다시 판단합니다.
    제목에 시·도가 없으면 정말 전국 공고로 보고 통과시킵니다.
    """
    region = field(row, "SUBSCRPT_AREA_CODE_NM")
    if region != "전국":
        return any(a in region for a in area_filter)
    mentioned = regions_in(field(row, "HOUSE_NM"))
    return not mentioned or any(a in m or m in a for a in area_filter for m in mentioned)


def lh_to_row(raw):
    kind = field(raw, "AIS_TP_CD_NM", "UPP_AIS_TP_NM")
    closing = norm_date(field(raw, "CLSG_DT"))
    return {
        "_type": "LH",
        "_id": "LH:" + field(raw, "PAN_ID"),
        "SUBSCRPT_AREA_CODE_NM": short_region(field(raw, "CNP_CD_NM")),
        "HOUSE_NM": field(raw, "PAN_NM"),
        "HOUSE_DTL_SECD_NM": "LH " + kind if kind else "LH",
        "RCRIT_PBLANC_DE": norm_date(field(raw, "PAN_NT_ST_DT", "PAN_DT")),
        "PBLANC_URL": field(raw, "DTL_URL"),
        "_phases": [("마감", "", closing)] if closing else [],
        "_lh_keys": {key: field(raw, key) for key in LH_DETAIL_KEYS},
    }


def lh_phase_label(target):
    """LH 공급일정의 공급 대상명을 청약홈과 같은 단계 라벨로 묶습니다."""
    if "특별" in target or target == "기관추천":
        return "특공"
    if target.startswith("일반공급") or "우선공급" in target:
        return "일반"
    return target or "접수"


def lh_schedule(rows):
    """LH 공급일정(dsSplScdl)을 [(라벨, 시작일, 종료일)]과 신생아·신혼 특공 여부로 바꿉니다."""
    spans = {}
    targets = [field(row, "HS_SBSC_ACP_TRG_CD_NM").strip() for row in rows]
    family = {label: None for label in ("신생아", "신혼") if any(label in t for t in targets)}
    for row, target in zip(rows, targets):
        dates = ["-".join(m) for m in LH_DATE_RE.findall(field(row, "ACP_DTTM"))]
        if not dates:
            continue
        label = lh_phase_label(target)
        begin, end = spans.get(label, (dates[0], dates[-1]))
        spans[label] = (min(begin, dates[0]), max(end, dates[-1]))
    steps = sorted(((label, b, e) for label, (b, e) in spans.items()), key=lambda p: p[1])
    return steps, family


def lh_dataset(body, name):
    parts = body if isinstance(body, list) else [body]
    return next((p[name] for p in parts if isinstance(p, dict) and name in p), [])


def attach_lh_schedules(service_key, rows):
    """LH 공고별 상세정보로 단계별 접수일, 신생아·신혼 특공 여부, 청약홈 주택관리번호를 붙입니다.

    조회에 실패한 건수를 돌려줍니다. 실패한 공고는 목록에서 받은 마감일로 리포트합니다.
    """
    def lookup(row):
        body = http_get_json(LH_DETAIL_URL, dict(serviceKey=service_key, **row["_lh_keys"]))
        notice = " ".join(field(d, "PAN_DTL_CTS") for d in lh_dataset(body, "dsEtcInfo"))
        match = LH_HOUSE_NO_RE.search(notice)
        if match:
            row["HOUSE_MANAGE_NO"] = match.group(1)
        steps, family = lh_schedule(lh_dataset(body, "dsSplScdl"))
        if steps:
            row["_phases"] = row["_lh_steps"] = steps
        if family:
            row["_special"] = family
    return lookup_each(rows, lookup)


def merge_lh_into_applyhome(items):
    """청약홈에도 올라온 LH 공고는 청약홈 쪽 하나만 남깁니다.

    세대수는 청약홈 값을 쓰고, 접수 일정은 공급 대상별로 나뉜 LH 상세 일정으로 바꿉니다.
    """
    latest_lh = {}  # 정정공고가 있으면 공고일이 가장 늦은 LH 공고의 일정을 씁니다.
    for row in sorted((r for r in items if r["_type"] == "LH"), key=lambda r: field(r, "RCRIT_PBLANC_DE")):
        if field(row, "HOUSE_MANAGE_NO") and row.get("_lh_steps"):
            latest_lh[field(row, "HOUSE_MANAGE_NO")] = row
    merged = set()
    for row in items:
        no = field(row, "HOUSE_MANAGE_NO")
        if row["_type"] not in ("LH", "SH") and no in latest_lh:
            row["_phases"] = latest_lh[no]["_lh_steps"]
            merged.add(no)
    return [r for r in items if not (r["_type"] == "LH" and field(r, "HOUSE_MANAGE_NO") in merged)]


def fetch_lh(service_key, today):
    """LH청약플러스 분양·임대·주거복지 공고를 게시일 기준 최근 LH_DAYS일치 수집합니다.

    문서상 조건은 PAN_NT_ST_DT·CLSG_DT지만 실제로는 무시되고 PAN_ST_DT·PAN_ED_DT(YYYYMMDD)가 적용됩니다.
    전 유형 합계가 0건이면 응답 형식이 바뀐 것으로 보고 예외를 던집니다.
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
            items.extend(lh_to_row(r) for r in rows
                         if field(r, "AIS_TP_CD_NM") not in LH_EXCLUDE_TYPES)
            if len(rows) < 100:
                break
    if not items:
        raise ValueError("최근 {}일 공고가 0건입니다. 응답 형식을 확인해 주세요.".format(LH_DAYS))
    return items


def parse_sh_board(page, board, label):
    """SH 공고 게시판 HTML에서 입주자 모집 공고만 골라냅니다. 당첨자·결과 게시 글은 제외합니다.

    게시글 행을 하나도 찾지 못하면 페이지 구조가 바뀐 것으로 보고 예외를 던집니다.
    """
    body = page[page.find("<tbody"):page.find("</tbody>")]
    matches = [m for m in (SH_ROW_RE.search(tr)
                           for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)) if m]
    if not matches:
        raise ValueError("{} 게시판에서 글을 찾지 못했습니다. 페이지 구조를 확인해 주세요.".format(label))
    rows = []
    for match in matches:
        seq, raw_title, posted = match.groups()
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", raw_title)).split())
        if not ("입주" in title and "모집" in title) or any(w in title for w in SH_EXCLUDE):
            continue
        rows.append({
            "_type": "SH",
            "_id": "SH:{}:{}".format(board, seq),
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


def load_seen():
    """이미 리포트한 공고 ID → 처음 본 날짜를 읽습니다. 기록이 없거나 깨졌으면 None을 돌려줍니다."""
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_seen(seen, items, today):
    """이번에 조회한 공고를 기록에 더하고, SEEN_KEEP_DAYS보다 오래된 기록은 지웁니다."""
    merged = dict(seen or {})
    for row in items:
        merged.setdefault(row["_id"], today.isoformat())
    cutoff = (today - timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    merged = {key: day for key, day in merged.items() if day >= cutoff}
    SEEN_PATH.parent.mkdir(exist_ok=True)
    SEEN_PATH.write_text(json.dumps(merged, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def is_new(row, today, seen):
    """기록이 있으면 처음 보는 공고를, 없으면(첫 실행) 공고일이 어제·오늘인 공고를 새 공고로 봅니다."""
    posted = field(row, "RCRIT_PBLANC_DE")
    if seen is None:
        return posted >= (today - timedelta(days=1)).isoformat()
    return (row["_id"] not in seen
            and posted >= (today - timedelta(days=NEW_LOOKBACK_DAYS)).isoformat())


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
    """세대수가 None이면 물량은 모르지만 해당 특공이 있다는 뜻입니다(LH)."""
    return any(count is None or count > 0 for count in row.get("_special", {}).values())


def format_family(label, count):
    return "{} 특공".format(label) if count is None else "{} {:,}세대".format(label, count)


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
    households = to_int(row.get("TOT_SUPLY_HSHLDCO"))
    hh = " {:,}세대".format(households) if households else ""
    details = [format_phase(*phase) for phase in phases(row)]
    url = field(row, "PBLANC_URL")
    if url:
        details.append('<a href="{}">공고</a>'.format(html.escape(url, quote=True)))
    line = "• [{}] {} ({}{})".format(area, name, house_type(row), hh)
    if details:
        line += "\n   " + " · ".join(details)
    if has_family_quota(row):
        line += "\n   👶 " + " · ".join(format_family(label, count)
                                       for label, count in row["_special"].items()
                                       if count is None or count > 0)
    return line


def build_report(items, today, warnings=(), seen=None):
    tomorrow = (today + timedelta(days=1)).isoformat()
    today_s = today.isoformat()
    upcoming_until = (today + timedelta(days=UPCOMING_DAYS)).isoformat()

    new_notices = [r for r in items if is_new(r, today, seen)]
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

    add_section("🆕 새로 올라온 공고 ({})".format(
        "어제~오늘" if seen is None else "지난 리포트 이후"), new_notices)
    add_section("👶 신생아·신혼 특공 접수 예정 ({}일 내)".format(UPCOMING_DAYS), family)
    add_section("📬 오늘 접수 시작", opening)
    add_section("⏰ 마감 임박 (오늘·내일)", closing)

    footer = "".join("\n⚠️ " + html.escape(w) for w in warnings)
    footer = "\n" + footer if footer else ""
    if not sections:
        return header + "\n\n오늘은 새로운 공고·접수 소식이 없습니다." + footer, False
    return header + "\n\n" + "\n\n".join(sections) + footer, True


def split_message(text, limit=3800):
    """텔레그램 한도(4096자) 안으로 줄 단위로 나눕니다. limit보다 긴 줄은 잘라서 나눕니다."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if current and len(current) + len(line) + 1 > limit:
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
            raise RuntimeError("텔레그램 전송 실패: {}".format(result.get("description") or result))


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


def parse_args(argv):
    """명령줄 옵션을 읽습니다. 모르는 옵션은 리포트를 보내지 않고 사용법과 함께 끝냅니다."""
    parser = argparse.ArgumentParser(
        description="청약홈·LH·SH 공고를 모아 텔레그램으로 데일리 리포트를 보냅니다.",
        allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="전송하지 않고 터미널에 출력합니다")
    mode.add_argument("--get-chat-id", action="store_true", help="봇에게 말 건 사람의 chat_id를 조회합니다")
    mode.add_argument("--test", action="store_true", help="텔레그램으로 테스트 메시지를 보냅니다")
    return parser.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])
    cfg = load_config()

    if args.get_chat_id:
        cmd_get_chat_id(cfg)
        return

    token = cfg.get("TELEGRAM_BOT_TOKEN")
    chat_id = cfg.get("TELEGRAM_CHAT_ID")

    if args.test:
        if not (token and chat_id):
            sys.exit(".env에 TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 먼저 넣어주세요.")
        send_telegram(token, chat_id, "✅ 청약 리포트 봇 연결 테스트 성공!")
        print("테스트 메시지를 보냈습니다.")
        return

    service_key = cfg.get("CHEONGYAK_SERVICE_KEY")
    missing = [k for k, v in (("CHEONGYAK_SERVICE_KEY", service_key),
                              ("TELEGRAM_BOT_TOKEN", token),
                              ("TELEGRAM_CHAT_ID", chat_id)) if not v]
    if missing and not (args.dry_run and service_key):
        sys.exit("[설정 필요] .env에 다음 값이 비어 있습니다: " + ", ".join(missing))

    today = today_kst()
    since = today - timedelta(days=45)
    area_filter = parse_area_filter(cfg.get("AREA_FILTER", ""))
    warnings = []
    unknown = unknown_areas(area_filter)
    if unknown:
        warnings.append("AREA_FILTER에서 알 수 없는 지역: {} (예: 서울,경기,인천)".format(", ".join(unknown)))

    items = fetch_notices(service_key, since)
    if not any(r["_type"] == "APT" for r in items):
        warnings.append("청약홈 APT 공고가 0건입니다. API 응답을 확인해 주세요.")
    items += collect_optional("LH", lambda: fetch_lh(service_key, today), warnings)
    if not area_filter or any("서울" in a for a in area_filter):
        items += collect_optional("SH", fetch_sh, warnings)

    if area_filter:
        items = [r for r in items if in_area(r, area_filter)]

    targets = [r for r in items
               if r["_type"] in MODEL_ENDPOINTS and last_date(r) >= today.isoformat()]
    failed = attach_special_counts(service_key, targets)
    if failed:
        warnings.append("특공 세대수 조회 실패 {}건".format(failed))
    lh_targets = [r for r in items if r["_type"] == "LH" and last_date(r) >= today.isoformat()]
    failed = attach_lh_schedules(service_key, lh_targets)
    if failed:
        warnings.append("LH 접수 일정 조회 실패 {}건 (마감일만 표시)".format(failed))
    items = merge_lh_into_applyhome(items)

    seen = load_seen()
    report, has_news = build_report(items, today, warnings, seen)

    if args.dry_run:
        print(report)
        return

    if not has_news and cfg.get("SEND_WHEN_EMPTY", "true").lower() == "false":
        print("새 소식 없음, 전송 생략 (SEND_WHEN_EMPTY=false)")
    else:
        send_telegram(token, chat_id, report)
        print("{} 리포트 전송 완료 (공고 {}건 조회)".format(today.isoformat(), len(items)))
    save_seen(seen, items, today)


def notify_failure(err):
    """리포트 생성이 중간에 실패하면 원인과 실행 로그 링크를 텔레그램으로 알립니다."""
    cfg = load_config()
    token, chat_id = cfg.get("TELEGRAM_BOT_TOKEN"), cfg.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id) or "--dry-run" in sys.argv:
        return
    text = "❗ <b>청약 리포트 생성 실패</b>\n{}: {}".format(
        type(err).__name__, html.escape(str(err)))
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        text += '\n<a href="{}/{}/actions/runs/{}">실행 로그</a>'.format(
            os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
            os.environ.get("GITHUB_REPOSITORY", ""), run_id)
    try:
        send_telegram(token, chat_id, text)
    except Exception:  # noqa: BLE001 - 텔레그램 자체가 원인이면 알릴 방법이 없습니다
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        notify_failure(error)
        raise
