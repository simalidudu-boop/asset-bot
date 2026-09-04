import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "state" / "manifest.json"


class TestManifest(unittest.TestCase):
    """Test suite for asset manifest validation."""

    def setUp(self):
        self.assertTrue(MANIFEST_PATH.exists(), "manifest.json must exist")
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def test_manifest_structure(self):
        """Verify top-level manifest structure and schema."""
        self.assertIn("assets", self.data)
        self.assertIsInstance(self.data["assets"], list)
        self.assertGreater(len(self.data["assets"]), 0)

    def test_legal_draft_pro_asset(self):
        """Verify legal-draft-pro configuration and deliverable files."""
        matched = [a for a in self.data["assets"] if a.get("slug") == "legal-draft-pro"]
        self.assertEqual(len(matched), 1, "legal-draft-pro should exist in manifest")
        asset = matched[0]
        self.assertEqual(asset["title"], "Legal Draft Pro")
        self.assertEqual(asset["price"], 14.0)
        self.assertEqual(asset["status"], "live")
        self.assertEqual(asset["product_id"], "prod_wr1JXUmiACthc")
        self.assertEqual(asset["marketplace_status"], "pending_review")
        self.assertIn("files", asset)
        self.assertEqual(len(asset["files"]), 4)
        file_names = {item["name"] for item in asset["files"]}
        expected_names = {
            "legal-draft-pro.pdf",
            "legal-draft-pro.docx",
            "legal-draft-pro.zip",
            "pack.html",
        }
        self.assertEqual(file_names, expected_names)
        self.assertIn("release_images", asset)
        self.assertEqual(len(asset["release_images"]), 2)


if __name__ == "__main__":
    unittest.main()
