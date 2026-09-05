"""Unit tests validating state/manifest.json schema and reconciled asset entries."""
import json
import unittest
from pathlib import Path


class TestManifest(unittest.TestCase):
    """Test suite for validating manifest integrity and asset records."""

    def setUp(self) -> None:
        """Load manifest.json from the repository root."""
        self.manifest_path = (
            Path(__file__).resolve().parent.parent / "state" / "manifest.json"
        )
        self.assertTrue(self.manifest_path.exists())
        self.data = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def test_manifest_structure(self) -> None:
        """Validate top-level manifest schema and assets collection."""
        self.assertIn("assets", self.data)
        self.assertIsInstance(self.data["assets"], list)
        self.assertGreater(len(self.data["assets"]), 0)

    def test_long_text_to_social_gold_asset(self) -> None:
        """Validate long-text-to-social-gold asset reconciliation."""
        target = None
        for asset in self.data["assets"]:
            if asset.get("slug") == "long-text-to-social-gold":
                target = asset
                break

        self.assertIsNotNone(target)
        self.assertEqual(target["title"], "Long Text to Social Gold")
        self.assertEqual(target["price"], 11.0)
        self.assertFalse(target["free"])
        self.assertEqual(target["product_id"], "prod_8rO1cRyuwNOUR")
        self.assertEqual(target["status"], "live")
        self.assertEqual(target["marketplace_status"], "pending_review")

        self.assertIn("release_images", target)
        self.assertEqual(len(target["release_images"]), 2)
        for img in target["release_images"]:
            self.assertTrue(img.startswith("https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/"))

        self.assertIn("files", target)
        self.assertEqual(len(target["files"]), 4)
        file_names = {f["name"] for f in target["files"]}
        expected_names = {
            "long-text-to-social-gold.pdf",
            "long-text-to-social-gold.docx",
            "long-text-to-social-gold.zip",
            "pack.html",
        }
        self.assertEqual(file_names, expected_names)

        for f in target["files"]:
            self.assertTrue(f["url"].startswith("https://github.com/simalidudu-boop/asset-bot/releases/download/deliveries-2026-W36/"))

    def test_all_assets_have_valid_fields(self) -> None:
        """Ensure all assets adhere to foundational schema requirements."""
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
