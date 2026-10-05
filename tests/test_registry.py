from __future__ import annotations

import builtins
import unittest
from unittest.mock import patch

from social_crawler.registry import get_collector
from social_crawler.settings import Settings


class RegistryTest(unittest.TestCase):
    def test_browser_dependency_does_not_block_other_collectors(self) -> None:
        original_import = builtins.__import__

        def without_browser(name, *args, **kwargs):
            if name == "social_crawler.platforms.browser_product" or name.startswith("playwright"):
                raise ModuleNotFoundError("No module named 'playwright'", name="playwright")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_browser):
            for platform, mode in [("sample", "sample"), ("generic_web", "web"), ("taobao", "search")]:
                with self.subTest(platform=platform):
                    self.assertIsNotNone(get_collector(platform, mode, Settings()))
            with self.assertRaisesRegex(RuntimeError, "浏览器采集组件未安装"):
                get_collector("xiaohongshu", "browser", Settings())

    def test_unsupported_browser_platform_is_rejected_before_import(self) -> None:
        with self.assertRaisesRegex(ValueError, "Browser mode not supported"):
            get_collector("unknown", "browser", Settings())


if __name__ == "__main__":
    unittest.main()
