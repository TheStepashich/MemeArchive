from app.service import _build_where


def test_build_where_empty():
    assert _build_where([], None) == {"pending": False}
    assert _build_where([], None, None) is None


def test_build_where_single_clause():
    assert _build_where([], True) == {"$and": [{"pending": False}, {"favorite": True}]}
    assert _build_where([], None, True) == {"pending": True}
    assert _build_where(["cat"], None) == {
        "$and": [{"pending": False}, {"tags": {"$contains": "cat"}}]
    }


def test_build_where_combines_clauses():
    assert _build_where(["cat", "funny"], False) == {
        "$and": [
            {"pending": False},
            {"favorite": False},
            {"tags": {"$contains": "cat"}},
            {"tags": {"$contains": "funny"}},
        ]
    }
