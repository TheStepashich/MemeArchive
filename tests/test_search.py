from app.service import _build_where


def test_build_where_empty():
    assert _build_where([], None) is None


def test_build_where_single_clause():
    assert _build_where([], True) == {"favorite": True}
    assert _build_where(["cat"], None) == {"tags": {"$contains": "cat"}}


def test_build_where_combines_clauses():
    assert _build_where(["cat", "funny"], False) == {
        "$and": [
            {"favorite": False},
            {"tags": {"$contains": "cat"}},
            {"tags": {"$contains": "funny"}},
        ]
    }
