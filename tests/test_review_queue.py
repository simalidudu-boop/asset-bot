import json
import unittest
from engine.approve_from_issue import extract_payload


class TestReviewQueue(unittest.TestCase):
    def test_extract_payload_standard(self):
        body = """
## Paid Asset Approval Required
- **Product:** The One-to-Many Content Engine
- **Price:** $11

```json
{
  "slug": "the-one-to-many-content-engine",
  "product_id": "prod_HyjncGDj3C8cE",
  "price": 11,
  "files": [
    {
      "name": "The One-to-Many Content Engine.pdf",
      "url": "https://example.com/file.pdf"
    }
  ]
}
```
"""
        payload = extract_payload(body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "the-one-to-many-content-engine")
        self.assertEqual(payload["product_id"], "prod_HyjncGDj3C8cE")
        self.assertEqual(payload["price"], 11)
        self.assertEqual(len(payload["files"]), 1)

    def test_extract_payload_with_trailing_spaces(self):
        body = """
```json   
{
  "slug": "test-slug",
  "price": 15
}
```  
"""
        payload = extract_payload(body)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["slug"], "test-slug")
        self.assertEqual(payload["price"], 15)

    def test_extract_payload_invalid_json(self):
        body = """
```json
{ invalid json
```
"""
        payload = extract_payload(body)
        self.assertIsNone(payload)

    def test_extract_payload_no_block(self):
        body = "No code blocks here."
        payload = extract_payload(body)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
