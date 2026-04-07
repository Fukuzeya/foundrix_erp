"""Tests for the pagination utilities."""

import pytest
from src.core.pagination import PageParams, PaginatedResponse


def test_page_params_defaults():
    params = PageParams()
    assert params.page == 1
    assert params.size == 20
    assert params.offset == 0


def test_page_params_offset_calculation():
    params = PageParams(page=3, size=10)
    assert params.offset == 20


def test_paginated_response_schema():
    from pydantic import BaseModel

    class ItemSchema(BaseModel):
        name: str

    resp = PaginatedResponse[ItemSchema](
        items=[ItemSchema(name="test")],
        total=50,
        page=1,
        size=20,
        pages=3,
    )
    assert resp.total == 50
    assert len(resp.items) == 1
    assert resp.pages == 3
