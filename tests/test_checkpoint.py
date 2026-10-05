from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from social_crawler.checkpoint import checkpoint_path, load_checkpoint, save_checkpoint
from social_crawler.models import CollectionTask


class CheckpointTest(unittest.TestCase):
    def test_checkpoint_round_trip_and_safe_path(self) -> None:
        task = CollectionTask(platform="douyin", task_type="keyword", query="nike shoes/跑鞋", mode="ui")

        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            checkpoint = load_checkpoint(log_dir, task)
            checkpoint.mark_processed("candidate-1")
            checkpoint.mark_processed("candidate-1")
            checkpoint.mark_processed("candidate-2")
            saved = save_checkpoint(log_dir, task, checkpoint)

            self.assertEqual(saved, checkpoint_path(log_dir, task))
            self.assertTrue(saved.exists())

            reloaded = load_checkpoint(log_dir, task)
            self.assertEqual(reloaded.processed_candidate_ids, ["candidate-1", "candidate-2"])
            self.assertEqual(reloaded.processed_set, {"candidate-1", "candidate-2"})


if __name__ == "__main__":
    unittest.main()
