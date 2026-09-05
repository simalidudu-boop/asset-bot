"""test_review_queue.py — Unit test suite for review queue parsing and helpers."""
import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from approve_from_issue import extract_payload, update_manifest_asset


class TestReviewQueue(unittest.TestCase):
    """Tests for review queue event processing and payload extraction."""

    def setUp(self):
        """Set up mock issue body representative of issue #10."""
        self.issue_10_body = (
            "## SEO Outline Architect: Entity Mapping Edition\n"
            "- **Price:** $11\n"
            "- **Category:** prompt-pack\n"
            "- **Prompts:** 8 | **Skills:** 2\n"
            "- **Description:** Stop guessing what Google wants. This pack equips you with prompts to build SEO-optimized blog post outlines, complete with semantic entity mapping.\n\n"
            "### Images\n"
            "- https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-img-1-v2.jpg\n"
            "- https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-img-2-v2.jpg\n\n"
            "### Deliverables\n"
            "- [seo-outline-architect-entity-mapping-edition.pdf](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-seo-outline-architect-entity-mapping-edition.pdf)\n"
            "- [seo-outline-architect-entity-mapping-edition.docx](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-seo-outline-architect-entity-mapping-edition.docx)\n"
            "- [seo-outline-architect-entity-mapping-edition.zip](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-seo-outline-architect-entity-mapping-edition.zip)\n"
            "- [pack.html](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-pack.html)\n\n"
            "**Whop page:** https://whop.com/the-algorithmic-daemon-concern/seo-outline-architect-entity-mapping-edition\n"
            "**Product ID:** `prod_lY8V0LqQ9dr0x`\n\n"
            "---\n"
            "Reply `/approve` to publish with pricing, or `/reject` to keep hidden.\n\n"
            "```json\n"
            "{\n"
            "  \"slug\": \"seo-outline-architect-entity-mapping-edition\",\n"
            "  \"price\": 11,\n"
            "  \"product_id\": \"prod_lY8V0LqQ9dr0x\",\n"
            "  \"page_url\": \"https://whop.com/the-algorithmic-daemon-concern/seo-outline-architect-entity-mapping-edition\",\n"
            "  \"images\": [\n"
            "    \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-img-1-v2.jpg\",\n"
            "    \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-img-2-v2.jpg\"\n"
            "  ],\n"
            "  \"files\": [\n"
            "    {\"name\": \"seo-outline-architect-entity-mapping-edition.pdf\", \"url\": \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-seo-outline-architect-entity-mapping-edition.pdf\"},\n"
            "    {\"name\": \"seo-outline-architect-entity-mapping-edition.docx\", \"url\": \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-seo-outline-architect-entity-mapping-edition.docx\"},\n"
            "    {\"name\": \"seo-outline-architect-entity-mapping-edition.zip\", \"url\": \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-seo-outline-architect-entity-mapping-edition.zip\"},\n"
            "    {\"name\": \"pack.html\", \"url\": \"https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/seo-outline-architect-entity-mapping-edition-pack.html\"}\n"
            "  ],\n"
            "  \"pack\": {\n"
            "    \"title\": \"SEO Outline Architect: Entity Mapping Edition\",\n"
            "    \"description\": \"Stop guessing what Google wants.\"\n"
            "  }\n"
            "}\n"
            "```\n"
        )

    def test_extract_payload_issue_10(self):
        """Extract and validate payload from issue #10 format."""
        payload = extract_payload(self.issue_10_body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "seo-outline-architect-entity-mapping-edition")
        self.assertEqual(payload["price"], 11)
        self.assertEqual(payload["product_id"], "prod_lY8V0LqQ9dr0x")
        self.assertEqual(len(payload["images"]), 2)
        self.assertEqual(len(payload["files"]), 4)
        self.assertEqual(payload["pack"]["title"], "SEO Outline Architect: Entity Mapping Edition")

    def test_extract_payload_whitespace_resilience(self):
        """Verify extraction handles whitespace surrounding code fences."""
        body = "   ```json   \n{\"slug\": \"test\", \"price\": 5}   \n```   "
        payload = extract_payload(body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "test")
        self.assertEqual(payload["price"], 5)

    def test_extract_payload_invalid_json(self):
        """Verify invalid JSON returns None instead of raising exceptions."""
        body = "```json\n{unquoted_key: invalid}\n```"
        payload = extract_payload(body)
        self.assertIsNone(payload)

    def test_extract_payload_no_block(self):
        """Verify missing json code block returns None."""
        body = "No code block here"
        payload = extract_payload(body)
        self.assertIsNone(payload)

    def test_metadata_construction(self):
        """Verify metadata mapping conforms to publish.approve requirements."""
        payload = extract_payload(self.issue_10_body)
        metadata = {
            "slug": payload.get("slug"),
            "pack": payload.get("pack"),
            "page_url": payload.get("page_url"),
            "file_urls": payload.get("files") or payload.get("file_urls"),
            "image_urls": payload.get("images") or payload.get("image_urls"),
            "description": (payload.get("pack") or {}).get("description", ""),
        }
        self.assertEqual(metadata["slug"], "seo-outline-architect-entity-mapping-edition")
        self.assertEqual(len(metadata["file_urls"]), 4)
        self.assertEqual(len(metadata["image_urls"]), 2)
        self.assertEqual(metadata["page_url"], "https://whop.com/the-algorithmic-daemon-concern/seo-outline-architect-entity-mapping-edition")
        self.assertEqual(metadata["description"], "Stop guessing what Google wants.")


if __name__ == "__main__":
    unittest.main()
