import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from engine import topics


class TestTopics(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_state = topics.STATE
        topics.STATE = Path(self.temp_dir)

    def tearDown(self):
        topics.STATE = self.old_state
        shutil.rmtree(self.temp_dir)

    def test_record_asset_defaults(self):
        topics.record_asset("test-slug", "Test Title", "Test Topic", "prompt-pack")
        mf = Path(self.temp_dir) / "manifest.json"
        self.assertTrue(mf.exists())
        data = json.loads(mf.read_text())
        self.assertEqual(len(data["assets"]), 1)
        asset = data["assets"][0]
        self.assertEqual(asset["slug"], "test-slug")
        self.assertEqual(asset["title"], "Test Title")
        self.assertTrue(asset["free"])
        self.assertEqual(asset["status"], "staged")

    def test_record_asset_paid(self):
        topics.record_asset("paid-slug", "Paid Title", "Paid Topic", "prompt-pack",
                            extra={"free": False, "price": 11.0, "status": "pending_approval"})
        mf = Path(self.temp_dir) / "manifest.json"
        data = json.loads(mf.read_text())
        asset = data["assets"][0]
        self.assertEqual(asset["slug"], "paid-slug")
        self.assertFalse(asset["free"])
        self.assertEqual(asset["price"], 11.0)
        self.assertEqual(asset["status"], "pending_approval")


if __name__ == "__main__":
    unittest.main()
