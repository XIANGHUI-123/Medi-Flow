"""
heatmap_service.py  ─  Medi‑Flow Orchestrator  ─  Consultation‑Based Pandemic Heatmap

Modular AI service that powers the consultation‑linked pandemic heatmap:
  1. query_consultation_data()       — structure raw consultation/visit data
  2. geocode_address()               — convert addresses to lat/lng
  3. assign_severity_weights()       — map severity labels → numeric weights
  4. predict_hotspots()              — DBSCAN clustering + risk scoring
  5. detect_anomalies()              — 7‑day spike detection
  6. analyse_trends()                — daily case & severity trends over time
  7. generate_weighted_heatmap()     — Folium heatmap with severity weights
  8. recommend_medicine_allocation() — estimate resource needs per cluster
  9. generate_ai_pandemic_heatmap()  — end‑to‑end orchestrator
"""

import logging
from datetime import date, timedelta

import folium
import numpy as np
import pandas as pd
from folium.plugins import HeatMap
from sklearn.cluster import DBSCAN

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════
#  Severity weights — used for heatmap intensity + resource calc
# ═════════════════════════════════════════════════════════════
SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3}

# ═════════════════════════════════════════════════════════════
#  Malaysia city/area → coordinate lookup
#  (Avoids external geocoding APIs; covers common Malaysian cities)
# ═════════════════════════════════════════════════════════════
_GEOCODE_LOOKUP: dict[str, tuple[float, float]] = {
    # Kuala Lumpur & Selangor
    "kuala lumpur":     (3.1390, 101.6869),
    "kl":               (3.1390, 101.6869),
    "petaling jaya":    (3.1073, 101.6067),
    "shah alam":        (3.0733, 101.5185),
    "subang jaya":      (3.0565, 101.5851),
    "ampang":           (3.1500, 101.7667),
    "cheras":           (3.1073, 101.7328),
    "puchong":          (3.0443, 101.6171),
    "klang":            (3.0449, 101.4455),
    "cyberjaya":        (2.9213, 101.6559),
    "putrajaya":        (2.9264, 101.6964),
    "kajang":           (2.9927, 101.7909),
    "bangi":            (2.9465, 101.7753),
    "rawang":           (3.3213, 101.5767),
    "gombak":           (3.2530, 101.7106),
    "serdang":          (3.0236, 101.7064),
    "damansara":        (3.1350, 101.6150),
    "kepong":           (3.2092, 101.6340),
    "setapak":          (3.1878, 101.7112),
    "bangsar":          (3.1290, 101.6712),
    "mont kiara":       (3.1710, 101.6510),
    "bukit bintang":    (3.1466, 101.7108),
    "sentul":           (3.1814, 101.6916),
    "wangsa maju":      (3.1972, 101.7335),
    "sri petaling":     (3.0769, 101.6888),
    # Penang
    "penang":           (5.4164, 100.3327),
    "george town":      (5.4164, 100.3327),
    "butterworth":      (5.3991, 100.3638),
    "bayan lepas":      (5.3027, 100.2689),
    "bukit mertajam":   (5.3631, 100.4656),
    # Johor
    "johor bahru":      (1.4927, 103.7414),
    "johor":            (1.4927, 103.7414),
    "iskandar puteri":  (1.4261, 103.6536),
    "pasir gudang":     (1.4726, 103.8896),
    "kulai":            (1.6559, 103.5982),
    # Perak
    "ipoh":             (4.5975, 101.0901),
    "taiping":          (4.8510, 100.7440),
    # Pahang
    "kuantan":          (3.8077, 103.3260),
    "temerloh":         (3.4504, 102.4174),
    # Kelantan
    "kota bharu":       (6.1254, 102.2381),
    # Terengganu
    "kuala terengganu": (5.3117, 103.1324),
    # Negeri Sembilan
    "seremban":         (2.7259, 101.9424),
    # Melaka
    "melaka":           (2.1896, 102.2501),
    "malacca":          (2.1896, 102.2501),
    # Kedah
    "alor setar":       (6.1248, 100.3677),
    # Perlis
    "kangar":           (6.4414, 100.1986),
    # Sabah
    "kota kinabalu":    (5.9804, 116.0735),
    # Sarawak
    "kuching":          (1.5497, 110.3634),
}

# ── Malaysian postcode → city fallback ───────────────────────
_POSTCODE_LOOKUP: dict[str, str] = {
    "50": "kuala lumpur", "51": "kuala lumpur", "52": "kuala lumpur",
    "53": "kuala lumpur", "54": "kuala lumpur", "55": "kuala lumpur",
    "56": "kuala lumpur", "57": "kuala lumpur", "58": "kuala lumpur",
    "59": "kuala lumpur", "60": "kuala lumpur",
    "40": "shah alam", "41": "klang", "42": "klang",
    "43": "kajang", "44": "kuala selangor",
    "45": "kuala selangor", "46": "petaling jaya", "47": "petaling jaya",
    "48": "rawang", "61": "cyberjaya", "62": "putrajaya", "63": "cyberjaya",
    "68": "ampang", "69": "gombak",
    "10": "george town", "11": "george town", "12": "butterworth",
    "13": "butterworth", "14": "bukit mertajam",
    "30": "ipoh", "31": "ipoh", "32": "ipoh", "33": "ipoh", "34": "taiping",
    "35": "taiping",
    "70": "seremban", "71": "seremban", "72": "seremban",
    "73": "melaka", "75": "melaka", "76": "melaka", "77": "melaka",
    "78": "melaka",
    "80": "johor bahru", "81": "johor bahru", "82": "johor bahru",
    "83": "johor bahru", "84": "pasir gudang", "85": "kulai", "86": "kulai",
    "15": "kota bharu", "16": "kota bharu", "17": "kota bharu",
    "20": "kuala terengganu", "21": "kuala terengganu",
    "22": "kuala terengganu",
    "25": "kuantan", "26": "kuantan", "27": "kuantan", "28": "temerloh",
    "05": "alor setar", "06": "alor setar", "08": "alor setar",
    "01": "kangar", "02": "kangar",
    "88": "kota kinabalu", "89": "kota kinabalu",
    "93": "kuching", "94": "kuching",
}

# Small random offset to prevent exact overlap on the map
_RNG = np.random.default_rng(42)

# Default fallback — central Kuala Lumpur
_DEFAULT_COORDS = (3.1390, 101.6869)


def geocode_address(address: str) -> tuple[float, float] | None:
    """
    Convert a Malaysian address string to (latitude, longitude).

    Matching strategy (in order):
      1. Keyword match against known city/area names
      2. Postcode prefix match (2-digit prefix → city)
      3. Fallback to Kuala Lumpur center

    Adds a small jitter so multiple patients at the same city don't stack.
    """
    if not address:
        return None

    text = address.lower().strip()

    # 1. Try keyword match — most specific (longest) key first
    for key in sorted(_GEOCODE_LOOKUP, key=len, reverse=True):
        if key in text:
            lat, lng = _GEOCODE_LOOKUP[key]
            jitter_lat = _RNG.uniform(-0.005, 0.005)
            jitter_lng = _RNG.uniform(-0.005, 0.005)
            return (lat + jitter_lat, lng + jitter_lng)

    # 2. Try postcode match — extract 5-digit postcode, use first 2 digits
    import re
    postcode_match = re.search(r"\b(\d{5})\b", text)
    if postcode_match:
        prefix = postcode_match.group(1)[:2]
        city_key = _POSTCODE_LOOKUP.get(prefix)
        if city_key and city_key in _GEOCODE_LOOKUP:
            lat, lng = _GEOCODE_LOOKUP[city_key]
            jitter_lat = _RNG.uniform(-0.005, 0.005)
            jitter_lng = _RNG.uniform(-0.005, 0.005)
            return (lat + jitter_lat, lng + jitter_lng)

    # 3. Fallback — default to KL center so the point still appears on map
    lat, lng = _DEFAULT_COORDS
    jitter_lat = _RNG.uniform(-0.01, 0.01)
    jitter_lng = _RNG.uniform(-0.01, 0.01)
    return (lat + jitter_lat, lng + jitter_lng)


# ═════════════════════════════════════════════════════════════
#  Query & structure consultation data
# ═════════════════════════════════════════════════════════════

def query_consultation_data(visits: list[dict]) -> pd.DataFrame:
    """
    Convert raw visit/consultation dicts into a clean DataFrame
    ready for geocoding, weighting, and analysis.

    Columns produced: patient_id, patient_name, home_address,
    diagnosis, severity, visit_date, notes.
    """
    if not visits:
        return pd.DataFrame()

    df = pd.DataFrame(visits)
    # Normalise column names
    col_map = {
        "patient_id": "patient_id",
        "patient_name": "patient_name",
        "home_address": "home_address",
        "diagnosis": "diagnosis",
        "severity": "severity",
        "visit_date": "visit_date",
        "notes": "notes",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # Parse visit_date if string
    if "visit_date" in df.columns and df["visit_date"].dtype == object:
        df["visit_date"] = pd.to_datetime(df["visit_date"], errors="coerce").dt.date

    # Fill missing
    df["diagnosis"] = df.get("diagnosis", pd.Series(["Unknown"] * len(df))).fillna("Unknown")
    df["severity"] = df.get("severity", pd.Series(["low"] * len(df))).fillna("low")

    return df


# ═════════════════════════════════════════════════════════════
#  Assign severity weights
# ═════════════════════════════════════════════════════════════

def assign_severity_weights(df: pd.DataFrame) -> pd.DataFrame:
    """
    Map severity labels (low / medium / high) to numeric weights.

    Adds a 'weight' column:  low → 1, medium → 2, high → 3.
    """
    df = df.copy()
    df["weight"] = df["severity"].map(SEVERITY_WEIGHT).fillna(1).astype(int)
    return df


# ═════════════════════════════════════════════════════════════
#  Predict outbreak hotspots using DBSCAN clustering
# ═════════════════════════════════════════════════════════════

def predict_hotspots(df: pd.DataFrame) -> pd.DataFrame:
    """
    Use DBSCAN spatial clustering to identify outbreak hotspots.

    Each cluster is scored by total severity weight and case count.
    A 'predicted_risk' column is added:
      - HIGH   → cluster weighted score ≥ 10
      - MEDIUM → cluster weighted score ≥ 5
      - LOW    → everything else

    Also marks anomalies (noise points from DBSCAN) for attention.
    """
    if df.empty or "lat" not in df.columns:
        return df

    coords = df[["lat", "lng"]].values

    # DBSCAN with eps ≈ 1 km (0.01 degrees), min 2 samples to form a cluster
    clustering = DBSCAN(eps=0.01, min_samples=2, metric="euclidean")
    df = df.copy()
    df["cluster"] = clustering.fit_predict(coords)

    # Calculate cluster-level severity score
    cluster_scores = (
        df[df["cluster"] >= 0]
        .groupby("cluster")["weight"]
        .sum()
        .to_dict()
    )

    def _risk(row):
        c = row["cluster"]
        if c < 0:
            return "ANOMALY"  # Noise / isolated point
        score = cluster_scores.get(c, 0)
        if score >= 10:
            return "HIGH"
        if score >= 5:
            return "MEDIUM"
        return "LOW"

    df["predicted_risk"] = df.apply(_risk, axis=1)
    return df


# ═════════════════════════════════════════════════════════════
#  Anomaly detection — sudden spikes
# ═════════════════════════════════════════════════════════════

def detect_anomalies(df: pd.DataFrame) -> list[dict]:
    """
    Detect areas with unusual spikes in cases.

    Compares last 7 days vs prior 7 days per cluster.
    Returns a list of alert dicts for clusters with ≥2× increase.
    """
    if df.empty or "cluster" not in df.columns or "visit_date" not in df.columns:
        return []

    alerts: list[dict] = []
    today = date.today()
    recent_start = today - timedelta(days=7)
    prior_start = today - timedelta(days=14)

    clustered = df[df["cluster"] >= 0].copy()
    if clustered.empty:
        return []

    # Parse visit_date if it's a string
    if clustered["visit_date"].dtype == object:
        clustered["visit_date"] = pd.to_datetime(clustered["visit_date"]).dt.date

    for cluster_id in clustered["cluster"].unique():
        cdata = clustered[clustered["cluster"] == cluster_id]
        recent = cdata[cdata["visit_date"] >= recent_start]
        prior = cdata[(cdata["visit_date"] >= prior_start) & (cdata["visit_date"] < recent_start)]

        recent_count = len(recent)
        prior_count = len(prior)

        if recent_count >= 3 and (prior_count == 0 or recent_count >= prior_count * 2):
            # Get centroid for alert location
            center_lat = cdata["lat"].mean()
            center_lng = cdata["lng"].mean()
            top_diag = cdata["diagnosis"].value_counts().head(1)
            alerts.append({
                "cluster": int(cluster_id),
                "location": f"({center_lat:.4f}, {center_lng:.4f})",
                "recent_cases": recent_count,
                "prior_cases": prior_count,
                "top_diagnosis": top_diag.index[0] if not top_diag.empty else "Unknown",
                "severity": "🔴 SPIKE DETECTED",
            })

    return alerts


# ═════════════════════════════════════════════════════════════
#  Trend analysis over time
# ═════════════════════════════════════════════════════════════

def analyse_trends(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute daily case counts and average severity over time.

    Returns a DataFrame with columns:
      date, cases, avg_severity, cumulative_cases
    Useful for charting trends and the time slider.
    """
    if df.empty or "visit_date" not in df.columns:
        return pd.DataFrame(columns=["date", "cases", "avg_severity", "cumulative_cases"])

    tdf = df.copy()
    if tdf["visit_date"].dtype == object:
        tdf["visit_date"] = pd.to_datetime(tdf["visit_date"], errors="coerce").dt.date

    daily = (
        tdf.groupby("visit_date")
        .agg(cases=("visit_date", "size"), avg_severity=("weight", "mean"))
        .reset_index()
        .rename(columns={"visit_date": "date"})
        .sort_values("date")
    )
    daily["cumulative_cases"] = daily["cases"].cumsum()
    daily["avg_severity"] = daily["avg_severity"].round(2)
    return daily


# ═════════════════════════════════════════════════════════════
#  Generate weighted Folium heatmap
# ═════════════════════════════════════════════════════════════

def generate_weighted_heatmap(df: pd.DataFrame) -> folium.Map:
    """
    Build an interactive Folium heatmap with severity-weighted intensity.

    Each data point contributes [lat, lng, weight] to the heatmap layer.
    Cluster centroids are marked with circle markers showing:
      - Case count, top diagnoses, average severity, risk level
    """
    # Default center: Malaysia
    center_lat = df["lat"].mean() if not df.empty else 3.14
    center_lng = df["lng"].mean() if not df.empty else 101.69

    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=11,
        tiles="CartoDB positron",
    )

    if df.empty:
        return m

    # ── Heatmap layer (weighted by severity) ─────────────────
    heat_data = df[["lat", "lng", "weight"]].values.tolist()
    HeatMap(
        heat_data,
        radius=20,
        blur=15,
        max_zoom=13,
        gradient={0.2: "blue", 0.4: "lime", 0.6: "yellow", 0.8: "orange", 1.0: "red"},
    ).add_to(m)

    # ── Cluster centroid markers with popup info ─────────────
    if "cluster" in df.columns:
        clustered = df[df["cluster"] >= 0]
        for cluster_id, group in clustered.groupby("cluster"):
            clat = group["lat"].mean()
            clng = group["lng"].mean()
            count = len(group)
            avg_weight = group["weight"].mean()
            top_diags = group["diagnosis"].value_counts().head(3)
            risk = group["predicted_risk"].mode().iloc[0] if "predicted_risk" in group.columns else "N/A"

            # Colour by risk level
            color = {"HIGH": "red", "MEDIUM": "orange", "LOW": "green"}.get(risk, "gray")

            # Build popup HTML
            diag_list = "<br>".join(f"• {d}: {c}" for d, c in top_diags.items())
            popup_html = (
                f"<b>Cluster {int(cluster_id)}</b><br>"
                f"<b>Cases:</b> {count}<br>"
                f"<b>Avg Severity:</b> {avg_weight:.1f}/3<br>"
                f"<b>Risk:</b> {risk}<br>"
                f"<hr><b>Top Diagnoses:</b><br>{diag_list}"
            )

            folium.CircleMarker(
                location=[clat, clng],
                radius=max(8, count * 2),
                color=color,
                fill=True,
                fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=f"Cluster {int(cluster_id)}: {count} cases ({risk})",
            ).add_to(m)

    return m


# ═════════════════════════════════════════════════════════════
#  Medicine / resource recommendation
# ═════════════════════════════════════════════════════════════

# Diagnosis → recommended medicine mapping
_MEDICINE_MAP = {
    "fever":                  ["Paracetamol", "Ibuprofen"],
    "cough":                  ["Dextromethorphan", "Guaifenesin"],
    "influenza":              ["Oseltamivir (Tamiflu)", "Paracetamol"],
    "flu":                    ["Oseltamivir (Tamiflu)", "Paracetamol"],
    "respiratory infection":  ["Amoxicillin", "Azithromycin", "Salbutamol inhaler"],
    "respiratory":            ["Amoxicillin", "Azithromycin"],
    "pneumonia":              ["Amoxicillin", "Azithromycin", "Oxygen therapy"],
    "diarrhoea":              ["ORS (Oral Rehydration Salts)", "Loperamide"],
    "diarrhea":               ["ORS (Oral Rehydration Salts)", "Loperamide"],
    "dengue":                 ["Paracetamol", "IV Fluids"],
    "covid":                  ["Paxlovid", "Paracetamol", "Dexamethasone"],
    "covid-19":               ["Paxlovid", "Paracetamol", "Dexamethasone"],
    "headache":               ["Paracetamol", "Ibuprofen"],
    "sore throat":            ["Lozenges", "Paracetamol"],
    "skin rash":              ["Hydrocortisone cream", "Cetirizine"],
    "allergy":                ["Cetirizine", "Loratadine"],
}


def recommend_medicine_allocation(df: pd.DataFrame) -> pd.DataFrame:
    """
    Estimate required medicine stock based on diagnosis distribution
    and severity weighting.

    Returns a DataFrame with columns:
      Medicine, Estimated Units, Priority, Based On
    """
    if df.empty:
        return pd.DataFrame(columns=["Medicine", "Estimated Units", "Priority", "Based On"])

    recommendations: dict[str, dict] = {}

    for _, row in df.iterrows():
        diag = row.get("diagnosis", "").lower().strip()
        weight = row.get("weight", 1)

        # Find matching medicines
        matched_meds: list[str] = []
        for keyword, meds in _MEDICINE_MAP.items():
            if keyword in diag:
                matched_meds.extend(meds)
                break

        if not matched_meds:
            matched_meds = ["General supplies"]

        for med in matched_meds:
            if med not in recommendations:
                recommendations[med] = {"units": 0, "max_severity": 0, "diagnoses": set()}
            # Each case needs ~weight units of medicine
            recommendations[med]["units"] += weight * 5  # 5 units per severity point
            recommendations[med]["max_severity"] = max(
                recommendations[med]["max_severity"], weight
            )
            recommendations[med]["diagnoses"].add(diag)

    rows = []
    for med, info in sorted(recommendations.items(), key=lambda x: -x[1]["units"]):
        priority = {3: "🔴 Urgent", 2: "🟠 Moderate", 1: "🟢 Standard"}.get(
            info["max_severity"], "🟢 Standard"
        )
        rows.append({
            "Medicine": med,
            "Estimated Units": info["units"],
            "Priority": priority,
            "Based On": ", ".join(sorted(info["diagnoses"]))[:80],
        })

    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════
#  Main orchestrator function
# ═════════════════════════════════════════════════════════════

def generate_ai_pandemic_heatmap(
    visits: list[dict],
) -> tuple[folium.Map | None, pd.DataFrame, pd.DataFrame, list[dict], pd.DataFrame]:
    """
    End-to-end pipeline: consultations → structure → weight → geocode →
    cluster → hotspots → anomalies → heatmap → recommendations → trends.

    Args:
        visits: list of visit/consultation dicts from the API.

    Returns:
        (folium_map, geo_dataframe, medicine_recs, anomaly_alerts, trend_df)
    """
    if not visits:
        empty = pd.DataFrame()
        return None, empty, empty, [], empty

    # ── Structure consultation data ──────────────────────────
    df = query_consultation_data(visits)

    # ── Assign severity weights ──────────────────────────────
    df = assign_severity_weights(df)

    # ── Geocode addresses ────────────────────────────────────
    coords = df["home_address"].apply(geocode_address)
    df["lat"] = coords.apply(lambda c: c[0] if c else None)
    df["lng"] = coords.apply(lambda c: c[1] if c else None)

    # Drop rows without coordinates
    geo_df = df.dropna(subset=["lat", "lng"]).copy()

    if geo_df.empty:
        empty = pd.DataFrame()
        return None, df, empty, [], empty

    # ── Predict hotspots via clustering ──────────────────────
    geo_df = predict_hotspots(geo_df)

    # ── Detect anomalies (unusual spikes) ────────────────────
    alerts = detect_anomalies(geo_df)

    # ── Trend analysis ───────────────────────────────────────
    trend_df = analyse_trends(geo_df)

    # ── Generate weighted heatmap ────────────────────────────
    heatmap = generate_weighted_heatmap(geo_df)

    # ── Medicine recommendations ─────────────────────────────
    med_recs = recommend_medicine_allocation(geo_df)

    return heatmap, geo_df, med_recs, alerts, trend_df
