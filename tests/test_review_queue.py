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
        """Set up issue body representative of issue #12."""
        self.issue_12_body = (
            "## E-commerce Copy Catalyst\n"
            "- **Price:** $11\n"
            "- **Category:** prompt-pack\n"
            "- **Prompts:** 9 | **Skills:** 2\n"
            "- **Description:** This pack provides a direct path to compelling e-commerce copy.\n\n"
            "### Images\n"
            "- https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-img-1-v2.jpg\n"
            "- https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-img-2-v2.jpg\n\n"
            "### Deliverables\n"
            "- [e-commerce-copy-catalyst.pdf](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-e-commerce-copy-catalyst.pdf)\n"
            "- [e-commerce-copy-catalyst.docx](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-e-commerce-copy-catalyst.docx)\n"
            "- [e-commerce-copy-catalyst.zip](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-e-commerce-copy-catalyst.zip)\n"
            "- [pack.html](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-pack.html)\n\n"
            "**Whop page:** https://whop.com/the-algorithmic-daemon-concern/e-commerce-copy-catalyst\n"
            "**Product ID:** `prod_lOBPQ3a0c9wjQ`\n\n"
            "---\n"
            "Reply `/approve` to publish with pricing, or `/reject` to keep hidden.\n\n"
            "```json\n"
            "{\n"
            "  \"slug\": \"e-commerce-copy-catalyst\",\n"
            "  \"price\": 11,\n"
            "  \"product_id\": \"prod_lOBPQ3a0c9wjQ\",\n"
            "  \"page_url\": \"https://whop.com/the-algorithmic-daemon-concern/e-commerce-copy-catalyst\",\n"
            "  \"images\": [\n"
            "    \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-img-1-v2.jpg\",\n"
            "    \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-img-2-v2.jpg\"\n"
            "  ],\n"
            "  \"files\": [\n"
            "    {\"name\": \"e-commerce-copy-catalyst.pdf\", \"url\": \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-e-commerce-copy-catalyst.pdf\"},\n"
            "    {\"name\": \"e-commerce-copy-catalyst.docx\", \"url\": \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-e-commerce-copy-catalyst.docx\"},\n"
            "    {\"name\": \"e-commerce-copy-catalyst.zip\", \"url\": \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-e-commerce-copy-catalyst.zip\"},\n"
            "    {\"name\": \"pack.html\", \"url\": \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/e-commerce-copy-catalyst-pack.html\"}\n"
            "  ],\n"
            "  \"pack\": {\n"
            "    \"title\": \"E-commerce Copy Catalyst\",\n"
            "    \"description\": \"This pack provides a direct path to compelling e-commerce copy.\"\n"
            "  }\n"
            "}\n"
            "```\n"
        )

    def test_extract_payload_issue_12(self) -> None:
        """Extract and validate payload from issue #12 format."""
        payload = extract_payload(self.issue_12_body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "e-commerce-copy-catalyst")
        self.assertEqual(payload["price"], 11)
        self.assertEqual(payload["product_id"], "prod_lOBPQ3a0c9wjQ")
        self.assertEqual(len(payload["images"]), 2)
        self.assertEqual(len(payload["files"]), 4)
        self.assertEqual(payload["pack"]["title"], "E-commerce Copy Catalyst")

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
        payload = extract_payload(self.issue_12_body)
        metadata = {
            "slug": payload.get("slug"),
            "pack": payload.get("pack"),
            "page_url": payload.get("page_url"),
            "file_urls": payload.get("files") or payload.get("file_urls"),
            "image_urls": payload.get("images") or payload.get("image_urls"),
            "description": (payload.get("pack") or {}).get("description", ""),
        }
        self.assertEqual(metadata["slug"], "e-commerce-copy-catalyst")
        self.assertEqual(len(metadata["file_urls"]), 4)
        self.assertEqual(len(metadata["image_urls"]), 2)
        self.assertEqual(metadata["page_url"], "https://whop.com/the-algorithmic-daemon-concern/e-commerce-copy-catalyst")
        self.assertEqual(metadata["description"], "This pack provides a direct path to compelling e-commerce copy.")

    def test_update_manifest_asset(self) -> None:
        """Verify update_manifest_asset function correctly updates asset fields."""
        manifest_path = Path(__file__).resolve().parent.parent / "state" / "manifest.json"
        initial_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        update_manifest_asset("e-commerce-copy-catalyst", {"price": 11.0, "status": "live"})
        updated_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        matching = [a for a in updated_data["assets"] if a.get("slug") == "e-commerce-copy-catalyst"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["price"], 11.0)
        self.assertEqual(matching[0]["status"], "live")


if __name__ == "__main__":
    unittest.main()
