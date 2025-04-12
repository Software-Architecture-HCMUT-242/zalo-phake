from typing import Generic, TypeVar, List

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

def common_pagination_parameters(
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    size: int = Query(50, ge=50, le=200, description="Number of items per page"),
):
    return PaginationParams(page=page, size=size)

class PaginationParams(BaseModel):
    page: int = Query(1, ge=1, description="Page number (starting from 1)")
    size: int = Query(10, ge=1, le=100, description="Number of items per page")


class PaginatedResponse(BaseModel, Generic[T]):
    """
    A generic paginated response model for handling paginated data.

    Attributes:
        items (List[T]): The list of items for the current page.
        total (int): The total number of items across all pages.
        page (int): The current page number (1-indexed).
        size (int): The number of items per page.
        pages (int): The total number of pages.

    Methods:
        create(items: List[T], total: int, page: int, size: int) -> "PaginatedResponse":
            A static method to create a PaginatedResponse instance.

            Args:
                items (List[T]): The list of items for the current page.
                total (int): The total number of items across all pages.
                page (int): The current page number (1-indexed).
                size (int): The number of items per page.

            Returns:
                PaginatedResponse: An instance of PaginatedResponse with the calculated total pages.

    Example:
        # Example usage of PaginatedResponse
        items = ["item1", "item2", "item3"]
        total = 10
        page = 1
        size = 3

        paginated_response = PaginatedResponse.create(items=items, total=total, page=page, size=size)
        print(paginated_response)
    """
    items: List[T]
    total: int
    page: int
    size: int
    pages: int

    @staticmethod
    def create(items: List[T], total: int, page: int, size: int) -> "PaginatedResponse":
        pages = (total + size - 1) // size  # Calculate total pages
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            size=size,
            pages=pages,
        )


def paginate(data: List[T], page: int, size: int) -> List[T]:
    start = (page - 1) * size
    end = start + size
    return data[start:end]