import altair as alt
import numpy as np
import pandas as pd
import requests
import streamlit as st

from helpers import normalize_columns

st.set_page_config(page_title="가계부 대시보드", page_icon="💸", layout="wide")

st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {
        background-color: #EAF7F0;
        border: 1px solid #C9E9D6;
        border-radius: 12px;
        padding: 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

CATEGORIES = ["식비", "교통", "주거", "쇼핑", "문화/취미", "해외", "기타"]


def demo_data():
    rng = np.random.default_rng(7)
    dates = pd.date_range("2026-04-01", "2026-06-25")
    n = 200
    timestamps = pd.Series(rng.choice(dates, n)) + pd.to_timedelta(rng.integers(0, 86_400, n), unit="s")
    return pd.DataFrame({
        "날짜": timestamps,
        "카테고리": rng.choice(CATEGORIES, n, p=[0.28, 0.13, 0.13, 0.13, 0.13, 0.1, 0.1]),
        "지출": rng.integers(3_000, 80_000, n),
    })


@st.cache_data(ttl=3600)
def fetch_usd_krw(start_date, end_date):
    resp = requests.get(
        f"https://api.frankfurter.app/{start_date}..{end_date}",
        params={"from": "USD", "to": "KRW"},
        timeout=10,
    )
    resp.raise_for_status()
    rates = resp.json()["rates"]
    return pd.DataFrame({
        "날짜": pd.to_datetime(list(rates.keys())),
        "USD/KRW": [v["KRW"] for v in rates.values()],
    }).sort_values("날짜")


st.title("💸 가계부 대시보드")

with st.sidebar:
    st.header("데이터 업로드")
    uploaded = st.file_uploader("지출 내역 엑셀 업로드 (날짜/카테고리/지출 컬럼)", type=["xlsx"])

if uploaded:
    df = normalize_columns(pd.read_excel(uploaded))
    missing = {"날짜", "카테고리", "지출"} - set(df.columns)
    if missing:
        st.error(f"인식할 수 없는 컬럼이 있습니다: {missing}")
        st.stop()
    df["날짜"] = pd.to_datetime(df["날짜"])
else:
    st.caption("업로드 전이라 예시 데이터로 표시 중입니다. 본인 엑셀을 올리면 바로 교체됩니다.")
    df = demo_data()

with st.sidebar:
    st.header("필터")
    categories = sorted(df["카테고리"].unique())
    selected_categories = st.multiselect("카테고리 선택", categories, default=categories)
    min_date, max_date = df["날짜"].min().date(), df["날짜"].max().date()
    date_range = st.date_input("기간 선택", value=(min_date, max_date), min_value=min_date, max_value=max_date)

filtered = df[df["카테고리"].isin(selected_categories)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
    filtered = filtered[(filtered["날짜"].dt.date >= start) & (filtered["날짜"].dt.date <= end)]

if filtered.empty:
    st.warning("조건에 맞는 데이터가 없습니다. 카테고리/기간을 다시 선택해주세요.")
    st.stop()

cat_sum = filtered.groupby("카테고리")["지출"].sum().sort_values(ascending=False)
days = (filtered["날짜"].max() - filtered["날짜"].min()).days + 1
top_category = cat_sum.idxmax()

c1, c2, c3, c4 = st.columns(4)
c1.metric("총 지출", f"₩{filtered['지출'].sum():,.0f}")
c2.metric("일평균 지출", f"₩{filtered['지출'].sum() / days:,.0f}")
c3.metric("카테고리 수", f"{filtered['카테고리'].nunique()}개")
c4.metric("최고 지출 카테고리", top_category, f"₩{cat_sum.max():,.0f}")

st.divider()

tab_overview, tab_external, tab_detail = st.tabs(["📊 개요", "🌍 외부 지표", "🧾 상세"])

with tab_overview:
    left, right = st.columns(2)
    with left:
        st.subheader("카테고리별 지출")
        st.caption("막대를 클릭하면 우측 추이가 해당 카테고리로 필터링됩니다.")
        cat_click = alt.selection_point(fields=["카테고리"], on="click", empty=True, name="catClick")
        cat_bar = (
            alt.Chart(cat_sum.reset_index())
            .mark_bar()
            .encode(
                x=alt.X("카테고리:N", sort="-y"),
                y="지출:Q",
                color=alt.condition(cat_click, alt.value("#1E8E5A"), alt.value("#BFE6D2")),
                tooltip=["카테고리", "지출"],
            )
            .add_params(cat_click)
        )
        click_event = st.altair_chart(cat_bar, on_select="rerun", key="cat_bar")
    with right:
        clicked = [row["카테고리"] for row in click_event["selection"]["catClick"]]
        scope = filtered[filtered["카테고리"].isin(clicked)] if clicked else filtered
        st.subheader(f"월별 지출 추이 — {', '.join(clicked) if clicked else '전체 카테고리'}")
        monthly = scope.groupby(scope["날짜"].dt.to_period("M").astype(str))["지출"].sum()
        st.line_chart(monthly, color="#1E8E5A")

with tab_external:
    st.subheader("💱 USD/KRW 환율 — 결제일 기준")
    start_iso = filtered["날짜"].min().date().isoformat()
    end_iso = filtered["날짜"].max().date().isoformat()
    try:
        fx = fetch_usd_krw(start_iso, end_iso)
        # ponytail: 무료 API라 일별 종가만 제공, 시가=전일종가로 근사한 캔들 — 실제 OHLC 필요하면 유료 FX API로 교체
        fx["시가"] = fx["USD/KRW"].shift(1).fillna(fx["USD/KRW"])
        fx["종가"] = fx["USD/KRW"]
        fx["전일대비"] = fx["종가"] - fx["시가"]
        fx["상승"] = fx["종가"] >= fx["시가"]
        fx["날짜문자열"] = fx["날짜"].dt.strftime("%Y-%m-%d")

        overseas = filtered[filtered["카테고리"] == "해외"].sort_values("날짜")
        overseas_fx = pd.DataFrame()
        if not overseas.empty:
            overseas_fx = pd.merge_asof(
                overseas, fx[["날짜", "종가"]], on="날짜", direction="backward"
            ).rename(columns={"종가": "결제일환율"})
            overseas_fx["USD환산"] = (overseas_fx["지출"] / overseas_fx["결제일환율"]).round(2)
            overseas_fx["지출표시"] = [
                f"₩{won:,.0f} (${usd:,.2f})" for won, usd in zip(overseas_fx["지출"], overseas_fx["USD환산"])
            ]

        overseas_dates = set(overseas_fx["날짜"].dt.strftime("%Y-%m-%d")) if not overseas_fx.empty else set()
        fx["해외결제"] = fx["날짜문자열"].isin(overseas_dates)
        fx["테두리색"] = fx["해외결제"].map({True: "#FFA500", False: "rgba(0,0,0,0)"})
        fx["테두리두께"] = fx["해외결제"].map({True: 3.0, False: 0.0})

        latest_rate = fx["종가"].iloc[-1]
        fcol1, fcol2 = st.columns([1, 2])
        fcol1.metric(
            "최근 환율", f"₩{latest_rate:,.1f} / $1",
            f"총 지출 환산 ${filtered['지출'].sum() / latest_rate:,.0f}",
        )
        fcol1.metric(
            "해외 결제 건수", f"{len(overseas_fx)}건",
            f"USD 환산 합계 ${overseas_fx['USD환산'].sum():,.0f}" if not overseas_fx.empty else None,
        )

        click = alt.selection_point(fields=["날짜문자열"], on="click", empty=True, name="fxClick")
        candle = (
            alt.Chart(fx)
            .mark_bar(size=6)
            .encode(
                x=alt.X("날짜:T", title="날짜"),
                y=alt.Y("시가:Q", title="USD/KRW", scale=alt.Scale(zero=False)),
                y2="종가:Q",
                color=alt.Color(
                    "상승:N", scale=alt.Scale(domain=[True, False], range=["#D64545", "#2F80ED"]), legend=None
                ),
                stroke=alt.Color("테두리색:N", scale=None, legend=None),
                strokeWidth=alt.StrokeWidth("테두리두께:Q", legend=None),
                tooltip=["날짜문자열", "시가", "종가", "해외결제"],
            )
            .add_params(click)
        )

        with fcol2:
            event = st.altair_chart(candle, on_select="rerun", key="fx_candle", width="stretch")

        clicked = [row["날짜문자열"] for row in event["selection"]["fxClick"]]
        if clicked:
            day = clicked[0]
            row = fx[fx["날짜문자열"] == day].iloc[0]
            st.subheader(f"📅 {day} 환율 상세")
            dcol1, dcol2 = st.columns(2)
            dcol1.metric("종가", f"₩{row['종가']:,.2f}", f"전일대비 {row['전일대비']:+,.2f}")
            dcol2.metric("시가", f"₩{row['시가']:,.2f}")
            day_overseas = (
                overseas_fx[overseas_fx["날짜"].dt.strftime("%Y-%m-%d") == day]
                if not overseas_fx.empty else pd.DataFrame()
            )
            if not day_overseas.empty:
                st.dataframe(
                    day_overseas[["날짜", "지출표시", "결제일환율"]],
                    hide_index=True,
                    column_config={
                        "날짜": st.column_config.DatetimeColumn("결제 시각", format="YYYY-MM-DD HH:mm"),
                        "지출표시": st.column_config.TextColumn("지출액 (원/달러)"),
                        "결제일환율": st.column_config.NumberColumn("결제일환율", format="₩%.2f"),
                    },
                )
            else:
                st.caption("이 날짜에는 해외 결제 내역이 없습니다.")
        else:
            st.caption("차트의 막대를 클릭하면 해당 날짜의 환율 상세가 표시됩니다. 주황 테두리는 해외 결제일입니다.")

        if not overseas_fx.empty:
            st.divider()
            st.subheader("🧳 해외 결제 내역 — 결제일 환율 기준")
            st.dataframe(
                overseas_fx[["날짜", "지출표시", "결제일환율"]],
                hide_index=True,
                column_config={
                    "날짜": st.column_config.DatetimeColumn("결제 시각", format="YYYY-MM-DD HH:mm"),
                    "지출표시": st.column_config.TextColumn("지출액 (원/달러)"),
                    "결제일환율": st.column_config.NumberColumn("결제일환율", format="₩%.2f"),
                },
            )
    except requests.RequestException:
        st.warning("환율 정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")

with tab_detail:
    st.subheader("카테고리별 상세")
    detail = (
        filtered.groupby("카테고리")
        .agg(지출=("지출", "sum"), 건수=("지출", "count"))
        .reset_index()
    )
    detail["비중(%)"] = (detail["지출"] / detail["지출"].sum() * 100).round(1)
    detail = detail.sort_values("지출", ascending=False).reset_index(drop=True)

    st.dataframe(
        detail,
        hide_index=True,
        column_config={
            "지출": st.column_config.ProgressColumn(
                "지출", format="₩%d", min_value=0, max_value=int(detail["지출"].max())
            ),
            "비중(%)": st.column_config.ProgressColumn(
                "비중(%)", format="%.1f%%", min_value=0, max_value=100
            ),
        },
    )
