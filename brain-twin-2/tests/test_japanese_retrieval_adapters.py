from types import SimpleNamespace

from brain_twin_eval.adapters import HybridRetriever, LexicalRetriever, VectorRetriever


def test_lexical_adapter_maps_existing_search_results(monkeypatch):
    conn = object()

    def fake_search(seen_conn, query, *, limit):
        assert seen_conn is conn
        assert query == "検索"
        assert limit == 3
        return [SimpleNamespace(memory_id="mem-001", score=0.75)]

    monkeypatch.setattr("brain_twin_eval.adapters.search.search", fake_search)
    results = LexicalRetriever(conn).search("検索", 3)
    assert [(result.memory_id, result.score) for result in results] == [("mem-001", 0.75)]


def test_vector_adapter_maps_existing_vector_results(monkeypatch):
    conn = object()
    provider = object()
    backend = object()

    def fake_vector_search(seen_conn, query, seen_provider, seen_backend, *, limit):
        assert (seen_conn, seen_provider, seen_backend) == (conn, provider, backend)
        assert query == "意味検索"
        assert limit == 10
        return [SimpleNamespace(memory_id="mem-002", similarity=0.91)]

    monkeypatch.setattr("brain_twin_eval.adapters.vector_search.vector_search", fake_vector_search)
    results = VectorRetriever(conn, provider, backend).search("意味検索", 10)
    assert [(result.memory_id, result.score) for result in results] == [("mem-002", 0.91)]


def test_hybrid_adapter_maps_existing_hybrid_results(monkeypatch):
    conn = object()
    provider = object()
    backend = object()

    def fake_hybrid_search(seen_conn, query, seen_provider, seen_backend, *, limit):
        assert (seen_conn, seen_provider, seen_backend) == (conn, provider, backend)
        assert query == "混合検索"
        assert limit == 5
        return [SimpleNamespace(memory_id="mem-003", final_score=0.42)]

    monkeypatch.setattr("brain_twin_eval.adapters.hybrid_search.hybrid_search", fake_hybrid_search)
    results = HybridRetriever(conn, provider, backend).search("混合検索", 5)
    assert [(result.memory_id, result.score) for result in results] == [("mem-003", 0.42)]
