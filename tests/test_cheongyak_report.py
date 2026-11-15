# -*- coding: utf-8 -*-
"""cheongyak_report 테스트입니다. 네트워크·텔레그램은 실제로 호출하지 않습니다.

대부분 순수 함수 테스트이고, MainTest만 네트워크를 가짜로 바꿔 main()을 처음부터 끝까지 돌립니다.

실행(레포 루트에서): python3 -W error -m unittest discover tests
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import cheongyak_report as cr

TODAY = date(2026, 11, 13)  # 금요일


class TodayKstTest(unittest.TestCase):
    def test_date_rolls_over_at_korean_midnight_whatever_the_machine_timezone(self):
        utc = timezone.utc
        self.assertEqual(cr.today_kst(datetime(2026, 11, 14, 14, 59, tzinfo=utc)), date(2026, 11, 14))
        self.assertEqual(cr.today_kst(datetime(2026, 11, 14, 15, 0, tzinfo=utc)), date(2026, 11, 15))
        # 예약 실행 시각(18:17 UTC)은 한국에서는 이미 다음 날 새벽입니다.
        self.assertEqual(cr.today_kst(datetime(2026, 11, 14, 18, 17, tzinfo=utc)), date(2026, 11, 15))
        pacific = timezone(timedelta(hours=-8))
        self.assertEqual(cr.today_kst(datetime(2026, 11, 14, 14, 17, tzinfo=pacific)), date(2026, 11, 15))

    def test_defaults_to_now(self):
        before = datetime.now(cr.KST).date()
        self.assertIn(cr.today_kst(), (before, datetime.now(cr.KST).date()))


class NormDateTest(unittest.TestCase):
    def test_compact_and_dotted_dates_become_iso(self):
        self.assertEqual(cr.norm_date("20261105"), "2026-11-05")
        self.assertEqual(cr.norm_date("2026.11.05"), "2026-11-05")
        self.assertEqual(cr.norm_date("2026-11-05"), "2026-11-05")

    def test_non_dates_are_kept(self):
        self.assertEqual(cr.norm_date(None), "")
        self.assertEqual(cr.norm_date(""), "")
        self.assertEqual(cr.norm_date("미정"), "미정")
        self.assertEqual(cr.norm_date("2026-11-05 10:00"), "2026-11-05 10:00")


class ToIntTest(unittest.TestCase):
    def test_digits_are_extracted(self):
        self.assertEqual(cr.to_int("1,024"), 1024)
        self.assertEqual(cr.to_int(52), 52)
        self.assertEqual(cr.to_int("약 30세대"), 30)

    def test_empty_is_zero(self):
        self.assertEqual(cr.to_int(None), 0)
        self.assertEqual(cr.to_int(""), 0)


class FieldTest(unittest.TestCase):
    def test_first_truthy_value_as_string(self):
        row = {"a": "", "b": 0, "c": 15, "d": "x"}
        self.assertEqual(cr.field(row, "a", "b", "c", "d"), "15")
        self.assertEqual(cr.field(row, "missing"), "")


class RegionTest(unittest.TestCase):
    def test_short_region_drops_admin_suffix(self):
        self.assertEqual(cr.short_region("서울특별시"), "서울")
        self.assertEqual(cr.short_region("부산광역시"), "부산")
        self.assertEqual(cr.short_region("세종특별자치시"), "세종")
        self.assertEqual(cr.short_region("강원특별자치도"), "강원")
        self.assertEqual(cr.short_region("제주특별자치도"), "제주")
        self.assertEqual(cr.short_region("경기도"), "경기")
        self.assertEqual(cr.short_region("서울"), "서울")

    def test_short_region_shortens_four_letter_provinces(self):
        self.assertEqual(cr.short_region("충청북도"), "충북")
        self.assertEqual(cr.short_region("충청남도"), "충남")
        self.assertEqual(cr.short_region("전라남도"), "전남")
        self.assertEqual(cr.short_region("경상북도"), "경북")
        self.assertEqual(cr.short_region("경상남도"), "경남")
        self.assertEqual(cr.short_region("전북특별자치도"), "전북")

    def test_regions_in_title(self):
        self.assertEqual(cr.regions_in("경남 김해 행복주택"), {"경남"})
        self.assertEqual(cr.regions_in("경상남도 창원 국민임대"), {"경남"})
        self.assertEqual(cr.regions_in("서울·인천 통합공고"), {"서울", "인천"})
        self.assertEqual(cr.regions_in("전세임대 입주자 모집"), set())


class ParseAreaFilterTest(unittest.TestCase):
    def test_comma_separated_regions(self):
        self.assertEqual(cr.parse_area_filter("서울, 경기,,인천 "), ["서울", "경기", "인천"])

    def test_empty_or_nationwide_means_no_filter(self):
        self.assertEqual(cr.parse_area_filter(""), [])
        self.assertEqual(cr.parse_area_filter("전국"), [])
        self.assertEqual(cr.parse_area_filter("서울,전국"), [])

    def test_full_names_become_short_names(self):
        self.assertEqual(cr.parse_area_filter("서울특별시, 경기도,충청북도,강원특별자치도,서울시"),
                         ["서울", "경기", "충북", "강원", "서울"])
        self.assertTrue(cr.in_area({"SUBSCRPT_AREA_CODE_NM": "경기"}, cr.parse_area_filter("경기도")))

    def test_unknown_names_are_kept_and_reported(self):
        areas = cr.parse_area_filter("서울,서을,성남")
        self.assertEqual(areas, ["서울", "서을", "성남"])
        self.assertEqual(cr.unknown_areas(areas), ["서을", "성남"])
        self.assertEqual(cr.unknown_areas(cr.parse_area_filter("부산광역시,제주도")), [])


class InAreaTest(unittest.TestCase):
    def test_regular_region(self):
        self.assertTrue(cr.in_area({"SUBSCRPT_AREA_CODE_NM": "서울"}, ["서울", "경기"]))
        self.assertFalse(cr.in_area({"SUBSCRPT_AREA_CODE_NM": "부산"}, ["서울", "경기"]))
        self.assertFalse(cr.in_area({}, ["서울"]))

    def test_lh_province_matches_short_filter(self):
        row = cr.lh_to_row({"PAN_ID": "1", "CNP_CD_NM": "충청북도", "PAN_NM": "청주 행복주택"})
        self.assertTrue(cr.in_area(row, ["충북"]))

    def test_nationwide_notice_is_judged_by_title(self):
        def nationwide(title):
            return {"SUBSCRPT_AREA_CODE_NM": "전국", "HOUSE_NM": title}

        self.assertFalse(cr.in_area(nationwide("경남 김해 행복주택"), ["서울"]))
        self.assertTrue(cr.in_area(nationwide("경기 화성 행복주택"), ["서울", "경기"]))
        self.assertTrue(cr.in_area(nationwide("전세임대 입주자 모집"), ["서울"]))


class LhResponseTest(unittest.TestCase):
    def test_lh_rows_finds_ds_list(self):
        self.assertEqual(cr.lh_rows([{"dsSch": [{}]}, {"dsList": [1, 2]}]), [1, 2])
        self.assertEqual(cr.lh_rows({"dsList": [3]}), [3])
        self.assertEqual(cr.lh_rows([{"dsSch": [{}]}]), [])
        self.assertEqual(cr.lh_rows([{"dsList": []}]), [])

    def test_lh_dataset_by_name(self):
        body = [{"dsEtcInfo": [{"PAN_DTL_CTS": "x"}]}, {"dsSplScdl": [1]}]
        self.assertEqual(cr.lh_dataset(body, "dsSplScdl"), [1])
        self.assertEqual(cr.lh_dataset(body, "dsMissing"), [])


class LhToRowTest(unittest.TestCase):
    RAW = {
        "PAN_ID": "2015122300012345",
        "CNP_CD_NM": "경기도",
        "PAN_NM": "화성동탄 행복주택",
        "AIS_TP_CD_NM": "행복주택",
        "PAN_NT_ST_DT": "2026.11.03",
        "CLSG_DT": "2026.11.20",
        "DTL_URL": "https://apply.lh.or.kr/notice",
        "UPP_AIS_TP_CD": "06",
    }

    def test_maps_list_row(self):
        row = cr.lh_to_row(self.RAW)
        self.assertEqual(row["_type"], "LH")
        self.assertEqual(row["_id"], "LH:2015122300012345")
        self.assertEqual(row["SUBSCRPT_AREA_CODE_NM"], "경기")
        self.assertEqual(row["HOUSE_DTL_SECD_NM"], "LH 행복주택")
        self.assertEqual(row["RCRIT_PBLANC_DE"], "2026-11-03")
        self.assertEqual(row["_phases"], [("마감", "", "2026-11-20")])
        self.assertEqual(row["_lh_keys"]["PAN_ID"], "2015122300012345")
        self.assertEqual(row["_lh_keys"]["UPP_AIS_TP_CD"], "06")
        self.assertEqual(row["_lh_keys"]["SPL_INF_TP_CD"], "")

    def test_without_closing_date_or_kind(self):
        raw = {k: v for k, v in self.RAW.items() if k not in ("CLSG_DT", "AIS_TP_CD_NM")}
        row = cr.lh_to_row(raw)
        self.assertEqual(row["_phases"], [])
        self.assertEqual(row["HOUSE_DTL_SECD_NM"], "LH")


class LhScheduleTest(unittest.TestCase):
    def test_phase_label(self):
        self.assertEqual(cr.lh_phase_label("신혼부부 특별공급"), "특공")
        self.assertEqual(cr.lh_phase_label("기관추천"), "특공")
        self.assertEqual(cr.lh_phase_label("일반공급 1순위"), "일반")
        self.assertEqual(cr.lh_phase_label("우선공급"), "일반")
        self.assertEqual(cr.lh_phase_label(""), "접수")
        self.assertEqual(cr.lh_phase_label("청약접수"), "청약접수")

    def test_schedule_groups_targets_and_detects_family_quota(self):
        rows = [
            {"HS_SBSC_ACP_TRG_CD_NM": "신생아 특별공급",
             "ACP_DTTM": "2026.11.10 10:00 ~ 2026.11.11 17:00"},
            {"HS_SBSC_ACP_TRG_CD_NM": " 신혼부부 특별공급 ",
             "ACP_DTTM": "2026.11.10 10:00 ~ 2026.11.12 17:00"},
            {"HS_SBSC_ACP_TRG_CD_NM": "일반공급 1순위",
             "ACP_DTTM": "2026.11.13 10:00 ~ 2026.11.13 17:00"},
            {"HS_SBSC_ACP_TRG_CD_NM": "서류제출", "ACP_DTTM": ""},
        ]
        steps, family = cr.lh_schedule(rows)
        self.assertEqual(steps, [("특공", "2026-11-10", "2026-11-12"),
                                 ("일반", "2026-11-13", "2026-11-13")])
        self.assertEqual(family, {"신생아": None, "신혼": None})


class MergeLhTest(unittest.TestCase):
    def test_lh_duplicate_of_applyhome_is_dropped_and_latest_schedule_used(self):
        apt = {"_type": "APT", "_id": "APT:2026000001:1", "HOUSE_MANAGE_NO": "2026000001"}
        lh_old = {"_type": "LH", "_id": "LH:1", "HOUSE_MANAGE_NO": "2026000001",
                  "RCRIT_PBLANC_DE": "2026-11-01",
                  "_lh_steps": [("특공", "2026-11-10", "2026-11-10")]}
        lh_new = {"_type": "LH", "_id": "LH:2", "HOUSE_MANAGE_NO": "2026000001",
                  "RCRIT_PBLANC_DE": "2026-11-05",
                  "_lh_steps": [("특공", "2026-11-12", "2026-11-12")]}
        lh_only = {"_type": "LH", "_id": "LH:3", "HOUSE_MANAGE_NO": "2026999999",
                   "RCRIT_PBLANC_DE": "2026-11-05",
                   "_lh_steps": [("일반", "2026-11-20", "2026-11-21")]}
        lh_plain = {"_type": "LH", "_id": "LH:4", "RCRIT_PBLANC_DE": "2026-11-05"}

        result = cr.merge_lh_into_applyhome([lh_new, apt, lh_old, lh_only, lh_plain])

        self.assertEqual([r["_id"] for r in result], ["APT:2026000001:1", "LH:3", "LH:4"])
        self.assertEqual(apt["_phases"], [("특공", "2026-11-12", "2026-11-12")])


class ParseShBoardTest(unittest.TestCase):
    @staticmethod
    def tr(seq, title, posted):
        return ('<tr><td>{0}</td><td class="txtL"><a href="#" '
                'onclick="getDetailView(\'{0}\');return false;">{1}</a></td>'
                '<td>{2}</td></tr>').format(seq, title, posted)

    def test_keeps_only_recruitment_notices(self):
        page = "<table><thead><tr><th>번호</th></tr></thead><tbody>{}</tbody></table>".format("".join([
            self.tr("301", "고덕강일 3단지   <b>입주자</b> 모집 공고", "2026-11-03"),
            self.tr("302", "고덕강일 3단지 입주자 모집 당첨자 발표", "2026-11-04"),
            self.tr("303", "임대료 납부 안내", "2026-11-05"),
            self.tr("304", "&lt;재공고&gt; 행복주택 입주자 모집", "2026-11-06"),
        ]))

        rows = cr.parse_sh_board(page, "1", "SH 분양")

        self.assertEqual([r["_id"] for r in rows], ["SH:1:301", "SH:1:304"])
        self.assertEqual(rows[0]["HOUSE_NM"], "고덕강일 3단지 입주자 모집 공고")
        self.assertEqual(rows[1]["HOUSE_NM"], "<재공고> 행복주택 입주자 모집")
        self.assertEqual(rows[0]["RCRIT_PBLANC_DE"], "2026-11-03")
        self.assertEqual(rows[0]["SUBSCRPT_AREA_CODE_NM"], "서울")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(rows[0]["PBLANC_URL"]).query)
        self.assertEqual(query, {"multi_itm_seq": ["1"], "seq": ["301"]})

    def test_changed_page_structure_raises(self):
        with self.assertRaises(ValueError):
            cr.parse_sh_board("<table><tbody></tbody></table>", "1", "SH 분양")


class SeenTest(unittest.TestCase):
    def test_is_new_on_first_run_uses_yesterday_and_today(self):
        self.assertTrue(cr.is_new({"_id": "A", "RCRIT_PBLANC_DE": "2026-11-12"}, TODAY, None))
        self.assertFalse(cr.is_new({"_id": "A", "RCRIT_PBLANC_DE": "2026-11-11"}, TODAY, None))

    def test_is_new_with_history_means_unseen_and_recent(self):
        seen = {"A": "2026-11-01"}
        self.assertFalse(cr.is_new({"_id": "A", "RCRIT_PBLANC_DE": "2026-11-12"}, TODAY, seen))
        self.assertTrue(cr.is_new({"_id": "B", "RCRIT_PBLANC_DE": "2026-11-01"}, TODAY, seen))
        self.assertFalse(cr.is_new({"_id": "C", "RCRIT_PBLANC_DE": "2026-10-20"}, TODAY, seen))

    def test_save_and_load_round_trip_prunes_old_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".state" / "seen.json"
            with mock.patch.object(cr, "SEEN_PATH", path):
                self.assertIsNone(cr.load_seen())
                cr.save_seen({"old": "2026-01-01", "keep": "2026-11-01"},
                             [{"_id": "keep"}, {"_id": "new"}], TODAY)
                self.assertEqual(cr.load_seen(), {"keep": "2026-11-01", "new": "2026-11-13"})
                path.write_text("{broken", encoding="utf-8")
                self.assertIsNone(cr.load_seen())


class PhasesTest(unittest.TestCase):
    def test_explicit_phases_win(self):
        steps = [("마감", "", "2026-11-20")]
        self.assertIs(cr.phases({"_phases": steps}), steps)

    def test_applyhome_fields_grouped_by_phase(self):
        row = {
            "SPSPLY_RCEPT_BGNDE": "2026-11-10", "SPSPLY_RCEPT_ENDDE": "2026-11-10",
            "GNRL_RNK1_CRSPAREA_RCPTDE": "2026-11-11", "GNRL_RNK1_CRSPAREA_ENDDE": "2026-11-11",
            "GNRL_RNK1_ETC_AREA_RCPTDE": "2026-11-12", "GNRL_RNK1_ETC_AREA_ENDDE": "2026-11-12",
            "GNRL_RCEPT_BGNDE": "2026-11-14",
        }
        self.assertEqual(cr.phases(row), [("특공", "2026-11-10", "2026-11-10"),
                                          ("1순위", "2026-11-11", "2026-11-12"),
                                          ("일반", "2026-11-14", "2026-11-14")])

    def test_fallback_and_empty(self):
        self.assertEqual(cr.phases({"RCEPT_BGNDE": "2026-11-14", "RCEPT_ENDDE": "2026-11-16"}),
                         [("접수", "2026-11-14", "2026-11-16")])
        self.assertEqual(cr.phases({"SUBSCRPT_RCEPT_ENDDE": "2026-11-16"}),
                         [("접수", "", "2026-11-16")])
        self.assertEqual(cr.phases({}), [])

    def test_last_date_and_sort_key(self):
        row = {"SUBSCRPT_AREA_CODE_NM": "서울",
               "_phases": [("특공", "2026-11-10", "2026-11-10"), ("마감", "", "2026-11-20")]}
        self.assertEqual(cr.last_date(row), "2026-11-20")
        self.assertEqual(cr.sort_key(row), ("서울", "2026-11-10"))
        self.assertEqual(cr.last_date({"_phases": []}), "")


class FormatTest(unittest.TestCase):
    def test_family_quota(self):
        self.assertFalse(cr.has_family_quota({}))
        self.assertFalse(cr.has_family_quota({"_special": {"신생아": 0, "신혼": 0}}))
        self.assertTrue(cr.has_family_quota({"_special": {"신생아": 0, "신혼": 3}}))
        self.assertTrue(cr.has_family_quota({"_special": {"신생아": None}}))
        self.assertEqual(cr.format_family("신혼", None), "신혼 특공")
        self.assertEqual(cr.format_family("신생아", 52), "신생아 52세대")
        self.assertEqual(cr.format_family("신혼", 1200), "신혼 1,200세대")

    def test_house_type(self):
        self.assertEqual(cr.house_type({"_type": "APT", "HOUSE_SECD_NM": "APT",
                                        "HOUSE_DTL_SECD_NM": "민영"}), "민영")
        self.assertEqual(cr.house_type({"_type": "APT", "HOUSE_SECD_NM": "신혼희망타운",
                                        "HOUSE_DTL_SECD_NM": "국민"}), "신혼희망타운 국민")
        self.assertEqual(cr.house_type({"_type": "APT"}), "APT")
        self.assertEqual(cr.house_type({"_type": "오피스텔 등",
                                        "HOUSE_DETAIL_SECD_NM": "오피스텔"}), "오피스텔")
        self.assertEqual(cr.house_type({"_type": "SH"}), "SH")

    def test_format_phase(self):
        self.assertEqual(cr.format_phase("특공", "2026-11-10", "2026-11-10"), "특공 11-10")
        self.assertEqual(cr.format_phase("1순위", "2026-11-11", "2026-11-12"), "1순위 11-11~11-12")
        self.assertEqual(cr.format_phase("마감", "", "2026-11-20"), "마감 11-20")
        self.assertEqual(cr.format_phase("접수", "2026-11-14", ""), "접수 11-14")

    def test_format_line_escapes_html(self):
        row = {
            "_type": "APT", "SUBSCRPT_AREA_CODE_NM": "서울", "HOUSE_NM": "래미안 <원베일리>",
            "HOUSE_SECD_NM": "APT", "HOUSE_DTL_SECD_NM": "민영", "TOT_SUPLY_HSHLDCO": "1024",
            "_phases": [("특공", "2026-11-10", "2026-11-10"), ("1순위", "2026-11-11", "2026-11-12")],
            "PBLANC_URL": "https://www.applyhome.co.kr/notice?a=1&b=2",
            "_special": {"신생아": 52, "신혼": 0},
        }
        self.assertEqual(cr.format_line(row), (
            "• [서울] 래미안 &lt;원베일리&gt; (민영 1,024세대)\n"
            '   특공 11-10 · 1순위 11-11~11-12 · <a href="https://www.applyhome.co.kr/notice?a=1&amp;b=2">공고</a>\n'
            "   👶 신생아 52세대"))

    def test_format_line_escapes_every_text_from_the_apis(self):
        row = {
            "_type": "LH", "SUBSCRPT_AREA_CODE_NM": "경기<남부>", "HOUSE_NM": "A&B 행복주택",
            "HOUSE_DTL_SECD_NM": "LH 행복주택<청년>",
            "_phases": [("고령자<만65세 이상>", "2026-11-20", "2026-11-21")],
        }
        self.assertEqual(cr.format_line(row), (
            "• [경기&lt;남부&gt;] A&amp;B 행복주택 (LH 행복주택&lt;청년&gt;)\n"
            "   고령자&lt;만65세 이상&gt; 11-20~11-21"))

    def test_format_line_with_missing_fields(self):
        self.assertEqual(cr.format_line({"_type": "SH", "_phases": []}), "• [지역미상] 이름미상 (SH)")

    def test_format_line_household_count(self):
        row = {"_type": "SH", "SUBSCRPT_AREA_CODE_NM": "서울", "HOUSE_NM": "X", "_phases": []}
        self.assertEqual(cr.format_line(dict(row, TOT_SUPLY_HSHLDCO=12032)), "• [서울] X (SH 12,032세대)")
        self.assertEqual(cr.format_line(dict(row, TOT_SUPLY_HSHLDCO=84)), "• [서울] X (SH 84세대)")
        self.assertEqual(cr.format_line(dict(row, TOT_SUPLY_HSHLDCO=0)), "• [서울] X (SH)")


class BuildReportTest(unittest.TestCase):
    @staticmethod
    def row(row_id, area, phases, **extra):
        row = {"_type": "APT", "_id": row_id, "SUBSCRPT_AREA_CODE_NM": area,
               "HOUSE_NM": row_id, "RCRIT_PBLANC_DE": "2026-11-01", "_phases": phases}
        row.update(extra)
        return row

    def test_sections(self):
        new = self.row("new", "서울", [("특공", "2026-11-20", "2026-11-20")],
                       RCRIT_PBLANC_DE="2026-11-13", _special={"신혼": 10})
        opening = self.row("opening", "경기", [("1순위", "2026-11-13", "2026-11-14")])
        closing = self.row("closing", "인천", [("접수", "2026-11-10", "2026-11-14")])
        seen = {"opening": "2026-11-01", "closing": "2026-11-01"}

        report, counts = cr.build_report([new, opening, closing], TODAY, seen=seen)

        self.assertEqual(counts, [("새 공고", 1), ("특공 예정", 1), ("오늘 접수 시작", 1), ("마감 임박", 2)])
        self.assertTrue(report.startswith("🏠 <b>청약 데일리 리포트</b> — 2026-11-13 (금)\n\n"))
        titles = [line for line in report.split("\n") if line.startswith("<b>")]
        self.assertEqual(titles, [
            "<b>🆕 새로 올라온 공고 (지난 리포트 이후)</b>",
            "<b>👶 신생아·신혼 특공 접수 예정 (14일 내)</b>",
            "<b>📬 오늘 접수 시작</b>",
            "<b>⏰ 마감 임박 (오늘·내일)</b>",
        ])
        sections = report.split("\n\n")[1:]
        self.assertIn("[서울] new", sections[0])
        self.assertIn("[서울] new", sections[1])
        self.assertIn("[경기] opening", sections[2])
        self.assertIn("[경기] opening", sections[3])
        self.assertIn("[인천] closing", sections[3])

    def test_first_run_title(self):
        new = self.row("new", "서울", [], RCRIT_PBLANC_DE="2026-11-12")
        report, _ = cr.build_report([new], TODAY)
        self.assertIn("<b>🆕 새로 올라온 공고 (어제~오늘)</b>", report)

    def test_empty_report_with_warning(self):
        report, counts = cr.build_report([], TODAY, ["LH 조회 실패: <timeout>"])
        self.assertEqual(counts, [])
        self.assertEqual(report, "🏠 <b>청약 데일리 리포트</b> — 2026-11-13 (금)\n\n"
                                 "오늘은 새로운 공고·접수 소식이 없습니다.\n\n"
                                 "⚠️ LH 조회 실패: &lt;timeout&gt;")


class LogWarningsTest(unittest.TestCase):
    @staticmethod
    def logged(warnings, env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out):
            cr.log_warnings(warnings)
        return out.getvalue()

    def test_plain_lines_outside_github_actions(self):
        self.assertEqual(self.logged(["LH 조회 실패: timed out", "SH 조회 실패: x"], {}),
                         "⚠️ LH 조회 실패: timed out\n⚠️ SH 조회 실패: x\n")
        self.assertEqual(self.logged([], {}), "")

    def test_annotations_in_github_actions_stay_on_one_line(self):
        self.assertEqual(
            self.logged(["LH 조회 실패: 100% 응답 없음\n::error::가짜 명령"], {"GITHUB_ACTIONS": "true"}),
            "::warning title=청약 리포트::LH 조회 실패: 100%25 응답 없음%0A::error::가짜 명령\n")


class SplitMessageTest(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(cr.split_message("hello", limit=10), ["hello"])

    def test_long_text_splits_on_lines(self):
        text = "\n".join("line-{:04d}".format(i) for i in range(20))
        chunks = cr.split_message(text, limit=40)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 40 for c in chunks))
        self.assertEqual("\n".join(chunks), text)

    def test_line_longer_than_limit_is_cut_without_empty_chunks(self):
        for text in ("x" * 50 + "\nshort", "aaa\n" + "y" * 45 + "\nbbb"):
            chunks = cr.split_message(text, limit=20)
            self.assertTrue(all(chunks), chunks)
            self.assertTrue(all(len(c) <= 20 for c in chunks), chunks)
            self.assertEqual("".join(chunks).replace("\n", ""), text.replace("\n", ""))


class HttpGetRetryTest(unittest.TestCase):
    def test_retries_then_raises_without_sleeping_after_the_last_attempt(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")) as urlopen, \
                mock.patch("time.sleep") as sleep:
            with self.assertRaises(OSError):
                cr.http_get("https://example.invalid")
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])


class LookupEachTest(unittest.TestCase):
    @staticmethod
    def lookup_failing_on(bad, calls):
        def lookup(row):
            calls.append(row)
            if row in bad:
                raise OSError("down")
        return lookup

    def test_scattered_failures_do_not_stop_the_rest(self):
        calls = []
        failed = cr.lookup_each(list(range(8)), self.lookup_failing_on({0, 1, 3, 4, 6}, calls))
        self.assertEqual(failed, 5)
        self.assertEqual(calls, list(range(8)))

    def test_consecutive_failures_skip_the_rest_and_count_them_as_failed(self):
        calls = []
        failed = cr.lookup_each(list(range(10)), self.lookup_failing_on({2, 3, 4}, calls))
        self.assertEqual(calls, [0, 1, 2, 3, 4])
        self.assertEqual(failed, 3 + 5)

    def test_outage_costs_only_a_few_requests(self):
        rows = [{"_type": "APT", "HOUSE_MANAGE_NO": str(n)} for n in range(40)]
        with mock.patch.object(cr, "http_get_json", side_effect=OSError("down")) as get:
            self.assertEqual(cr.attach_special_counts("key", rows), 40)
        self.assertEqual(get.call_count, cr.DETAIL_FAILURE_LIMIT)
        self.assertNotIn("_special", rows[0])

    def test_special_counts_are_attached_when_lookups_succeed(self):
        rows = [{"_type": "APT", "HOUSE_MANAGE_NO": "1"}]
        body = {"data": [{"NWBB_HSHLDCO": 3, "NWWDS_HSHLDCO": 5}, {"NWBB_HSHLDCO": 2, "NWWDS_HSHLDCO": 0}]}
        with mock.patch.object(cr, "http_get_json", return_value=body):
            self.assertEqual(cr.attach_special_counts("key", rows), 0)
        self.assertEqual(rows[0]["_special"], {"신생아": 5, "신혼": 5})


class TelegramErrorTest(unittest.TestCase):
    @staticmethod
    def http_error(code, body):
        return urllib.error.HTTPError("https://api.telegram.org/botTOKEN/sendMessage",
                                      code, "Bad Request", {}, io.BytesIO(body))

    def test_rejection_reason_is_reported_without_the_token(self):
        body = json.dumps({"ok": False, "error_code": 400,
                           "description": "Bad Request: chat not found"}).encode("utf-8")
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(400, body)):
            with self.assertRaises(RuntimeError) as ctx:
                cr.send_telegram("TOKEN", "1", "hi")
        self.assertEqual(str(ctx.exception), "텔레그램 전송 실패: Bad Request: chat not found")

    def test_error_without_json_body_stays_an_http_error(self):
        error = self.http_error(502, b"<html>Bad Gateway</html>")
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                cr.http_post_json("https://example.invalid", {})


class GetChatIdTest(unittest.TestCase):
    @staticmethod
    def http_error(code):
        # 본문 없이(None) 만들면 파이썬 3.9에서는 close()가 KeyError를 냅니다. 실제 응답처럼 본문을 줍니다.
        return urllib.error.HTTPError("https://api.telegram.org/botTOKEN/getUpdates",
                                      code, "error", {}, io.BytesIO(b""))

    def test_rejected_token_exits_with_a_hint_instead_of_a_traceback(self):
        for code in (401, 404):
            with self.subTest(code=code), \
                    mock.patch.object(cr, "http_get_json", side_effect=self.http_error(code)):
                with self.assertRaises(SystemExit) as ctx:
                    cr.cmd_get_chat_id({"TELEGRAM_BOT_TOKEN": "TOKEN"})
                self.assertIn("TELEGRAM_BOT_TOKEN", str(ctx.exception))
                self.assertNotIn("botTOKEN", str(ctx.exception))

    def test_other_http_errors_are_raised(self):
        with mock.patch.object(cr, "http_get_json", side_effect=self.http_error(502)):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                cr.cmd_get_chat_id({"TELEGRAM_BOT_TOKEN": "TOKEN"})
        ctx.exception.close()

    def test_lists_chats_that_messaged_the_bot(self):
        body = {"result": [{"message": {"chat": {"id": 42, "first_name": "Soo", "last_name": "Lee"}}},
                           {"channel_post": {"chat": {"id": -100, "title": "가족방"}}}]}
        out = io.StringIO()
        with mock.patch.object(cr, "http_get_json", return_value=body), contextlib.redirect_stdout(out):
            cr.cmd_get_chat_id({"TELEGRAM_BOT_TOKEN": "TOKEN"})
        self.assertEqual(out.getvalue(), "chat_id: 42  (Soo Lee)\nchat_id: -100  (가족방)\n")


class MissingConfigTest(unittest.TestCase):
    MISSING = ["CHEONGYAK_SERVICE_KEY", "TELEGRAM_CHAT_ID"]

    def test_points_at_the_env_file_locally(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cr.missing_config_message(self.MISSING),
                             "[설정 필요] .env에 다음 값이 비어 있습니다: CHEONGYAK_SERVICE_KEY, TELEGRAM_CHAT_ID")

    def test_points_at_repository_secrets_on_github_actions(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True):
            message = cr.missing_config_message(self.MISSING)
        self.assertTrue(message.startswith("::error title=청약 리포트 설정::"))
        self.assertIn("레포 Secrets에 다음 값이 없습니다: CHEONGYAK_SERVICE_KEY, TELEGRAM_CHAT_ID.", message)
        self.assertNotIn(".env", message)
        self.assertNotIn("\n", message)


class ParseArgsTest(unittest.TestCase):
    def test_no_option_sends_the_report(self):
        args = cr.parse_args([])
        self.assertFalse(args.dry_run or args.get_chat_id or args.test)

    def test_known_options(self):
        self.assertTrue(cr.parse_args(["--dry-run"]).dry_run)
        self.assertTrue(cr.parse_args(["--get-chat-id"]).get_chat_id)
        self.assertTrue(cr.parse_args(["--test"]).test)

    def test_unknown_or_conflicting_options_exit_instead_of_sending(self):
        for argv in (["--dryrun"], ["--dry"], ["extra"], ["--dry-run", "--test"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    cr.parse_args(argv)
                self.assertEqual(ctx.exception.code, 2)


class LoadConfigTest(unittest.TestCase):
    def test_env_file_and_environment_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("# 주석\n"
                           "CHEONGYAK_SERVICE_KEY='abc=='\n"
                           'TELEGRAM_CHAT_ID="123"\n'
                           "AREA_FILTER = 서울,경기\n"
                           "잘못된 줄\n", encoding="utf-8")
            with mock.patch.object(cr, "ENV_PATH", env), \
                    mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "999"}, clear=True):
                cfg = cr.load_config()
        self.assertEqual(cfg, {"CHEONGYAK_SERVICE_KEY": "abc==", "TELEGRAM_CHAT_ID": "999",
                               "AREA_FILTER": "서울,경기"})


LH_LINE = ("• [경기] 화성동탄 행복주택 (LH 행복주택)\n"
           '   일반 11-13~11-14 · <a href="https://apply.lh.or.kr/notice">공고</a>')
SH_LINE = ("• [서울] 고덕강일 입주자 모집 공고 (SH 분양)\n"
           '   <a href="https://www.i-sh.co.kr/app/lay2/program/S1T294C297/www/brd/m_247/view.do'
           '?multi_itm_seq=1&amp;seq=301">공고</a>')
APT_LINE = ("• [서울] 테스트자이 (민영 1,024세대)\n"
            '   특공 11-20 · 1순위 11-23 · <a href="https://www.applyhome.co.kr/x">공고</a>\n'
            "   👶 신생아 3세대 · 신혼 5세대")
FIRST_REPORT = "\n\n".join([
    "🏠 <b>청약 데일리 리포트</b> — 2026-11-13 (금)",
    "<b>🆕 새로 올라온 공고 (어제~오늘)</b>\n" + "\n".join([LH_LINE, SH_LINE, APT_LINE]),
    "<b>👶 신생아·신혼 특공 접수 예정 (14일 내)</b>\n" + APT_LINE,
    "<b>📬 오늘 접수 시작</b>\n" + LH_LINE,
    "<b>⏰ 마감 임박 (오늘·내일)</b>\n" + LH_LINE,
])


class MainTest(unittest.TestCase):
    """main()을 처음부터 끝까지 돌립니다. 네트워크만 가짜이고 조회·필터·리포트·기록은 실제 코드를 탑니다."""

    ENV = {"CHEONGYAK_SERVICE_KEY": "KEY", "TELEGRAM_BOT_TOKEN": "TOKEN", "TELEGRAM_CHAT_ID": "42",
           "AREA_FILTER": "서울,경기,인천"}
    APT = {
        "HOUSE_MANAGE_NO": "2026000101", "PBLANC_NO": "2026000101", "HOUSE_NM": "테스트자이",
        "HOUSE_SECD_NM": "APT", "HOUSE_DTL_SECD_NM": "민영", "SUBSCRPT_AREA_CODE_NM": "서울",
        "RCRIT_PBLANC_DE": "2026-11-12", "TOT_SUPLY_HSHLDCO": 1024,
        "SPSPLY_RCEPT_BGNDE": "2026-11-20", "SPSPLY_RCEPT_ENDDE": "2026-11-20",
        "GNRL_RNK1_CRSPAREA_RCPTDE": "2026-11-23", "GNRL_RNK1_CRSPAREA_ENDDE": "2026-11-23",
        "PBLANC_URL": "https://www.applyhome.co.kr/x",
    }
    LH = {
        "PAN_ID": "2015122300012345", "CNP_CD_NM": "경기도", "PAN_NM": "화성동탄 행복주택",
        "AIS_TP_CD_NM": "행복주택", "PAN_NT_ST_DT": "2026.11.12", "CLSG_DT": "2026.11.14",
        "DTL_URL": "https://apply.lh.or.kr/notice", "UPP_AIS_TP_CD": "06",
    }
    LH_SCHEDULE = [{"HS_SBSC_ACP_TRG_CD_NM": "일반공급", "ACP_DTTM": "2026.11.13 10:00 ~ 2026.11.14 17:00"}]
    SEEN = {"APT:2026000101:2026000101": "2026-11-13", "LH:2015122300012345": "2026-11-13",
            "SH:1:301": "2026-11-13"}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.seen_path = Path(tmp.name) / ".state" / "seen.json"
        self.down = set()  # 응답하지 않는 것으로 칠 출처입니다: "applyhome", "lh"
        self.posts = []
        patchers = [
            mock.patch.object(cr, "ENV_PATH", Path(tmp.name) / ".env"),
            mock.patch.object(cr, "SEEN_PATH", self.seen_path),
            mock.patch.object(cr, "today_kst", return_value=TODAY),
            mock.patch.object(cr, "http_post_json", side_effect=self.fake_post),
            mock.patch("urllib.request.urlopen",
                       side_effect=AssertionError("테스트가 실제 네트워크를 호출했습니다")),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(cr, "http_get", side_effect=self.fake_get)
        self.http_get = patcher.start()
        self.addCleanup(patcher.stop)

    def fake_get(self, url, params=None, retries=3):
        params = params or {}
        if url.startswith(cr.API_BASE):
            if "applyhome" in self.down:
                raise OSError("청약홈 응답 없음")
            endpoint = url.rsplit("/", 1)[1]
            if endpoint == "getAPTLttotPblancDetail":
                return json.dumps({"data": [self.APT]})
            if endpoint == "getAPTLttotPblancMdl":
                return json.dumps({"data": [{"NWBB_HSHLDCO": 3, "NWWDS_HSHLDCO": 5}]})
            return json.dumps({"data": []})
        if url == cr.LH_LIST_URL:
            if "lh" in self.down:
                raise OSError("timed out")
            rows = [self.LH] if params["UPP_AIS_TP_CD"] == "06" else []
            return json.dumps([{"dsSch": [{}]}, {"dsList": rows}])
        if url == cr.LH_DETAIL_URL:
            return json.dumps([{"dsSplScdl": self.LH_SCHEDULE}, {"dsEtcInfo": []}])
        if url == cr.SH_BOARD_URL.format("list"):
            title = "고덕강일 입주자 모집 공고" if params["multi_itm_seq"] == "1" else "임대료 납부 안내"
            return "<table><tbody>{}</tbody></table>".format(ParseShBoardTest.tr("301", title, "2026-11-12"))
        raise AssertionError("예상하지 못한 주소입니다: " + url)

    def fake_post(self, url, payload):
        self.posts.append((url, payload))
        return {"ok": True}

    def run_main(self, *argv, **env):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["cheongyak_report.py"] + list(argv)), \
                mock.patch.dict(os.environ, dict(self.ENV, **env), clear=True), \
                contextlib.redirect_stdout(out):
            cr.main()
        return out.getvalue()

    def saved_seen(self):
        return json.loads(self.seen_path.read_text(encoding="utf-8"))

    def test_sends_the_report_and_records_the_notices(self):
        out = self.run_main()

        self.assertEqual(len(self.posts), 1)
        url, payload = self.posts[0]
        self.assertEqual(url, "https://api.telegram.org/botTOKEN/sendMessage")
        self.assertEqual((payload["chat_id"], payload["parse_mode"]), ("42", "HTML"))
        self.assertEqual(payload["text"], FIRST_REPORT)
        self.assertEqual(self.saved_seen(), self.SEEN)
        self.assertEqual(out, "2026-11-13 리포트 전송 완료 (공고 3건 조회)\n"
                              "리포트 내용: 새 공고 3건 · 특공 예정 1건 · 오늘 접수 시작 1건 · 마감 임박 1건\n")

    def test_dry_run_prints_without_sending_or_recording(self):
        self.assertEqual(self.run_main("--dry-run"), FIRST_REPORT + "\n")
        self.assertEqual(self.posts, [])
        self.assertFalse(self.seen_path.exists())

    def test_next_run_does_not_repeat_notices_already_reported(self):
        self.run_main()
        out = self.run_main()

        text = self.posts[1][1]["text"]
        self.assertNotIn("🆕", text)
        self.assertIn("<b>📬 오늘 접수 시작</b>\n" + LH_LINE, text)
        self.assertIn("리포트 내용: 특공 예정 1건 · 오늘 접수 시작 1건 · 마감 임박 1건\n", out)

    def test_failed_optional_source_becomes_a_warning(self):
        self.down = {"lh"}

        out = self.run_main()

        text = self.posts[0][1]["text"]
        self.assertNotIn("화성동탄", text)
        self.assertIn(APT_LINE, text)
        self.assertTrue(text.endswith("\n\n⚠️ LH 조회 실패: timed out"))
        self.assertTrue(out.endswith("⚠️ LH 조회 실패: timed out\n"))
        self.assertEqual(sorted(self.saved_seen()), ["APT:2026000101:2026000101", "SH:1:301"])

    def test_quiet_day_is_sent_unless_send_when_empty_is_false(self):
        out = self.run_main(AREA_FILTER="부산", SEND_WHEN_EMPTY="false")
        self.assertEqual(self.posts, [])
        self.assertEqual(out, "새 소식 없음, 전송 생략 (SEND_WHEN_EMPTY=false)\n")
        self.assertEqual(self.saved_seen(), {})

        self.run_main(AREA_FILTER="부산")
        self.assertEqual(self.posts[0][1]["text"], "🏠 <b>청약 데일리 리포트</b> — 2026-11-13 (금)\n\n"
                                                   "오늘은 새로운 공고·접수 소식이 없습니다.")

    def test_applyhome_failure_stops_the_run_without_sending_or_recording(self):
        self.down = {"applyhome"}
        with self.assertRaises(OSError):
            self.run_main()
        self.assertEqual(self.posts, [])
        self.assertFalse(self.seen_path.exists())

    def test_missing_setting_exits_before_any_request(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_main(TELEGRAM_CHAT_ID="")
        self.assertEqual(str(ctx.exception), "[설정 필요] .env에 다음 값이 비어 있습니다: TELEGRAM_CHAT_ID")
        self.assertEqual(self.http_get.call_count, 0)
        self.assertEqual(self.posts, [])

    def notify(self, *argv, **env):
        with mock.patch.object(sys, "argv", ["cheongyak_report.py"] + list(argv)), \
                mock.patch.dict(os.environ, dict(self.ENV, **env), clear=True):
            cr.notify_failure(OSError("<청약홈> 응답 없음"))

    def test_failure_notice_names_the_error_and_links_the_run_log(self):
        self.notify(GITHUB_RUN_ID="123", GITHUB_REPOSITORY="me/cheongyak-bot")
        self.assertEqual(self.posts[0][1]["text"],
                         "❗ <b>청약 리포트 생성 실패</b>\nOSError: &lt;청약홈&gt; 응답 없음\n"
                         '<a href="https://github.com/me/cheongyak-bot/actions/runs/123">실행 로그</a>')

    def test_failure_notice_is_skipped_on_dry_run_or_without_a_chat(self):
        self.notify("--dry-run")
        self.notify(TELEGRAM_CHAT_ID="")
        self.assertEqual(self.posts, [])


if __name__ == "__main__":
    unittest.main()
