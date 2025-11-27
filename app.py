import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

# =======================
# データ読み込み
# =======================

@st.cache_data
def load_data():
    df_hosp = pd.read_csv("data/flu_with_address.csv", encoding="utf-8-sig")
    df_scene = pd.read_csv("data/scene_with_month.csv", encoding="utf-8-sig")

    # 座標を数値化
    for df in [df_hosp, df_scene]:
        df["fX"] = pd.to_numeric(df["fX"], errors="coerce")
        df["fY"] = pd.to_numeric(df["fY"], errors="coerce")
        df.dropna(subset=["fX", "fY"], inplace=True)

    return df_hosp, df_scene


df_hosp, df_scene = load_data()

# =======================
# サイドバー UI
# =======================

st.sidebar.title("フィルタ")

# 月の選択肢
month_list = sorted(df_scene["month"].dropna().unique())
month_options = ["全期間"] + month_list

selected_month = st.sidebar.selectbox(
    "表示する月",
    month_options,
    index=0
)

# =======================
# データのフィルタリング
# =======================

if selected_month == "全期間":
    df_scene_filt = df_scene.copy()
else:
    df_scene_filt = df_scene[df_scene["month"] == selected_month].copy()

# 住所ごとに集計（全ケース＋各症状）
group_cols = ["addr_csis", "LocName", "fY", "fX"]
agg_dict = {
    "case_id": "count",
    "incident_condition_heatstroke_flag": "sum",
    "incident_condition_flu_flag": "sum",
    "incident_condition_snow_flag": "sum",
    "incident_condition_covid19_suspect_flag": "sum",
}

df_scene_agg = (
    df_scene_filt
    .groupby(group_cols, dropna=True)
    .agg(agg_dict)
    .reset_index()
    .rename(columns={"case_id": "total_cases"})
)

# =======================
# マップ作成
# =======================

st.title("救急現場と病院のマップ")
st.write(f"表示期間：**{selected_month}**")

# 中心は病院の平均位置
center_lat = df_hosp["fY"].mean()
center_lng = df_hosp["fX"].mean()

m = folium.Map(location=[center_lat, center_lng], zoom_start=12, tiles="OpenStreetMap")

# -------- 病院マーカー（青ピン） --------
for _, row in df_hosp.iterrows():
    lat, lng = row["fY"], row["fX"]
    name = row.get("hospital_name", "")
    addr = row.get("addr_csis", row.get("address", ""))

    popup_html = f"{name}<br>{addr}"

    folium.Marker(
        [lat, lng],
        popup=popup_html,
        icon=folium.Icon(color="blue", icon="hospital-o", prefix="fa")
    ).add_to(m)

# -------- 現場マーカー（住所ごと） --------
for _, row in df_scene_agg.iterrows():
    lat, lng = row["fY"], row["fX"]
    addr = row["addr_csis"]
    popup_html = (
        f"住所: {addr}<br>"
        f"全ケース: {row['total_cases']}件<br>"
        f"熱中症疑い: {row['incident_condition_heatstroke_flag']}件<br>"
        f"インフル疑い: {row['incident_condition_flu_flag']}件<br>"
        f"雪関連疑い: {row['incident_condition_snow_flag']}件<br>"
        f"コロナ疑い: {row['incident_condition_covid19_suspect_flag']}件"
    )

    folium.CircleMarker(
        location=[lat, lng],
        radius=5,
        color="orange",
        fill=True,
        fill_opacity=0.5,
        popup=popup_html,
    ).add_to(m)

# 地図を Streamlit に表示
st_folium(m, width=900, height=600)
