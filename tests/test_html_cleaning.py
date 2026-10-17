from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from scripts.html_cleaning import (
    clone_and_remove_noise,
    extract_legal_blocks,
    extract_legal_metadata,
    extract_policy_blocks,
    table_structure,
)


class HtmlCleaningTests(unittest.TestCase):
    def test_navigation_removed_but_article_header_preserved(self) -> None:
        soup = BeautifulSoup(
            """
            <main>
              <header class="article-header"><h1>Policy title</h1></header>
              <nav>Site menu</nav>
              <p>Eligibility condition</p>
              <footer>Site footer</footer>
            </main>
            """,
            "lxml",
        )
        cleaned = clone_and_remove_noise(soup.main, "CPF")
        text = cleaned.get_text(" ", strip=True)
        self.assertIn("Policy title", text)
        self.assertIn("Eligibility condition", text)
        self.assertNotIn("Site menu", text)

    def test_hdb_site_header_and_footer_removed(self) -> None:
        soup = BeautifulSoup(
            "<main><header>Advisory</header><h1>Eligibility</h1><p>Policy</p><footer>Contact</footer></main>",
            "lxml",
        )
        cleaned = clone_and_remove_noise(soup.main, "HDB")
        self.assertEqual(cleaned.get_text(" ", strip=True), "Eligibility Policy")

    def test_accordion_heading_and_description_are_preserved(self) -> None:
        soup = BeautifulSoup(
            """
            <main><button class="accordion-button"><div role="heading" aria-level="3">MOP</div>
            <div><p>Five years for Standard flats.</p></div></button></main>
            """,
            "lxml",
        )
        cleaned = clone_and_remove_noise(soup.main, "HDB")
        blocks = extract_policy_blocks(cleaned, "")
        self.assertEqual([block["text"] for block in blocks], ["MOP", "Five years for Standard flats."])

    def test_table_preserves_headers_and_merged_cells(self) -> None:
        soup = BeautifulSoup(
            """
            <table>
              <tr><th rowspan="2">Buyer</th><th colspan="2">Limit</th></tr>
              <tr><th>CPF</th><th>Cash</th></tr>
              <tr><td>Family</td><td><ul><li>$X</li><li>$Z</li></ul></td><td>$Y</td></tr>
            </table>
            """,
            "lxml",
        )
        result = table_structure(soup.table, "")
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["column_count"], 3)
        self.assertEqual(result["cells"][0]["rowspan"], 2)
        self.assertEqual(result["cells"][1]["colspan"], 2)
        self.assertIn("$X", result["markdown"])
        self.assertIn("$Z", result["markdown"])

    def test_links_are_preserved_in_policy_blocks(self) -> None:
        soup = BeautifulSoup(
            '<main><h1>Grant</h1><p>Read <a href="/rules">the rules</a>.</p></main>',
            "lxml",
        )
        blocks = extract_policy_blocks(soup.main, "https://example.gov.sg/page")
        self.assertEqual(blocks[1]["text"], "Read [the rules](https://example.gov.sg/rules).")

    def test_nested_list_items_are_preserved_without_duplication(self) -> None:
        soup = BeautifulSoup(
            "<main><h1>Conditions</h1><ul><li>Citizen<ul><li>At least 21</li></ul></li></ul></main>",
            "lxml",
        )
        blocks = extract_policy_blocks(soup.main, "")
        items = [block["text"] for block in blocks if block["type"] == "list_item"]
        self.assertEqual(items, ["Citizen", "At least 21"])

    def test_table_nested_in_list_item_is_preserved_as_structured_block(self) -> None:
        soup = BeautifulSoup(
            """
            <main><ul><li>Loan limits<div><table><tr>
              <th>Remaining lease</th><td>At least 20 years</td>
            </tr></table></div></li></ul></main>
            """,
            "lxml",
        )
        blocks = extract_policy_blocks(soup.main, "")
        self.assertEqual(
            [block["text"] for block in blocks if block["type"] == "list_item"],
            ["Loan limits"],
        )
        tables = [block for block in blocks if block["type"] == "table"]
        self.assertEqual(len(tables), 1)
        self.assertIn("20 years", tables[0]["text"])
        self.assertEqual(tables[0]["table"]["cells"][1]["text"], "At least 20 years")

    def test_legal_number_and_hierarchy_preserved(self) -> None:
        soup = BeautifulSoup(
            """
            <div id="legisContent">
              <div class="body">
                <div class="partNo">PART 1</div><div class="partHdr">PRELIMINARY</div>
                <div class="prov1"><span id="pr2-"></span><div class="prov1Hdr">Interpretation</div><div>2.—(1) Defined terms.</div></div>
              </div>
            </div>
            """,
            "lxml",
        )
        blocks = extract_legal_blocks(soup.find(id="legisContent"))
        provision = next(block for block in blocks if block["type"] == "legal_provision")
        self.assertEqual(provision["section_number"], "2")
        self.assertEqual(provision["section_path"], ["PART 1 PRELIMINARY", "Section 2 Interpretation"])
        self.assertIn("2.—(1)", provision["text"])

    def test_deleted_legal_provision_is_preserved(self) -> None:
        soup = BeautifulSoup(
            """
            <div id="legisContent"><div class="body">
              <div class="prov1Rep" id="pr12-"><strong>12.</strong> [Deleted by S 367/2006]</div>
            </div></div>
            """,
            "lxml",
        )
        blocks = extract_legal_blocks(soup.find(id="legisContent"))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["section_number"], "12")
        self.assertEqual(blocks[0]["section_status"], "repealed_or_deleted")
        self.assertIn("Deleted by S 367/2006", blocks[0]["text"])

    def test_legal_version_metadata_preserved(self) -> None:
        soup = BeautifulSoup(
            """
            <div class="status-row">Status: Current version as at 17 Oct 2026</div>
            <div class="revdHdr">2025 REVISED EDITION</div>
            <div class="revdTxt">Includes amendments to 1 Jan 2026</div>
            <div class="cDate">[1 February 1960]</div>
            <div class="longTitle">An Act relating to housing.</div>
            """,
            "lxml",
        )
        metadata = extract_legal_metadata(soup)
        self.assertEqual(metadata["revised_edition"], "2025 REVISED EDITION")
        self.assertEqual(metadata["commencement_text"], "[1 February 1960]")


if __name__ == "__main__":
    unittest.main()
