"""Unit test suite for review queue parsing, metadata extraction, and manifest updates."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from approve_from_issue import extract_payload, update_manifest_asset


class TestReviewQueue(unittest.TestCase):
    """Tests for review queue event processing and payload extraction."""

    def setUp(self) -> None:
        """Set up issue body representative of issue #15."""
        self.issue_15_body = (
            "## Paid asset awaiting approval — `data-storyteller-s-toolkit`\n\n"
            "| | |\n"
            "|---|---|\n"
            "| **Title** | Data Storyteller's Toolkit |\n"
            "| **Price** | $11 |\n"
            "| **Category** | prompt-pack |\n"
            "| **Prompts** | 8 |\n"
            "| **Skills** | 3 |\n\n"
            "**Description:** This pack equips you with AI prompts to streamline your data analysis and visualization workflows. Move from messy datasets to structured insights and compelling visual communication faster. Generate analysis plans, uncover hidden trends, and craft persuasive data narratives.\n\n"
            "**Images:**\n"
            "- https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/data-storyteller-s-toolkit-img-1-v2.jpg\n"
            "- https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/data-storyteller-s-toolkit-img-2-v2.jpg\n\n"
            "**Deliverables:** 4 file(s)\n"
            "- data-storyteller-s-toolkit.pdf\n"
            "- data-storyteller-s-toolkit.docx\n"
            "- data-storyteller-s-toolkit.zip\n"
            "- pack.html\n\n"
            "*(Download links are deliberately omitted — this repo is public. Verified\n"
            "2026-09-05 that published links let anyone download paid products for free.)*\n\n"
            "**Whop page:** https://whop.com/the-algorithmic-daemon-concern/data-storyteller-s-toolkit\n\n"
            "---\n"
            "Comment **`/approve`** to publish to Whop, or **`/reject <reason>`** to archive.\n\n"
            "```json\n"
            "{\n"
            "  \"slug\": \"data-storyteller-s-toolkit\",\n"
            "  \"price\": 11,\n"
            "  \"product_id\": \"prod_Cw3vVbUJLp3Ip\",\n"
            "  \"page_url\": \"https://whop.com/the-algorithmic-daemon-concern/data-storyteller-s-toolkit\",\n"
            "  \"images\": [\n"
            "    \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/data-storyteller-s-toolkit-img-1-v2.jpg\",\n"
            "    \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/data-storyteller-s-toolkit-img-2-v2.jpg\"\n"
            "  ],\n"
            "  \"files\": [\n"
            "    {\"name\": \"data-storyteller-s-toolkit.pdf\"},\n"
            "    {\"name\": \"data-storyteller-s-toolkit.docx\"},\n"
            "    {\"name\": \"data-storyteller-s-toolkit.zip\"},\n"
            "    {\"name\": \"pack.html\"}\n"
            "  ],\n"
            "  \"pack\": {\n"
            "    \"title\": \"Data Storyteller's Toolkit\",\n"
            "    \"subtitle\": \"Turn raw data into clear, actionable insights and compelling visuals.\",\n"
            "    \"description\": \"This pack equips you with AI prompts to streamline your data analysis and visualization workflows. Move from messy datasets to structured insights and compelling visual communication faster. Generate analysis plans, uncover hidden trends, and craft persuasive data narratives.\"\n"
            "  }\n"
            "}\n"
            "```\n"
        )

    def test_extract_payload_issue_15(self) -> None:
        """Extract and validate payload from issue #15 format."""
        payload = extract_payload(self.issue_15_body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "data-storyteller-s-toolkit")
        self.assertEqual(payload["price"], 11)
        self.assertEqual(payload["product_id"], "prod_Cw3vVbUJLp3Ip")
        self.assertEqual(len(payload["images"]), 2)
        self.assertEqual(len(payload["files"]), 4)
        self.assertEqual(payload["pack"]["title"], "Data Storyteller's Toolkit")

    def test_extract_payload_whitespace_resilience(self) -> None:
        """Verify extraction handles whitespace surrounding code fences."""
        body = "   ```json   \n{\"slug\": \"test\", \"price\": 5}   \n```   "
        payload = extract_payload(body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "test")
        self.assertEqual(payload["price"], 5)

    def test_extract_payload_invalid_json(self) -> None:
        """Verify invalid JSON returns None instead of raising exceptions."""
        body = "```json\n{unquoted_key: invalid}\n```"
        payload = extract_payload(body)
        self.assertIsNone(payload)

    def test_extract_payload_no_block(self) -> None:
        """Verify missing json code block returns None."""
        body = "No code block here"
        payload = extract_payload(body)
        self.assertIsNone(payload)

    def test_metadata_construction(self) -> None:
        """Verify metadata mapping conforms to publish.approve requirements."""
        payload = extract_payload(self.issue_15_body)
        metadata = {
            "slug": payload.get("slug"),
            "pack": payload.get("pack"),
            "page_url": payload.get("page_url"),
            "file_urls": payload.get("files") or payload.get("file_urls"),
            "image_urls": payload.get("images") or payload.get("image_urls"),
            "description": (payload.get("pack") or {}).get("description", ""),
        }
        self.assertEqual(metadata["slug"], "data-storyteller-s-toolkit")
        self.assertEqual(len(metadata["file_urls"]), 4)
        self.assertEqual(len(metadata["image_urls"]), 2)
        self.assertEqual(metadata["page_url"], "https://whop.com/the-algorithmic-daemon-concern/data-storyteller-s-toolkit")
        self.assertEqual(
            metadata["description"],
            "This pack equips you with AI prompts to streamline your data analysis and visualization workflows. "
            "Move from messy datasets to structured insights and compelling visual communication faster. "
            "Generate analysis plans, uncover hidden trends, and craft persuasive data narratives."
        )

    def test_update_manifest_asset(self) -> None:
        """Verify update_manifest_asset function correctly updates asset fields."""
        manifest_path = Path(__file__).resolve().parent.parent / "state" / "manifest.json"
        initial_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        update_manifest_asset("data-storyteller-s-toolkit", {"price": 11.0, "status": "live"})
        updated_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        matching = [a for a in updated_data["assets"] if a.get("slug") == "data-storyteller-s-toolkit"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["price"], 11.0)
        self.assertEqual(matching[0]["status"], "live")


if __name__ == "__main__":
    unittest.main()
