COLUMN_ALIASES = {
    "날짜": {"날짜", "지출일", "거래일", "일자"},
    "카테고리": {"카테고리", "분류", "항목", "category"},
    "지출": {"지출", "금액", "지출(원)", "금액(원)", "지출액"},
}


def normalize_columns(raw):
    rename = {}
    for col in raw.columns:
        for canon, aliases in COLUMN_ALIASES.items():
            if str(col).strip() in aliases:
                rename[col] = canon
                break
    return raw.rename(columns=rename)
