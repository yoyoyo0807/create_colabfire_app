import pandas as pd
import folium
from folium.plugins import MarkerCluster
import streamlit as st
from streamlit_folium import st_folium

HOSP_PATH  = "flu_with_address.csv"
EMG_PATH   = "emergency_data.xlsx"
SCENE_PATH = "scene_with_geo_and_conditions.csv"


# ========= データ読み込み（キャッシュ付き） =========
@st.cache_data
def load_data():
    # --- 病院 ---
    df_hosp = pd.read_csv(HOSP_PATH, encoding="utf-8-sig")
    df_hosp["fX"] = pd.to_numeric(df_hosp["fX"], errors="coerce")
    df_hosp["fY"] = pd.to_numeric(df_hosp["fY"], errors="coerce")
    df_hosp = df_hosp.dropna(subset=["fX", "fY"])

    # 総問い合わせ
    if "inquiry_total" in df_hosp.columns:
        df_hosp["total_inquiry"] = df_hosp["inquiry_total"]
    else:
        cols_exist = [c for c in ["heatstroke_inquiry", "flu_inquiry",
                                  "snow_inquiry", "covid_inquiry"]
                      if c in df_hosp.columns]
        df_hosp["total_inquiry"] = df_hosp[cols_exist].sum(axis=1)

    # 症状ごとの問い合わせあり病院
    def has_col(df, col):
        return col in df.columns

    df_hosp_heat  = df_hosp[df_hosp["heatstroke_inquiry"] > 0] if has_col(df_hosp, "heatstroke_inquiry") else df_hosp.iloc[0:0]
    df_hosp_flu   = df_hosp[df_hosp["flu_inquiry"]        > 0] if has_col(df_hosp, "flu_inquiry")        else df_hosp.iloc[0:0]
    df_hosp_snow  = df_hosp[df_hosp["snow_inquiry"]       > 0] if has_col(df_hosp, "snow_inquiry")       else df_hosp.iloc[0:0]
    df_hosp_covid = df_hosp[df_hosp["covid_inquiry"]      > 0] if has_col(df_hosp, "covid_inquiry")      else df_hosp.iloc[0:0]

    # --- emergency_data（call_time → month） ---
    df_emg = pd.read_excel(EMG_PATH)
    df_emg["call_time"] = pd.to_datetime(df_emg["call_time"], errors="coerce")
    df_emg["month"] = df_emg["call_time"].dt.to_period("M").astype(str)

    # --- 現場 + フラグ + 座標 ---
    df_scene = pd.read_csv(SCENE_PATH, encoding="utf-8-sig")
    df_scene = df_scene.merge(
        df_emg[["case_id", "month"]],
        on="case_id",
        how="left"
    )
    df_scene["fX"] = pd.to_numeric(df_scene["fX"], errors="coerce")
    df_scene["fY"] = pd.to_numeric(df_scene["fY"], errors="coerce")
    df_scene = df_scene.dropna(subset=["fX", "fY"])

    return df_hosp, df_hosp_heat, df_hosp_flu, df_hosp_snow, df_hosp_covid, df_scene


# ========= 地図を作る関数（month だけ切り替え） =========
def build_map(df_hosp, df_hosp_heat, df_hosp_flu, df_hosp_snow, df_hosp_covid,
              df_scene, selected_month):

    # --- 月フィルタ（「全期間」はそのまま） ---
    if selected_month != "全期間":
        df_scene = df_scene[df_scene["month"] == selected_month]

    # --- 現場を住所ごとに集計 ---
    group_cols = ["addr_csis", "LocName", "fY", "fX"]
    agg_dict = {
        "case_id": "count",
        "incident_condition_heatstroke_flag": "sum",
        "incident_condition_flu_flag": "sum",
        "incident_condition_snow_flag": "sum",
        "incident_condition_covid19_suspect_flag": "sum",
    }

    df_scene_agg = (
        df_scene
        .groupby(group_cols, dropna=True)
        .agg(agg_dict)
        .reset_index()
        .rename(columns={"case_id": "total_cases"})
    )

    df_scene_heat  = df_scene_agg[df_scene_agg["incident_condition_heatstroke_flag"] > 0]
    df_scene_flu   = df_scene_agg[df_scene_agg["incident_condition_flu_flag"] > 0]
    df_scene_snow  = df_scene_agg[df_scene_agg["incident_condition_snow_flag"] > 0]
    df_scene_covid = df_scene_agg[df_scene_agg["incident_condition_covid19_suspect_flag"] > 0]

    # --- 地図ベース ---
    center_lat = df_hosp["fY"].mean()
    center_lng = df_hosp["fX"].mean()
    m = folium.Map(location=[center_lat, center_lng], zoom_start=12, tiles="OpenStreetMap")

    # ===== 病院レイヤー（ピン＋問い合わせ情報） =====
    fg_all_hosp   = folium.FeatureGroup(name="全ての病院（青）")
    fg_heat_hosp  = folium.FeatureGroup(name="熱中症問い合わせあり病院")
    fg_flu_hosp   = folium.FeatureGroup(name="インフル問い合わせあり病院")
    fg_snow_hosp  = folium.FeatureGroup(name="雪関連問い合わせあり病院")
    fg_covid_hosp = folium.FeatureGroup(name="コロナ問い合わせあり病院")

    def build_hosp_popup(row):
        name = row.get("hospital_name", "")
        addr = row.get("addr_csis", row.get("address", ""))
        total = int(row.get("total_inquiry", 0))

        h_inq = int(row.get("heatstroke_inquiry", 0))
        f_inq = int(row.get("flu_inquiry", 0))
        s_inq = int(row.get("snow_inquiry", 0))
        c_inq = int(row.get("covid_inquiry", 0))

        html = f"""
        <b>{name}</b><br>
        住所: {addr}<br>
        <b>総問い合わせ</b>: {total} 件<br>
        ┗ 熱中症: {h_inq} 件<br>
        ┗ インフル: {f_inq} 件<br>
        ┗ 雪関連: {s_inq} 件<br>
        ┗ コロナ: {c_inq} 件
        """
        return html

    def add_hosp_markers(df, fg, mode=None):
        for _, row in df.iterrows():
            lat, lng = row["fY"], row["fX"]
            if pd.isna(lat) or pd.isna(lng):
                continue

            color = "blue"
            if mode is None:
                total = int(row.get("total_inquiry", 0))
                if total >= 100:
                    color = "darkblue"
            else:
                col_map = {
                    "heat": "heatstroke_inquiry",
                    "flu":  "flu_inquiry",
                    "snow": "snow_inquiry",
                    "covid": "covid_inquiry",
                }
                col = col_map.get(mode)
                if col and col in row and int(row[col]) >= 10:
                    color = "darkblue"

            popup_html = build_hosp_popup(row)
            folium.Marker(
                [lat, lng],
                popup=popup_html,
                icon=folium.Icon(color=color, icon="hospital-o", prefix="fa")
            ).add_to(fg)

    add_hosp_markers(df_hosp,       fg_all_hosp,   mode=None)
    add_hosp_markers(df_hosp_heat,  fg_heat_hosp,  mode="heat")
    add_hosp_markers(df_hosp_flu,   fg_flu_hosp,   mode="flu")
    add_hosp_markers(df_hosp_snow,  fg_snow_hosp,  mode="snow")
    add_hosp_markers(df_hosp_covid, fg_covid_hosp, mode="covid")

    fg_all_hosp.add_to(m)
    fg_heat_hosp.add_to(m)
    fg_flu_hosp.add_to(m)
    fg_snow_hosp.add_to(m)
    fg_covid_hosp.add_to(m)

    # ===== 現場レイヤー（クラスタ） =====

    ICON_CREATE_FUNCTION = """
    function(cluster) {
        var markers = cluster.getAllChildMarkers();
        var sum = 0;
        for (var i = 0; i < markers.length; i++) {
            if (markers[i].options && markers[i].options.cases) {
                sum += markers[i].options.cases;
            } else {
                sum += 1;
            }
        }
        return new L.DivIcon({
            html: '<div><span>' + sum + '</span></div>',
            className: 'marker-cluster marker-cluster-small',
            iconSize: new L.Point(40, 40)
        });
    }
    """

    cluster_scene_all   = MarkerCluster(
        name="全ケースの現場（住所ごと）",
        icon_create_function=ICON_CREATE_FUNCTION
    )
    cluster_scene_heat  = MarkerCluster(
        name="熱中症疑い現場",
        icon_create_function=ICON_CREATE_FUNCTION
    )
    cluster_scene_flu   = MarkerCluster(
        name="インフル疑い現場",
        icon_create_function=ICON_CREATE_FUNCTION
    )
    cluster_scene_snow  = MarkerCluster(
        name="雪関連疑い現場",
        icon_create_function=ICON_CREATE_FUNCTION
    )
    cluster_scene_covid = MarkerCluster(
        name="コロナ疑い現場",
        icon_create_function=ICON_CREATE_FUNCTION
    )

    COLOR_ALL   = "orange"
    COLOR_HEAT  = "red"
    COLOR_FLU   = "green"
    COLOR_SNOW  = "deepskyblue"
    COLOR_COVID = "purple"

    # 全ケース
    for _, row in df_scene_agg.iterrows():
        lat, lng = row["fY"], row["fX"]
        if pd.isna(lat) or pd.isna(lng):
            continue
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
            color=COLOR_ALL,
            fill=True,
            fill_opacity=0.5,
            popup=popup_html,
            cases=int(row["total_cases"])
        ).add_to(cluster_scene_all)

    # 症状別
    def add_scene_condition_markers(df_sub, cluster, color, cond_col, label):
        for _, row in df_sub.iterrows():
            lat, lng = row["fY"], row["fX"]
            if pd.isna(lat) or pd.isna(lng):
                continue
            addr = row["addr_csis"]
            count = int(row[cond_col])
            popup_html = f"住所: {addr}<br>{label}: {count}件"
            folium.CircleMarker(
                location=[lat, lng],
                radius=6,
                color=color,
                fill=True,
                fill_opacity=0.6,
                popup=popup_html,
                cases=count
            ).add_to(cluster)

    add_scene_condition_markers(
        df_scene_heat,  cluster_scene_heat,
        COLOR_HEAT, "incident_condition_heatstroke_flag", "熱中症疑い"
    )
    add_scene_condition_markers(
        df_scene_flu,   cluster_scene_flu,
        COLOR_FLU, "incident_condition_flu_flag", "インフル疑い"
    )
    add_scene_condition_markers(
        df_scene_snow,  cluster_scene_snow,
        COLOR_SNOW, "incident_condition_snow_flag", "雪関連疑い"
    )
    add_scene_condition_markers(
        df_scene_covid, cluster_scene_covid,
        COLOR_COVID, "incident_condition_covid19_suspect_flag", "コロナ疑い"
    )

    cluster_scene_all.add_to(m)
    cluster_scene_heat.add_to(m)
    cluster_scene_flu.add_to(m)
    cluster_scene_snow.add_to(m)
    cluster_scene_covid.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


# ========= Streamlit 本体 =========
def main():
    st.title("救急現場・病院マップ（まずは月切り替え版）")

    (df_hosp,
     df_hosp_heat,
     df_hosp_flu,
     df_hosp_snow,
     df_hosp_covid,
     df_scene) = load_data()

    # サイドバー：月選択
    st.sidebar.header("フィルタ")
    month_options = ["全期間"] + sorted(df_scene["month"].dropna().unique().tolist())
    selected_month = st.sidebar.selectbox("月を選択", month_options)

    st.write(f"表示中の月: **{selected_month}**")

    # 地図生成
    m = build_map(df_hosp, df_hosp_heat, df_hosp_flu, df_hosp_snow, df_hosp_covid,
                  df_scene, selected_month)

    # 表示
    st_folium(m, width=1100, height=700)


if __name__ == "__main__":
    main()
