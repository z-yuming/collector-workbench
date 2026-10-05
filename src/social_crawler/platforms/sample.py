from __future__ import annotations

from social_crawler.models import CollectionResult, CollectionTask, SocialContent, SocialComment
from social_crawler.platforms.base import PlatformCollector


class SampleCollector(PlatformCollector):
    def collect(self, task: CollectionTask) -> CollectionResult:
        contents = [
            SocialContent(
                platform=task.platform,
                keyword=task.query,
                source_url="sample://public-content/1",
                content_id="sample-1",
                author_name="sample_author",
                title=f"Sample public content for {task.query}",
                description="This row verifies the public social data export schema.",
                like_count="123",
                comment_count="45",
                favorite_count="6",
                share_count="7",
                play_count="890",
                capture_method="sample",
            )
        ]
        comments = []
        if task.collect_comments:
            comments.append(
                SocialComment(
                    platform=task.platform,
                    content_id="sample-1",
                    source_url="sample://public-content/1",
                    comment_id="sample-comment-1",
                    comment_text="Sample public comment",
                    comment_author="sample_commenter",
                    comment_likes="3",
                )
            )
        return CollectionResult(task=task, contents=contents, comments=comments)
