from __future__ import annotations

import unittest
from pathlib import Path

from social_crawler.models import CollectionTask
from social_crawler.platforms.generic_web import GenericWebCollector, extract_metrics, parse_comment_text
from social_crawler.registry import get_collector
from social_crawler.settings import Settings


FIXTURE = Path(__file__).parent / "fixtures" / "generic_social_public.html"


class GenericWebTest(unittest.TestCase):
    def test_extract_metrics_from_public_text(self) -> None:
        metrics = extract_metrics(["Likes: 123", "Comments: 45", "Favorites: 6", "Shares: 7", "Views: 890"])

        self.assertEqual(metrics["like_count"], "123")
        self.assertEqual(metrics["comment_count"], "45")
        self.assertEqual(metrics["favorite_count"], "6")
        self.assertEqual(metrics["share_count"], "7")
        self.assertEqual(metrics["play_count"], "890")

    def test_parse_comment_text(self) -> None:
        comment = parse_comment_text("Author: alice Text: Great public review Likes: 3")

        self.assertEqual(comment["author"], "alice")
        self.assertEqual(comment["text"], "Great public review")
        self.assertEqual(comment["likes"], "3")

    def test_collects_public_html_file(self) -> None:
        collector = GenericWebCollector(Settings())
        result = collector.collect(
            CollectionTask(
                platform="generic_web",
                task_type="content",
                query=str(FIXTURE),
                collect_comments=True,
            )
        )

        self.assertEqual(len(result.contents), 1)
        self.assertEqual(result.contents[0].title, "Nike public running review")
        self.assertEqual(result.contents[0].author_name, "public_runner")
        self.assertEqual(result.contents[0].like_count, "123")
        self.assertEqual(result.contents[0].comment_count, "45")
        self.assertEqual(result.contents[0].favorite_count, "6")
        self.assertEqual(result.contents[0].share_count, "7")
        self.assertEqual(result.contents[0].play_count, "890")
        self.assertEqual(len(result.comments), 2)
        self.assertEqual(result.comments[0].comment_author, "alice")
        self.assertEqual(result.comments[0].comment_text, "Great public review")

    def test_registry_resolves_generic_web(self) -> None:
        collector = get_collector("generic_web", "web", Settings())
        self.assertIsInstance(collector, GenericWebCollector)


if __name__ == "__main__":
    unittest.main()
