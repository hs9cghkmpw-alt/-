"""依存フリー。/api/pairing/start の二次防御(多層防御)。
一次防御は apps/web/nginx.conf での edge ブロック。ここでは、PC自身からの
直接呼び出し(`docker compose exec server curl http://localhost:8000/...`)らしさを、
「ループバックからの接続であり、かつリバースプロキシを経由した形跡(X-Forwarded-*等)が
無いこと」で判定する。"""
from __future__ import annotations

from typing import Mapping

_TRUSTED_HOSTS = {"127.0.0.1", "::1", "localhost"}
_PROXY_HEADER_MARKERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip")


def is_trusted_local_request(headers: Mapping[str, str], client_host: str | None) -> bool:
    if client_host not in _TRUSTED_HOSTS:
        return False
    lowered_keys = {k.lower() for k in headers.keys()}
    if any(marker in lowered_keys for marker in _PROXY_HEADER_MARKERS):
        return False
    return True
