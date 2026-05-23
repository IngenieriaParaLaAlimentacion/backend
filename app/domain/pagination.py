from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class PaginatedResult(Generic[T]):
    """Generic container for a single page of query results."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
