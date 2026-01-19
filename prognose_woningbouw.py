import json
import requests
import pandas as pd
import geopandas as gpd
import plotly.express as px

YEAR = "2050"  # 2035 or 2050

TYPENAME = "waterschap_zuiveringseenheid"
WFS_DATA = "https://service.pdok.nl/rioned/waterschappen-waterketen-gwsw/wfs/v1_0"  # WFS from https://www.pdok.nl/ogc-webservices/-/article/waterschappen-waterketen-gwsw#d392de7088a2b1c9c19f304c5d6de465
PROG_DATA = "data/Prognoses obv HWH.xlsx"
BELASTING_DATA = "data/overzicht belasting RWZI.xlsx"

translate_map = {
    "groen": "green",
    "geel": "yellow",
    "rood": "red",
}
color_map = {
    "green": "green",
    "yellow": "rgb(241, 220, 74)",
    "red": "rgb(213, 37, 45)",
}
legend_map = {
    "green": "Voldoende",
    "yellow": "Beperkt",
    "red": "Weinig",
}

# request data from prognoses, rename rwzi, set toename
df_prog = pd.read_excel(PROG_DATA, skiprows=4)

df_prog["toename_2035"] = round(
    (df_prog["prognose 2035"] - df_prog["inwoners 2022"]) / df_prog["inwoners 2022"] * 100, 1
)
df_prog["toename_2050"] = round(
    (df_prog["prognose 2050"] - df_prog["inwoners 2022"]) / df_prog["inwoners 2022"] * 100, 1
)

# request data from belasting, rename rwzi, translate colors:
df_belasting = pd.read_excel(BELASTING_DATA, skiprows=1)
df_belasting["rwzi"] = df_belasting["RWZI"]
df_belasting["Ruimte"] = df_belasting["RUIMTE"].map(translate_map)

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

# merge prognoses en belasting in
gdf = gdf.merge(df_prog, on="rwzi", how="left")
gdf = gdf.merge(df_belasting, on="rwzi", how="left")

gdf = gdf.to_crs(epsg=4326)
geojson = json.loads(gdf.to_json())

# make color zuiveringsgebieden
fig = px.choropleth_map(
    gdf,
    geojson=geojson,
    locations=gdf.index,
    color="Ruimte",
    color_discrete_map=color_map,
    custom_data=[
        gdf["rwzi"],
        gdf["toename_2035"],
        gdf["toename_2050"],
    ],
    map_style="carto-positron",
    center={"lat": 52.07, "lon": 6.37},
    zoom=9.6,
)

for tr in fig.data:
    if tr.name in legend_map:
        tr.name = legend_map[tr.name]

# add positive, negative and neutral labels
pos = gdf[gdf["toename_" + YEAR] > 0]
neg = gdf[gdf["toename_" + YEAR] < 0]
zer = gdf[(gdf["toename_" + YEAR] == 0) | (gdf["toename_" + YEAR].isna())]

fig.add_scattermap(
    lat=gdf.geometry.representative_point().y,
    lon=gdf.geometry.representative_point().x,
    mode="markers",
    marker=dict(size=84, color="white"),
    showlegend=False,
)
fig.add_scattermap(
    lat=pos.geometry.representative_point().y,
    lon=pos.geometry.representative_point().x,
    mode="text",
    text=(pos["rwzi"] + "<br>" + pos["toename_" + YEAR].map(lambda v: f"{v:+.1f}%")),
    textfont=dict(size=12, color=color_map["green"]),
    showlegend=False,
)
fig.add_scattermap(
    lat=neg.geometry.representative_point().y,
    lon=neg.geometry.representative_point().x,
    mode="text",
    text=(neg["rwzi"] + "<br>" + neg["toename_" + YEAR].map(lambda v: f"{v:+.1f}%")),
    textfont=dict(size=12, color=color_map["red"]),
    showlegend=False,
)
fig.add_scattermap(
    lat=zer.geometry.representative_point().y,
    lon=zer.geometry.representative_point().x,
    mode="text",
    text=zer["rwzi"] + "<br>" "0.0%",
    textfont=dict(size=12, color="black"),
    showlegend=False,
)

fig.update_traces(
    selector=dict(type="scattermap"),
    below="",
)

fig.update_traces(
    hoverinfo="skip",
    hovertemplate=None,
)

fig.update_layout(
    margin=dict(l=0, r=0, t=0, b=0),
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
