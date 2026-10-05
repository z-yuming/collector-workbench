from __future__ import annotations

import unittest
from pathlib import Path

from social_crawler.platforms.douyin_parser import (
    extract_comments_from_xml,
    extract_public_content_from_xml,
    has_comment_panel,
)


FIXTURE = Path(__file__).parent / "fixtures" / "douyin_public_content.xml"
SEQUENCE_FIXTURE = Path(__file__).parent / "fixtures" / "douyin_comment_panel_sequence.xml"


class DouyinParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.xml = FIXTURE.read_text(encoding="utf-8")

    def test_extracts_public_content_metrics_and_product(self) -> None:
        content = extract_public_content_from_xml(self.xml, platform="douyin", keyword="nike")

        self.assertIsNotNone(content)
        assert content is not None
        self.assertEqual(content.author_name, "nike_store")
        self.assertEqual(content.like_count, "1.2万")
        self.assertEqual(content.comment_count, "345")
        self.assertEqual(content.favorite_count, "678")
        self.assertEqual(content.share_count, "89")
        self.assertEqual(content.play_count, "9.8万")
        self.assertEqual(content.product_title, "Nike Air Zoom Pegasus 男款跑鞋")
        self.assertEqual(content.product_price, "499")
        self.assertEqual(content.product_pay_count, "2.3万")

    def test_extracts_visible_public_comments(self) -> None:
        comments = extract_comments_from_xml(self.xml, platform="douyin", limit=10)

        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0].comment_author, "用户甲")
        self.assertEqual(comments[0].comment_text, "这双鞋脚感不错")
        self.assertEqual(comments[0].comment_likes, "15")
        self.assertEqual(comments[1].comment_author, "用户乙")
        self.assertEqual(comments[1].comment_text, "尺码偏正常")
        self.assertEqual(comments[1].comment_likes, "3")

    def test_detects_comment_panel_marker(self) -> None:
        self.assertTrue(has_comment_panel(self.xml))
        self.assertFalse(
            has_comment_panel(
                """<?xml version="1.0" encoding="UTF-8"?><hierarchy><node text="Nike Air Zoom" content-desc="" /></hierarchy>"""
            )
        )

    def test_extracts_sequenced_comment_panel_nodes(self) -> None:
        xml = SEQUENCE_FIXTURE.read_text(encoding="utf-8")
        comments = extract_comments_from_xml(xml, platform="douyin", limit=10)

        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0].comment_author, "用户甲")
        self.assertEqual(comments[0].comment_text, "@朋友: 这个公开评论可以采集")
        self.assertEqual(comments[0].comment_likes, "588")
        self.assertEqual(comments[1].comment_author, "用户乙")
        self.assertEqual(comments[1].comment_text, "第二条评论")
        self.assertEqual(comments[1].comment_likes, "0")


if __name__ == "__main__":
    unittest.main()
