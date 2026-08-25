from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins.qqzone.storage import QQZoneRepository


class StorageTests(unittest.TestCase):
    def test_cache_actions_drafts_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = QQZoneRepository(Path(directory) / "qqzone.sqlite3")
            repository.cache_feeds([{"user_id": "10001", "tid": "feed-1", "content": "hello"}])
            self.assertEqual(repository.find_feed("10001", "feed-1")["content"], "hello")  # type: ignore[index]

            repository.record_action("post", content="hello", source="test")
            self.assertEqual(repository.count_success_today("post"), 1)
            self.assertEqual(repository.recent_actions(1)[0]["source"], "test")

            draft_id = repository.create_draft("hello", "平静", "", "context")
            repository.mark_draft_published(draft_id, "feed-2")
            draft = repository.get_draft(draft_id)
            assert draft is not None
            self.assertEqual(draft["status"], "published")
            self.assertEqual(draft["tid"], "feed-2")

            repository.set_state("last_slot", "2026-08-20-18")
            self.assertEqual(repository.get_state("last_slot"), "2026-08-20-18")


if __name__ == "__main__":
    unittest.main()
