from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from scripts.file_audit import (
    audit_files,
    clean_source_url,
    extract_original_url,
    extract_saved_date,
    extract_title,
    legal_diagnostics,
    legal_capture_coverage,
    preferred_file_id,
    title_filename_mismatch,
)


SINGLEFILE_FIXTURE = """<!doctype html>
<!-- saved from url=(0048)https://www.hdb.gov.sg/page?utm_source=test&id=12 -->
<html><head>
  <meta name="savepage-date" content="2026-10-10T11:12:13Z">
  <title>Buying an HDB flat</title>
</head><body><main><h1>Eligibility</h1><p>Official policy text.</p></main></body></html>
"""


class FileAuditTests(unittest.TestCase):
    def test_singlefile_metadata_and_title_extraction(self) -> None:
        soup = BeautifulSoup(SINGLEFILE_FIXTURE, "lxml")
        self.assertEqual(extract_title(soup), "Buying an HDB flat")
        self.assertEqual(
            extract_original_url(soup, SINGLEFILE_FIXTURE),
            "https://www.hdb.gov.sg/page?id=12",
        )
        self.assertEqual(extract_saved_date(soup, SINGLEFILE_FIXTURE), "2026-10-10T11:12:13Z")

    def test_tracking_cleanup_preserves_identifying_query(self) -> None:
        self.assertEqual(
            clean_source_url("https://example.gov.sg/a?utm_medium=x&doc=4#section"),
            "https://example.gov.sg/a?doc=4",
        )

    def test_file_id_only_uses_standalone_letter_suffix(self) -> None:
        self.assertEqual(preferred_file_id("H04_A_Grant.html"), "H04_A")
        self.assertEqual(preferred_file_id("H06_Minimum Occupation Period.html"), "H06")
        self.assertEqual(preferred_file_id("IR01_Buyer's Stamp Duty.html"), "IR01")

    def test_meaningful_filename_title_mismatch(self) -> None:
        self.assertTrue(
            title_filename_mismatch(
                "H03_Resale Flat Eligibility.html",
                "Application for an HDB Flat Eligibility Letter",
            )
        )
        self.assertFalse(
            title_filename_mismatch(
                "C09_Home Protection Scheme.html",
                "Protecting against losing your home",
            )
        )

    def test_legal_structure_detection(self) -> None:
        text = (
            "Housing and Development Act 1959 Section 1 Short title. "
            "Section 2 Interpretation. " + "legal provision " * 150
        )
        result = legal_diagnostics(
            "Housing and Development Act 1959",
            text,
            "S01_Housing and Development Act 1959",
        )
        self.assertEqual(result["legal_title_present"], "true")
        self.assertEqual(result["section_numbers_detectable"], "true")
        self.assertEqual(result["substantive_legal_provisions_present"], "true")
        self.assertEqual(result["empty_viewer_shell"], "false")

    def test_incomplete_sso_capture_is_detected(self) -> None:
        soup = BeautifulSoup(
            """
            <nav id="toc">
              <a href="#pr1-">1 Citation</a>
              <a href="#pr2-">2 Definitions</a>
              <a href="#Sc-">THE SCHEDULE</a>
            </nav>
            <div id="legisContent"><div id="pr1-" class="prov1">1. Citation</div></div>
            """,
            "lxml",
        )
        result = legal_capture_coverage(soup)
        self.assertEqual(result["sso_toc_provision_count"], "2")
        self.assertEqual(result["sso_captured_provision_count"], "1")
        self.assertEqual(result["legal_content_coverage_status"], "incomplete_provisions")

    def test_exact_duplicate_detection(self) -> None:
        html = "<html><head><title>Policy</title></head><body>" + ("policy text " * 100) + "</body></html>"
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "H01_A.html"
            second = Path(temp_dir) / "H01_B.html"
            first.write_text(html, encoding="utf-8")
            second.write_text(html, encoding="utf-8")
            records = audit_files([(first, "HDB"), (second, "HDB")])
        self.assertTrue(
            all(record.suspected_duplicate_status == "exact_raw_file" for record in records)
        )
        self.assertEqual(len({record.file_id for record in records}), 2)
        self.assertEqual(
            sorted(record.downstream_action for record in records),
            ["exclude_exact_duplicate", "keep"],
        )
        excluded = next(
            record for record in records if record.downstream_action == "exclude_exact_duplicate"
        )
        self.assertTrue(excluded.duplicate_of)


if __name__ == "__main__":
    unittest.main()
