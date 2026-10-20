from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any


class BaseParser(ABC):
    @abstractmethod
    def parse(self, content: bytes) -> Iterator[dict[str, Any]]:
        """Yield records from the supplied file contents."""
        raise NotImplementedError
