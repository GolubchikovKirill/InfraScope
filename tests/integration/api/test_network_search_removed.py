"""Network search (subnet scans and the "add what was found" flow) was removed on purpose.

It may come back in a different shape; until then none of its routes may linger,
or an old bookmark/script would start scans nobody can see or stop any more.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/scanner/scan"),
        ("get", "/api/v1/scanner/status"),
        ("get", "/api/v1/scanner/results"),
        ("get", "/api/v1/scanner/settings"),
        ("post", "/api/v1/scanner/smart-search/computers"),
        ("post", "/api/v1/scanner/smart-search/cash-registers"),
        ("post", "/api/v1/scanner/add"),
        ("post", "/api/v1/scanner/rediscover-by-mac"),
        ("post", "/api/v1/switches/discover/scan"),
        ("get", "/api/v1/switches/discover/results"),
        ("post", "/api/v1/switches/discover/add"),
        ("post", "/api/v1/media-players/discover/scan"),
        ("get", "/api/v1/media-players/discover/results"),
        ("post", "/api/v1/media-players/discover/add"),
        ("post", "/api/v1/tasks/scan-network"),
    ],
)
def test_search_routes_are_gone(client: TestClient, admin_token: str, method: str, path: str) -> None:
    response = getattr(client, method)(path, headers={"Authorization": f"Bearer {admin_token}"})

    # 404 (no such route) or 405/422 where a parametrised sibling route swallows the path -
    # what must never happen is a 2xx/401/403 from a live handler
    assert response.status_code in (404, 405, 422), (path, response.status_code)


def test_the_media_player_rediscovery_by_mac_is_still_there(client: TestClient, admin_token: str) -> None:
    """The MAC-based relocation of a moved device is a different feature and stays."""
    response = client.post("/api/v1/media-players/rediscover", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code not in (404, 405)
