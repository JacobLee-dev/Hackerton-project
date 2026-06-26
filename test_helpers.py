import pandas as pd

from helpers import normalize_columns


def test_normalize_columns():
    raw = pd.DataFrame({"지출일": ["2026-01-01"], "분류": ["식비"], "금액(원)": [10000]})
    norm = normalize_columns(raw)
    assert set(norm.columns) == {"날짜", "카테고리", "지출"}


if __name__ == "__main__":
    test_normalize_columns()
    print("OK")
