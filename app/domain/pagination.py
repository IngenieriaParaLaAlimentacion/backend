from dataclasses import dataclass
from math import ceil
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

    @classmethod
    def build(
        cls, items: list[T], total: int, page: int, page_size: int
    ) -> "PaginatedResult[T]":
        total_pages = ceil(total / page_size) if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
