# pages/database_viewer.py
import streamlit as st
from pathlib import Path
import sqlite3
import config
import pandas as pd
import time

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Database Viewer",
    layout="wide"
)

st.title("LifeDrawingGallery Database Viewer")
st.write("""
Explore your SQLite databases for LifeDrawingGallery.
Select a database, view its tables, and inspect rows.
""")

# ---------------- Select Database ----------------
db_root = config.DB_DIR
if not db_root.exists():
    st.warning(f"Database folder not found: {db_root}")
    st.stop()

db_files = sorted([p for p in db_root.iterdir() if p.suffix == ".db"])
if not db_files:
    st.info("No database files found.")
    st.stop()

db_file = st.selectbox("Select Database", db_files, format_func=lambda p: p.name)

# ---------------- Connect to DB ----------------
try:
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
except Exception as e:
    st.error(f"Failed to connect to {db_file.name}: {e}")
    st.stop()

# ---------------- List Tables ----------------
try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [t[0] for t in cursor.fetchall()]
except Exception as e:
    st.error(f"Failed to read tables: {e}")
    conn.close()
    st.stop()

if not tables:
    st.info(f"No tables found in {db_file.name}.")
    conn.close()
    st.stop()

table_name = st.selectbox("Select Table", tables)

# ---------------- Browse Rows ----------------
st.markdown("---")
st.subheader(f"Rows in Table: {table_name}")

try:
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    total_rows = cursor.fetchone()[0]
    st.write(f"Total Rows: {total_rows}")

    max_rows = st.number_input(
        "Maximum rows to display",
        min_value=10,
        max_value=10000,
        value=100,
        step=10
    )

    query = f"SELECT * FROM {table_name} LIMIT {int(max_rows)}"
    df = pd.read_sql_query(query, conn)

    if df.empty:
        st.info("No rows found.")
    else:
        st.dataframe(df)

except Exception as e:
    st.error(f"Failed to read rows: {e}")

# ---------------- Optional Filters ----------------
st.markdown("---")
st.subheader("Search / Filter Table (Optional)")

try:
    filter_column = st.selectbox("Select Column to Filter", df.columns.tolist())
    filter_value = st.text_input("Filter Value (contains)")
    if filter_value:
        filtered_df = df[df[filter_column].astype(str).str.contains(filter_value, case=False, na=False)]
        st.write(f"Filtered Rows: {len(filtered_df)}")
        st.dataframe(filtered_df)
except Exception:
    pass

conn.close()