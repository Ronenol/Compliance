import streamlit as st
import pandas as pd
from datetime import timedelta

st.title("Pilot VFR Time Dashboard")

# 1. Upload file
uploaded = st.file_uploader("Upload your HeliEFB Excel file", type="xlsx")
if not uploaded:
    st.info("Please upload the Excel file to get started.")
    st.stop()

# 2. Load sheets
df_flights = pd.read_excel(uploaded, sheet_name="Flight", dtype=str)
df_crew    = pd.read_excel(uploaded, sheet_name="Crew Currency", dtype=str)
df_legs    = pd.read_excel(uploaded, sheet_name="Leg", dtype=str)

# 3. Normalize IDs
df_flights["flight id"] = df_flights["id"].str.lstrip("#")
df_crew["flight id"]    = df_crew["flight id"].str.lstrip("#")
df_legs["flight id"]    = df_legs["flight id"].str.lstrip("#")
df_crew["leg id"]       = df_crew["leg id"].astype(str)
df_legs["leg id"]       = df_legs["leg id"].astype(str)

# 4. Merge data
df = (
    df_crew
    .merge(df_flights[["flight id","flt date","a/c type","type of flight"]], on="flight id", how="left")
    .merge(df_legs[["flight id","leg id","type of landing"]], on=["flight id","leg id"], how="left")
)

# 5. Parse and clean dates
df["flt date"] = pd.to_datetime(df["flt date"], errors="coerce")
df = df.dropna(subset=["flt date"])
if df.empty:
    st.error("No valid flight dates found. Check your Flight sheet.")
    st.stop()

# 6. Parse VFR times
df["vfr td"] = pd.to_timedelta(df["vfr t"].fillna("0:00") + ":00", errors="coerce")

# 7. Sidebar filters
ac_types = sorted(df["a/c type"].dropna().unique())
sel_ac = st.sidebar.multiselect("Filter by A/C Type", ac_types, default=ac_types)
df = df[df["a/c type"].isin(sel_ac)]
ftypes = sorted(df["type of flight"].dropna().unique())
sel_ft = st.sidebar.multiselect("Filter by Type of Flight", ftypes, default=ftypes)
df = df[df["type of flight"].isin(sel_ft)]

# 8. Date range selection (Time term)
min_date = df["flt date"].min().date()
max_date = df["flt date"].max().date()
term_start = st.sidebar.date_input("Term Start date", value=min_date, min_value=min_date, max_value=max_date)
term_end   = st.sidebar.date_input("Term End date",   value=max_date, min_value=min_date, max_value=max_date)
if term_start > term_end:
    st.sidebar.error("Term Start date must be on or before Term End date.")
    st.stop()
df = df[(df["flt date"].dt.date >= term_start) & (df["flt date"].dt.date <= term_end)]
if df.empty:
    st.warning("No flights match the selected filters & dates.")
    st.stop()

# 9. Compute Term VFR per pilot
df_vfr = df.groupby("crew")["vfr td"].sum()
def fmt(td):
    hrs = td.components.days * 24 + td.components.hours
    mins = td.components.minutes
    return f"{hrs}:{mins:02d}"
display_vfr = pd.DataFrame({
    "Term VFR": df_vfr.map(fmt),
    "Hours (dec)": df_vfr.dt.total_seconds().div(3600).round(2)
}).sort_values("Hours (dec)", ascending=False)

# 10. Flight Hour Compliance Countdown
window_days = st.sidebar.number_input("Window (In recent days)", min_value=1, value=60)
window_min = st.sidebar.number_input("Window Minimum Hrs", min_value=0.0, value=15.0)
today = pd.to_datetime(term_end)
results = []
last_dates = df.groupby("crew")["flt date"].max().dt.date
for crew_name, grp in df.groupby("crew"):
    last_date = last_dates.get(crew_name)
    term_vfr = display_vfr.at[crew_name, "Term VFR"] if crew_name in display_vfr.index else "0:00"
    # rolling window hours
    days_window = timedelta(days=window_days)
    window_start = today - days_window
    curr_hours = grp[(grp["flt date"] > window_start) & (grp["flt date"] <= today)]["vfr td"].dt.total_seconds().sum()/3600
    curr = curr_hours
    if curr < window_min:
        expire = today.date()
    else:
        events = {}
        for _, row in grp[(grp["flt date"] > window_start) & (grp["flt date"] <= today)].iterrows():
            exp_d = (row["flt date"] + days_window).date()
            events.setdefault(exp_d, 0)
            events[exp_d] += row["vfr td"].total_seconds()/3600
        expire = None
        for ed in sorted(events):
            curr -= events[ed]
            if curr < window_min:
                expire = ed
                break
    missing = curr - window_min
    results.append({
        'crew': crew_name,
        'Last Flight Date': last_date,
        'Term VFR': term_vfr,
        f"{window_days}-day VFR": f"{curr_hours:.2f}",
        'VFR Expiration': expire or "Never",
        'VFR at Expiration': f"{missing:.2f}"
    })
countdown = pd.DataFrame(results).set_index('crew')
col_w = f"{window_days}-day VFR"
countdown = countdown[["Term VFR","Last Flight Date",col_w,"VFR Expiration","VFR at Expiration"]]

st.header("Flight Hour Compliance Countdown")
func = lambda val: 'color: red' if pd.to_datetime(val).date() <= today.date() else ''
st.dataframe(countdown.style.applymap(func, subset=["VFR Expiration"]))

# 11. Landings
landings = df.groupby(["crew","type of landing"]).size().unstack(fill_value=0)
st.header("Landings")
st.dataframe(landings)
