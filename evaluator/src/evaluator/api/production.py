"""Server-side client for completed production call traces."""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ProductionSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductionSource:
    base_url: str
    token: str
    timeout: float = 15.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def fetch(self) -> list[dict]:
        if not self.configured:
            return []
        rows: list[dict] = []
        page = 1
        while page:
            query = urlencode({"page": page, "page_size": 100})
            url = f"{self.base_url.rstrip('/')}/ops/api/evaluator/calls?{query}"
            request = Request(url, headers={"X-Ops-Token": self.token, "Accept": "application/json"})
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
            except HTTPError as exc:
                raise ProductionSyncError(f"producción respondió HTTP {exc.code}") from exc
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                raise ProductionSyncError(f"no se pudo leer producción: {exc}") from exc
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise ProductionSyncError("producción devolvió un formato no reconocido")
            rows.extend(item for item in items if isinstance(item, dict))
            next_page = payload.get("next_page")
            page = int(next_page) if isinstance(next_page, int) and next_page > page else 0
        return rows
