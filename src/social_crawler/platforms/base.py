from __future__ import annotations

from abc import ABC, abstractmethod

from social_crawler.models import CollectionResult, CollectionTask
from social_crawler.settings import Settings


class PlatformCollector(ABC):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def collect(self, task: CollectionTask) -> CollectionResult:
        raise NotImplementedError
