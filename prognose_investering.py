import json
import requests
import pandas as pd
import geopandas as gpd
import plotly.express as px

PERIOD = "4"  # planperiode 1 (2026-2030), 2 (2031-2035), 3 (2036-2040) of 4 (2041-2045)

SCALING = 50.0

TYPENAME = "waterschap_zuiveringseenheid"
WFS_DATA = "https://service.pdok.nl/rioned/waterschappen-waterketen-gwsw/wfs/v1_0"  # WFS from https://www.pdok.nl/ogc-webservices/-/article/waterschappen-waterketen-gwsw#d392de7088a2b1c9c19f304c5d6de465
PROG_DATA = "data/Overzicht langjarige investeringsplanning.xlsx"

thema_color = {
    "100% circulair": "rgb(66, 216, 238)",
    "Digitale transformatie": "rgb(223, 146, 5)",
    "Klimaatneutraal": "rgb(95, 201, 165)",
    "Klimaatpositief": "rgb(95, 201, 165)",
    "Renovatie en vervanging": "rgb(213, 37, 45)",
    "Slimme keten": "rgb(223, 146, 5)",
    "Water op maat": "rgb(0, 50, 212)",
    "Wendbare keten": "rgb(169, 202, 1)",
    "KN & CE": "rgb(95, 201, 165)",
}

rwzi_map = {
    "ATN": "Aalten",
    "DPL": "Dinxperlo",
    "ETN": "Etten",
    "HLO": "Haarlo",
    "HTN": "Holten",
    "LTV": "Lichtenvoorde",
    "NGF": "Nieuwgraaf",
    "OLB": "Olburgen",
    "RLO": "Ruurlo",
    "VSV": "Varsseveld",
    "WHL": "Wehl",
    "WTW": "Winterswijk",
    "ZPN": "Zutphen",
}

# request data from prognoses
df_prog = pd.read_excel(PROG_DATA, skiprows=2)

# rename
df_prog = df_prog.rename(
    columns={
        "AWK 2050 thema/Thema BTP": "thema",
        "Unnamed: 13": "period_1",
        "Unnamed: 19": "period_2",
        "36-40": "period_3",
        "41-45": "period_4",
        "RWZI": "rwzi",
    }
)

# ignore every row after "Totalen"
idx = df_prog[df_prog.apply(lambda r: r.astype(str).str.contains("Totalen", case=False)).any(axis=1)].index[0]
df_prog = df_prog.iloc[:idx].copy()

# remove empty rows
df_prog = df_prog[(~df_prog["rwzi"].isna() & ~df_prog["thema"].isna())].reset_index().copy()
df_prog = df_prog.fillna(0)

# set 0 for empty period numbers
df_prog = df_prog[
    [
        "rwzi",
        "thema",
        "period_1",
        "period_2",
        "period_3",
        "period_4",
    ]
].copy()

# rename abbriviations to full rwzi name and set all incorrectly named to NaN
df_prog["rwzi"] = df_prog["rwzi"].map(rwzi_map)

# devide all NaN RWZI lineair over the 13 RWZI's (stolen from chatGPT)
all_rwzi = list(rwzi_map.values())
period_cols = [c for c in df_prog.columns if c.startswith("period_")]
mask_all = df_prog["rwzi"].isna()
df_all = df_prog.loc[mask_all].copy()
df_all[period_cols] = round(df_all[period_cols] / len(all_rwzi), 1)
df_all["rwzi"] = [all_rwzi] * len(df_all)
df_all = df_all.explode("rwzi", ignore_index=True)
df_rest = df_prog.loc[~mask_all].copy()
df_out = pd.concat([df_rest, df_all], ignore_index=True)
df_prog = df_out.copy()

# strip spaties op einde van themanaam
df_prog["thema"] = df_prog["thema"].str.strip()

# sum numbers per thema and rwzi en zet alle negatieve waardes op 0 en schaal door te delen door 1000
df_prog = df_prog.groupby(["thema", "rwzi"], as_index=False).sum()
df_prog[period_cols] = df_prog[period_cols].clip(lower=0) / SCALING

# request data from WFS, explode multipoints, filter on Rijn en IJssel (7) and set rwzi
params = {
    "service": "WFS",
    "request": "GetFeature",
    "version": "2.0.0",
    "typenames": TYPENAME,
    "outputFormat": "application/json",
    "srsName": "EPSG:4326",
}
r = requests.get(WFS_DATA, params=params, timeout=60)
r.raise_for_status()

gdf_raw = gpd.GeoDataFrame.from_features(r.json()["features"], crs="EPSG:4326")

gdf = gdf_raw.explode(ignore_index=True)

if TYPENAME == "waterschap_rwzi":
    gdf = gdf[gdf.geometry.type == "Point"].copy()

gdf["filter_code"] = gdf["naam"].str.extract(r"WBHCODE\.(\d+)", expand=False).astype("Int64")

gdf = gdf[gdf["filter_code"] == 7].copy()
gdf.drop(gdf.index[10], inplace=True)  # haal extra gebiedje Zutphen weg (foutje in dataset?)

gdf["rwzi"] = gdf["naam"].str.replace(r"^\([^)]*\)\s*", "", regex=True)

# merge prognoses
gdf = gdf.merge(df_prog, on="rwzi", how="left")

gdf = gdf.to_crs(epsg=4326)
geojson = json.loads(gdf.to_json())

# make color zuiveringsgebieden
fig = px.choropleth_map(
    gdf,
    geojson=geojson,
    locations=gdf.index,
    color_discrete_sequence=["rgb(230, 246, 216)"],
    custom_data=[
        gdf["rwzi"],
    ],
    map_style="carto-positron",
    center={"lat": 52.07, "lon": 6.37},
    zoom=9.6,
)

fig.add_scattermap(
    lat=gdf.geometry.representative_point().y,
    lon=gdf.geometry.representative_point().x,
    mode="markers+text",
    marker=dict(size=120, color="white"),
    text=gdf["rwzi"],
    textposition="top center",
    textfont=dict(size=12, color="black"),
    showlegend=False,
)

# voeg per thema een bolletje toe
themas = list(gdf["thema"].dropna().unique())

thema_shift_x = {
    "100% circulair": -1,
    "Digitale transformatie": 1,
    "Klimaatneutraal": 0,
    "Klimaatpositief": -1,
    "Renovatie en vervanging": 0,
    "Slimme keten": 1,
    "Water op maat": 1,
    "Wendbare keten": -1,
    "KN & CE": 0,
}
thema_shift_y = {
    "100% circulair": 0,
    "Digitale transformatie": -1,
    "Klimaatneutraal": -1,
    "Klimaatpositief": 1,
    "Renovatie en vervanging": 0,
    "Slimme keten": 1,
    "Water op maat": 0,
    "Wendbare keten": -1,
    "KN & CE": 1,
}
for t in themas:

    sub = gdf[gdf["thema"] == t]
    rp = sub.geometry.representative_point()

    fig.add_scattermap(
        lat=rp.y + thema_shift_y[t] / SCALING,
        lon=rp.x + thema_shift_x[t] / (SCALING - 10.0),  # visueel meer aantrekkelijk met text erbij
        mode="markers",
        name=t,
        marker=dict(
            size=sub["period_" + PERIOD],
            color=thema_color[t],
            sizemode="area",
        ),
        showlegend=True,
    )

fig.update_traces(
    selector=dict(type="scattermap"),
    below="",
)

fig.update_traces(
    selector=dict(type="choroplethmap"),
    showlegend=False,
)

fig.update_traces(
    hoverinfo="skip",
    hovertemplate=None,
)

fig.update_layout(
    margin=dict(l=0, r=0, t=0, b=0),
    legend_title_text="Thema",
    legend=dict(
        font=dict(size=18),
        orientation="v",
        x=0.02,
        y=0.98,
        xanchor="left",
        yanchor="top",
    ),
)

fig.show()
