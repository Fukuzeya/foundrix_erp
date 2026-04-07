"""Tests for system health and info endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_info_returns_platform_info(client: AsyncClient):
    response = await client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert data["platform"] == "Foundrix ERP"
    assert data["environment"] == "development"
