# -*- coding: utf-8 -*-
"""cheongyak_report 의 순수 함수 테스트입니다. 네트워크·텔레그램은 호출하지 않습니다.

실행(레포 루트에서): python3 -m unittest discover tests
"""

import os
import tempfile
import unittest
import urllib.parse
from datetime import date
from pathlib import Path
from unittest import mock

import cheongyak_report as cr

TODAY = date(2026, 11, 13)  # 금요일


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
            "• [서울] 래미안 &lt;원베일리&gt; (민영 1024세대)\n"
            '   특공 11-10 · 1순위 11-11~11-12 · <a href="https://www.applyhome.co.kr/notice?a=1&amp;b=2">공고</a>\n'
            "   👶 신생아 52세대"))

    def test_format_line_with_missing_fields(self):
        self.assertEqual(cr.format_line({"_type": "SH", "_phases": []}), "• [지역미상] 이름미상 (SH)")


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

        report, has_news = cr.build_report([new, opening, closing], TODAY, seen=seen)

        self.assertTrue(has_news)
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
        report, has_news = cr.build_report([], TODAY, ["LH 조회 실패: <timeout>"])
        self.assertFalse(has_news)
        self.assertEqual(report, "🏠 <b>청약 데일리 리포트</b> — 2026-11-13 (금)\n\n"
                                 "오늘은 새로운 공고·접수 소식이 없습니다.\n\n"
                                 "⚠️ LH 조회 실패: &lt;timeout&gt;")


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


if __name__ == "__main__":
    unittest.main()
