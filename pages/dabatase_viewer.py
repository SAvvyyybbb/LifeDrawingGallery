# pages/database_viewer.py
import streamlit as st
from pathlib import Path
import sqlite3
import config
import pandas as pd

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Database Viewer & Editor",
    layout="wide"
)

st.title("LifeDrawingGallery Database Viewer & Editor")
st.write("""
Explore, filter, and edit your SQLite databases.
Select a database, browse tables, filter rows, edit values, and save changes.
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

# ---------------- Browse & Filter Rows ----------------
st.markdown("---")
st.subheader(f"Rows in Table: {table_name}")

try:
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    total_rows = cursor.fetchone()[0]
    st.write(f"Total Rows: {total_rows}")

    max_rows = st.number_input(
        "Maximum rows to display/edit",
        min_value=10,
        max_value=1000,
        value=100,
        step=10
    )

    query = f"SELECT * FROM {table_name} LIMIT {int(max_rows)}"
    df = pd.read_sql_query(query, conn)

    if df.empty:
        st.info("No rows found.")
    else:
        # ---------------- Filter Section ----------------
        st.subheader("Filter Rows (Optional)")
        filter_column = st.selectbox("Column to filter", df.columns.tolist())
        filter_value = st.text_input("Filter value (contains)")
        if filter_value:
            df = df[df[filter_column].astype(str).str.contains(filter_value, case=False, na=False)]

        st.write(f"Displaying {len(df)} rows after filtering.")

        # ---------------- Editable Grid ----------------
        st.subheader("Edit Table Values")
        edited_df = st.data_editor(df, num_rows="dynamic")

        # ---------------- Save Changes ----------------
        if st.button("Save Changes to Database"):
            try:
                # Determine primary key: prefer 'id', else first column
                pk_col = "id" if "id" in df.columns else df.columns[0]
                for index, row in edited_df.iterrows():
                    set_clause = ", ".join([f"{col} = ?" for col in df.columns])
                    pk_value = row[pk_col]
                    values = [row[col] for col in df.columns] + [pk_value]
                    sql = f"UPDATE {table_name} SET {set_clause} WHERE {pk_col} = ?"
                    cursor.execute(sql, values)
                conn.commit()
                st.success("Changes saved successfully ✅")
            except Exception as e:
                st.error(f"Failed to save changes: {e}")

except Exception as e:
    st.error(f"Failed to read rows: {e}")

conn.close()