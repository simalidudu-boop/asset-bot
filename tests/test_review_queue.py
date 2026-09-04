import unittest
from engine.approve_from_issue import extract_payload


class TestReviewQueue(unittest.TestCase):
    """Test suite for issue review payload extraction."""

    def test_extract_payload_issue_7(self):
        """Verify extraction of the Legal Draft Pro issue payload."""
        body = """
## Paid asset awaiting approval \u2014 `legal-draft-pro`

- **Title:** Legal Draft Pro
- **Price:** $14
- **Category:** prompt-pack (9 prompts, 1 skills)
- **Product:** `prod_wr1JXUmiACthc` \u2014 https://whop.com/the-algorithmic-daemon-concern/legal-draft-pro
- **Images:** 2 \u2014 [img 1](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/legal-draft-pro-img-1-v2.jpg) \u00b7 [img 2](https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/legal-draft-pro-img-2-v2.jpg)
- **Deliverables:**
  - `legal-draft-pro.pdf`
  - `legal-draft-pro.docx`
  - `legal-draft-pro.zip`
  - `pack.html`

Comment `/approve` to publish to Whop, or `/reject <reason>` to archive.

```json
{
  "slug": "legal-draft-pro",
  "product_id": "prod_wr1JXUmiACthc",
  "price": 14,
  "files": [
    {
      "name": "legal-draft-pro.pdf",
      "url": "https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/legal-draft-pro-legal-draft-pro.pdf"
    },
    {
      "name": "legal-draft-pro.docx",
      "url": "https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/legal-draft-pro-legal-draft-pro.docx"
    },
    {
      "name": "legal-draft-pro.zip",
      "url": "https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/legal-draft-pro-legal-draft-pro.zip"
    },
    {
      "name": "pack.html",
      "url": "https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/legal-draft-pro-pack.html"
    }
  ],
  "images": [
    "https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/legal-draft-pro-img-1-v2.jpg",
    "https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/legal-draft-pro-img-2-v2.jpg"
  ]
}
```
"""
        payload = extract_payload(body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "legal-draft-pro")
        self.assertEqual(payload["product_id"], "prod_wr1JXUmiACthc")
        self.assertEqual(payload["price"], 14)
        self.assertEqual(len(payload["files"]), 4)
        self.assertEqual(len(payload["images"]), 2)

    def test_extract_payload_with_trailing_spaces(self):
        """Verify robust extraction when json block contains trailing spaces."""
        body = """
```json   
{
  "slug": "test-slug",
  "price": 14.0
}
```  
"""
        payload = extract_payload(body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "test-slug")
        self.assertEqual(payload["price"], 14.0)

    def test_extract_payload_invalid_json(self):
        """Verify None is returned when JSON content is malformed."""
        body = """
```json
{ invalid json
```
"""
        payload = extract_payload(body)
        self.assertIsNone(payload)

    def test_extract_payload_no_block(self):
        """Verify None is returned when no JSON code block exists."""
        body = "Issue without code block."
        payload = extract_payload(body)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
