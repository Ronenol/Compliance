import streamlit as st
import pandas as pd

st.title("Pilot VFR Time Dashboard")

# 1. Upload
uploaded = st.file_uploader("Upload your HeliEFB Excel file", type="xlsx")
if not uploaded:
    st.info("Please upload the Excel file to get started.")
    st.stop()

# 2. Read Flight + Crew sheets
flights = pd.read_excel(uploaded, sheet_name="Flight", dtype=str)
crew    = pd.read_excel(uploaded, sheet_name="Crew Currency", dtype=str)

# 3. Normalize IDs
flights["flight id"] = flights["id"].str.lstrip("#")
crew   ["flight id"] = crew["flight id"].str.lstrip("#")

# 4. Merge in both date & aircraft type
df = crew.merge(
    flights[["flight id", "flt date", "a/c type"]],
    on="flight id",
    how="left"
)

# 5. Parse & clean dates
df["flt date"] = pd.to_datetime(df["flt date"], errors="coerce")
df = df.dropna(subset=["flt date"])
if df.empty:
    st.error("No valid flight dates found. Check your Flight sheet.")
    st.stop()

# 6. Parse VFR times into timedeltas
df["vfr td"] = pd.to_timedelta(df["vfr t"].fillna("0:00") + ":00", errors="coerce")

# ─── New: Aircraft type filter ───
all_types = sorted(df["a/c type"].dropna().unique())
selected_types = st.sidebar.multiselect(
    "Filter by A/C Type",
    options=all_types,
    default=all_types
)
df = df[df["a/c type"].isin(selected_types)]

# 7. Compute calendar bounds
min_date = df["flt date"].min().date()
max_date = df["flt date"].max().date()

# 8. Date pickers
start_date = st.sidebar.date_input(
    "Start date",
    value=min_date,
    min_value=min_date,
    max_value=max_date
)
end_date = st.sidebar.date_input(
    "End date",
    value=max_date,
    min_value=min_date,
    max_value=max_date
)
if start_date > end_date:
    st.sidebar.error("Start date must be on or before End date.")
    st.stop()

# 9. Filter by date
mask = (df["flt date"].dt.date >= start_date) & (df["flt date"].dt.date <= end_date)
df = df.loc[mask]

# 10. Aggregate VFR time per pilot
vfr_totals = df.groupby("crew")["vfr td"].sum()

# 11. Format for display
def fmt(td):
    hrs = td.components.days * 24 + td.components.hours
    mins = td.components.minutes
    return f"{hrs}:{mins:02d}"

display = pd.DataFrame({
    "Total VFR Time": vfr_totals.map(fmt),
    "Hours (dec)":    vfr_totals.dt.total_seconds().div(3600).round(2)
}).sort_values("Hours (dec)", ascending=False)

# 12. Show outputs
st.header(f"VFR Time per Pilot\n({start_date} → {end_date})")
st.dataframe(display[["Total VFR Time"]])

st.subheader("VFR Time (decimal hours)")
st.bar_chart(display["Hours (dec)"])
