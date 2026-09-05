"""test_manifest.py — Unit test suite validating state/manifest.json."""
import json
import unittest
from pathlib import Path


class TestManifest(unittest.TestCase):
    """Manifest data validation tests."""

    @classmethod
    def setUpClass(cls):
        """Load manifest.json from the state directory."""
        cls.manifest_path = Path(__file__).resolve().parent.parent / "state" / "manifest.json"
        cls.assertTrue(cls.manifest_path.exists(), "manifest.json must exist")
        cls.data = json.loads(cls.manifest_path.read_text(encoding="utf-8"))

    def test_manifest_structure(self):
        """Validate top-level manifest structure."""
        self.assertIn("assets", self.data)
        self.assertIsInstance(self.data["assets"], list)
        self.assertGreater(len(self.data["assets"]), 0)

    def test_seo_outline_architect_asset(self):
        """Validate reconciled SEO Outline Architect asset entry for issue #10."""
        assets = {a["slug"]: a for a in self.data["assets"]}
        self.assertIn("seo-outline-architect-entity-mapping-edition", assets)

        asset = assets["seo-outline-architect-entity-mapping-edition"]
        self.assertEqual(asset["title"], "SEO Outline Architect: Entity Mapping Edition")
        self.assertEqual(asset["price"], 11.0)
        self.assertFalse(asset["free"])
        self.assertEqual(asset["product_id"], "prod_lY8V0LqQ9dr0x")
        self.assertEqual(asset["status"], "live")
        self.assertEqual(asset["marketplace_status"], "pending_review")

        self.assertIn("files", asset)
        self.assertEqual(len(asset["files"]), 4)
        file_names = {f["name"] for f in asset["files"]}
        expected_names = {
            "seo-outline-architect-entity-mapping-edition.pdf",
            "seo-outline-architect-entity-mapping-edition.docx",
            "seo-outline-architect-entity-mapping-edition.zip",
            "pack.html",
        }
        self.assertEqual(file_names, expected_names)

        self.assertIn("release_images", asset)
        self.assertEqual(len(asset["release_images"]), 2)
        for img_url in asset["release_images"]:
            self.assertTrue(img_url.startswith("https://github.com/simalidudu-boop/asset-bot/releases/download/"))

    def test_all_assets_have_valid_fields(self):
        """Ensure all assets conform to schema requirements."""
        for asset in self.data["assets"]:
            self.assertIn("slug", asset)
            self.assertIn("title", asset)
            self.assertIn("status", asset)
            self.assertIn("kind", asset)
            self.assertIn("price", asset)
            self.assertIsInstance(asset["price"], (int, float))
            self.assertGreaterEqual(asset["price"], 0.0)


if __name__ == "__main__":
    unittest.main()
