import streamlit as st
import pandas as pd
import io
from datetime import timedelta
from fpdf import FPDF

st.set_page_config(page_title="Pilot VFR Dashboard", layout="wide")
st.title("🚁 Pilot VFR Time Dashboard")

# ========= Sidebar =========
st.sidebar.header("🧭 Filters")
uploaded = st.sidebar.file_uploader("Upload your HeliEFB Excel file", type="xlsx")

if not uploaded:
    st.info("Please upload the Excel file to get started.")
    st.stop()

# ========= Read and Process Data =========
df_flights = pd.read_excel(uploaded, sheet_name="Flight", dtype=str)
df_crew    = pd.read_excel(uploaded, sheet_name="Crew Currency", dtype=str)
df_legs    = pd.read_excel(uploaded, sheet_name="Leg", dtype=str)

df_flights["flight id"] = df_flights["id"].str.lstrip("#")
df_crew["flight id"]    = df_crew["flight id"].str.lstrip("#")
df_legs["flight id"]    = df_legs["flight id"].str.lstrip("#")
df_crew["leg id"]       = df_crew["leg id"].astype(str)
df_legs["leg id"]       = df_legs["leg id"].astype(str)

df = (
    df_crew
    .merge(df_flights[["flight id","flt date","a/c type","type of flight"]], on="flight id", how="left")
    .merge(df_legs[["flight id","leg id","type of landing"]], on=["flight id","leg id"], how="left")
)

df["flt date"] = pd.to_datetime(df["flt date"], errors="coerce")
df = df.dropna(subset=["flt date"])
if df.empty:
    st.error("No valid flight dates found. Check your Flight sheet.")
    st.stop()

df["vfr td"] = pd.to_timedelta(df["vfr t"].fillna("0:00") + ":00", errors="coerce")

# ========= Filters =========
ac_types = sorted(df["a/c type"].dropna().unique())
sel_ac = st.sidebar.multiselect("A/C Type", ac_types, default=ac_types)
df = df[df["a/c type"].isin(sel_ac)]

ftypes = sorted(df["type of flight"].dropna().unique())
sel_ft = st.sidebar.multiselect("Type of Flight", ftypes, default=ftypes)
df = df[df["type of flight"].isin(sel_ft)]

min_date = df["flt date"].min().date()
max_date = df["flt date"].max().date()
term_start = st.sidebar.date_input("Term Start Date", value=min_date, min_value=min_date, max_value=max_date)
term_end   = st.sidebar.date_input("Term End Date",   value=max_date, min_value=min_date, max_value=max_date)

if term_start > term_end:
    st.sidebar.error("Start date must be before or equal to end date.")
    st.stop()

df = df[(df["flt date"].dt.date >= term_start) & (df["flt date"].dt.date <= term_end)]
if df.empty:
    st.warning("No flights match selected filters.")
    st.stop()

# ========= Compute VFR Time =========
df_vfr = df.groupby("crew")["vfr td"].sum()

def fmt(td):
    hrs = td.components.days * 24 + td.components.hours
    mins = td.components.minutes
    return f"{hrs}:{mins:02d}"

display_vfr = pd.DataFrame({
    "Term VFR": df_vfr.map(fmt),
    "Hours (dec)": df_vfr.dt.total_seconds().div(3600).round(2)
}).sort_values("Hours (dec)", ascending=False)

# ========= Compliance Countdown =========
st.sidebar.header("📆 Compliance Settings")
window_days = st.sidebar.number_input("Window (Days)", min_value=1, value=60)
window_min = st.sidebar.number_input("Minimum VFR Hours", min_value=0.0, value=15.0)

today = pd.to_datetime(term_end)
results = []
last_dates = df.groupby("crew")["flt date"].max().dt.date

for crew_name, grp in df.groupby("crew"):
    last_date = last_dates.get(crew_name)
    term_vfr = display_vfr.at[crew_name, "Term VFR"] if crew_name in display_vfr.index else "0:00"
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

# ========= Excel Export =========
def create_excel_download(countdown_df, landings_df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        countdown_df.to_excel(writer, sheet_name="VFR Countdown")
        landings_df.to_excel(writer, sheet_name="Landings")
    output.seek(0)
    return output

# ========= PDF Export =========
def generate_pdf(countdown_df, landings_df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="Flight Hour Compliance Countdown", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.ln(5)
    for i, row in countdown_df.reset_index().iterrows():
        line = ", ".join([f"{k}: {v}" for k, v in row.items()])
        pdf.multi_cell(0, 7, txt=line)

    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="Landings per Pilot", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.ln(5)
    for i, row in landings_df.reset_index().iterrows():
        line = ", ".join([f"{k}: {v}" for k, v in row.items()])
        pdf.multi_cell(0, 7, txt=line)

    pdf_bytes = pdf.output(dest='S').encode('latin-1')
    return io.BytesIO(pdf_bytes)

# ========= Tabs =========
tab1, tab2 = st.tabs(["📉 Flight Hour Compliance Countdown", "🛬 Landings Per Pilot"])

with tab1:
    st.subheader("Flight Hour Compliance Countdown")
    styled_df = countdown.style\
        .applymap(lambda val: 'color: red; font-weight: bold;' if pd.to_datetime(val, errors="coerce") and pd.to_datetime(val).date() <= today.date() else '', subset=["VFR Expiration"])\
        .format({
            col_w: lambda x: f"{float(x):.2f}" if str(x).replace('.', '', 1).isdigit() else x,
            "VFR at Expiration": lambda x: f"{float(x):.2f}" if str(x).replace('.', '', 1).isdigit() else x
        })\
        .set_properties(**{"text-align": "center"})\
        .set_table_styles([
            {"selector": "thead th", "props": [("background-color", "#0e1117"), ("color", "white")]},
            {"selector": "tbody td", "props": [("border", "1px solid #ccc")]}
        ])
    st.dataframe(styled_df, use_container_width=True)

with tab2:
    st.subheader("Landings per Pilot")
    landings = df.groupby(["crew", "type of landing"]).size().unstack(fill_value=0)
    st.dataframe(
        landings.style
        .set_properties(**{"text-align": "center"}),
        use_container_width=True
    )

# ========= Download Buttons =========
excel_data = create_excel_download(countdown.reset_index(), landings)
st.download_button(
    label="📥 Export Both Tables to Excel",
    data=excel_data,
    file_name="VFR_dashboard_export.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

pdf_data = generate_pdf(countdown, landings)
st.download_button(
    label="🧾 Export Both Tables to PDF",
    data=pdf_data,
    file_name="VFR_dashboard_export.pdf",
    mime="application/pdf"
)
