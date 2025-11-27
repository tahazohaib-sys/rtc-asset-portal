#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RTC League - Asset Management Portal (Python + Streamlit + SQLite)
Clean light dashboard layout.
"""

import os
import sqlite3
from datetime import datetime, date

import pandas as pd
import streamlit as st

DB_PATH = os.path.join(os.path.dirname(__file__), "assets.db")


# ---------------------- DB SETUP ---------------------- #

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()

    # Assets Master
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS assets_master (
            asset_id TEXT PRIMARY KEY,
            asset_type TEXT NOT NULL,           -- Laptop / Office Equipment
            asset_name TEXT NOT NULL,
            laptop_category TEXT,
            laptop_description TEXT,
            purchase_date TEXT,                 -- ISO date string YYYY-MM-DD
            purchase_amount REAL,
            vendor_name TEXT,
            invoice_no TEXT
        );
        """
    )

    # Asset Movements
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_movements (
            movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL,
            movement_date TEXT NOT NULL,        -- ISO date string
            from_type TEXT,
            from_name TEXT,
            to_type TEXT,
            to_name TEXT,
            movement_type TEXT,                 -- Purchase / Allocate / Return / Transfer / Scrap
            reference TEXT,
            remarks TEXT,
            FOREIGN KEY (asset_id) REFERENCES assets_master(asset_id)
        );
        """
    )

    # Employees (simple master)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            email TEXT
        );
        """
    )

    conn.commit()


# ---------------------- HELPERS ---------------------- #

def next_asset_id(conn: sqlite3.Connection, prefix: str) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT asset_id FROM assets_master WHERE asset_id LIKE ? ORDER BY asset_id DESC LIMIT 1",
        (prefix + "-%",),
    )
    row = cur.fetchone()
    if not row:
        return f"{prefix}-0001"
    last_id = row["asset_id"]
    try:
        num = int(last_id.split("-")[1])
    except Exception:
        num = 0
    next_num = str(num + 1).zfill(4)
    return f"{prefix}-{next_num}"


def to_iso(d: date | None) -> str | None:
    if not d:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


def parse_date_str(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None


# ---------------------- SNAPSHOT LOGIC ---------------------- #

def get_snapshot(conn: sqlite3.Connection) -> pd.DataFrame:
    assets = pd.read_sql_query("SELECT * FROM assets_master", conn)
    if assets.empty:
        return pd.DataFrame(
            columns=[
                "asset_id",
                "asset_type",
                "asset_name",
                "laptop_category",
                "laptop_description",
                "purchase_date",
                "purchase_amount",
                "current_holder_type",
                "current_holder_name",
                "in_usage_from",
                "status",
            ]
        )

    moves = pd.read_sql_query(
        "SELECT * FROM asset_movements ORDER BY movement_date ASC, movement_id ASC",
        conn,
    )

    by_asset: dict[str, list] = {}
    for _, row in moves.iterrows():
        aid = row["asset_id"]
        by_asset.setdefault(aid, []).append(row)

    snapshot_rows = []

    for _, a in assets.iterrows():
        asset_id = a["asset_id"]
        mov_list = by_asset.get(asset_id, [])

        holder_type = "Stock"
        holder_name = "Store"
        status = "In Stock"
        in_usage_from = None

        for m in mov_list:
            to_type = (m["to_type"] or "").strip().lower()
            to_name = m["to_name"] or ""
            mov_type = (m["movement_type"] or "").strip().lower()
            mov_date = m["movement_date"]

            if mov_type == "scrap" or to_type == "disposal":
                holder_type = "Disposal"
                holder_name = to_name
                status = "Scrapped"
            elif to_type == "employee":
                holder_type = "Employee"
                holder_name = to_name
                status = "Allocated"
                if in_usage_from is None:
                    in_usage_from = mov_date
            elif to_type == "stock":
                holder_type = "Stock"
                holder_name = to_name or "Store"
                status = "In Stock"

        snapshot_rows.append(
            {
                "asset_id": asset_id,
                "asset_type": a["asset_type"],
                "asset_name": a["asset_name"],
                "laptop_category": a["laptop_category"],
                "laptop_description": a["laptop_description"],
                "purchase_date": a["purchase_date"],
                "purchase_amount": a["purchase_amount"],
                "current_holder_type": holder_type,
                "current_holder_name": holder_name,
                "in_usage_from": in_usage_from,
                "status": status,
            }
        )

    snap_df = pd.DataFrame(snapshot_rows)
    return snap_df


def get_dashboard_stats(snapshot: pd.DataFrame) -> dict:
    if snapshot.empty:
        return {
            "total_assets": 0,
            "total_amount": 0,
            "total_allocated_laptops": 0,
            "laptops_in_stock": 0,
        }

    total_assets = len(snapshot)
    total_amount = snapshot.loc[
        snapshot["status"] != "Scrapped", "purchase_amount"
    ].fillna(0).sum()

    is_laptop = snapshot["asset_type"].str.lower().eq("laptop")
    is_emp = snapshot["current_holder_type"].str.lower().eq("employee")
    is_stock = snapshot["current_holder_type"].str.lower().eq("stock")
    is_in_stock = snapshot["status"].str.lower().eq("in stock")

    total_allocated_laptops = snapshot[is_laptop & is_emp].shape[0]
    laptops_in_stock = snapshot[is_laptop & (is_in_stock | is_stock)].shape[0]

    return {
        "total_assets": int(total_assets),
        "total_amount": float(total_amount),
        "total_allocated_laptops": int(total_allocated_laptops),
        "laptops_in_stock": int(laptops_in_stock),
    }


def get_allocated_laptops(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    is_laptop = snapshot["asset_type"].str.lower().eq("laptop")
    is_emp = snapshot["current_holder_type"].str.lower().eq("employee")
    return snapshot[is_laptop & is_emp].copy()


def get_assets_by_type(snapshot: pd.DataFrame, asset_type: str) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    return snapshot[snapshot["asset_type"].str.lower() == asset_type.lower()].copy()


def get_laptops_in_stock(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    is_laptop = snapshot["asset_type"].str.lower().eq("laptop")
    is_stock = snapshot["current_holder_type"].str.lower().eq("stock")
    is_in_stock = snapshot["status"].str.lower().eq("in stock")
    return snapshot[is_laptop & (is_stock | is_in_stock)].copy()


def apply_search_filter(df: pd.DataFrame, query: str) -> pd.DataFrame:
    q = (query or "").strip().lower()
    if not q or df.empty:
        return df
    mask = (
        df["asset_id"].astype(str).str.lower().str.contains(q)
        | df["asset_name"].astype(str).str.lower().str.contains(q)
    )
    return df[mask].copy()


# ---------------------- BUSINESS ACTIONS ---------------------- #

def add_asset(
    conn: sqlite3.Connection,
    asset_type: str,
    asset_name: str,
    laptop_category: str,
    laptop_description: str,
    purchase_date: date | None,
    purchase_amount: float | None,
    vendor_name: str,
    invoice_no: str,
):
    prefix = "LAP" if asset_type.lower() == "laptop" else "OFF"
    asset_id = next_asset_id(conn, prefix)

    iso_date = to_iso(purchase_date) or date.today().isoformat()
    amount = float(purchase_amount or 0)

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO assets_master (
            asset_id, asset_type, asset_name,
            laptop_category, laptop_description,
            purchase_date, purchase_amount,
            vendor_name, invoice_no
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            asset_type,
            asset_name,
            laptop_category,
            laptop_description,
            iso_date,
            amount,
            vendor_name,
            invoice_no,
        ),
    )

    cur.execute(
        """
        INSERT INTO asset_movements (
            asset_id, movement_date,
            from_type, from_name,
            to_type, to_name,
            movement_type, reference, remarks
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            iso_date,
            "Vendor",
            vendor_name,
            "Stock",
            "Store",
            "Purchase",
            invoice_no,
            "Initial purchase",
        ),
    )
    conn.commit()
    return asset_id


def allocate_asset(
    conn: sqlite3.Connection,
    snapshot: pd.DataFrame,
    asset_id: str,
    employee_name: str,
    alloc_date: date | None,
):
    alloc_date_iso = to_iso(alloc_date) or date.today().isoformat()

    row = snapshot.loc[snapshot["asset_id"] == asset_id]
    if row.empty:
        raise ValueError("Asset not found in snapshot")

    current = row.iloc[0]
    from_type = current["current_holder_type"] or "Stock"
    from_name = current["current_holder_name"] or "Store"

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO asset_movements (
            asset_id, movement_date,
            from_type, from_name,
            to_type, to_name,
            movement_type, reference, remarks
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            alloc_date_iso,
            from_type,
            from_name,
            "Employee",
            employee_name,
            "Allocate",
            "",
            f"Allocated to {employee_name}",
        ),
    )
    conn.commit()


def process_movement(
    conn: sqlite3.Connection,
    snapshot: pd.DataFrame,
    asset_id: str,
    action: str,
    move_date: date | None,
    new_employee: str | None,
    remarks: str | None,
):
    move_date_iso = to_iso(move_date) or date.today().isoformat()

    row = snapshot.loc[snapshot["asset_id"] == asset_id]
    if row.empty:
        raise ValueError("Asset not found in snapshot")

    current = row.iloc[0]
    from_type = current["current_holder_type"] or ""
    from_name = current["current_holder_name"] or ""

    action = (action or "").lower().strip()
    if action == "return":
        to_type, to_name, mov_type = "Stock", "Store", "Return"
    elif action == "transfer":
        to_type, to_name, mov_type = "Employee", new_employee or "", "Transfer"
    elif action == "scrap":
        to_type, to_name, mov_type = "Disposal", "Scrap", "Scrap"
    else:
        raise ValueError("Unknown action")

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO asset_movements (
            asset_id, movement_date,
            from_type, from_name,
            to_type, to_name,
            movement_type, reference, remarks
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            move_date_iso,
            from_type,
            from_name,
            to_type,
            to_name,
            mov_type,
            "",
            remarks or "",
        ),
    )
    conn.commit()


def get_movement_history(conn: sqlite3.Connection, asset_id: str) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT
            movement_date,
            from_type || CASE WHEN from_name IS NOT NULL AND from_name != '' THEN ' - ' || from_name ELSE '' END AS from_party,
            to_type   || CASE WHEN to_name   IS NOT NULL AND to_name   != '' THEN ' - ' || to_name   ELSE '' END AS to_party,
            movement_type,
            reference,
            remarks
        FROM asset_movements
        WHERE asset_id = ?
        ORDER BY movement_date ASC, movement_id ASC
        """,
        conn,
        params=(asset_id,),
    )


def get_employees(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM employees ORDER BY name ASC")
    rows = cur.fetchall()
    return [(r["id"], r["name"]) for r in rows]


def add_employee(conn: sqlite3.Connection, name: str, email: str | None = None):
    name = (name or "").strip()
    if not name:
        return
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO employees (name, email) VALUES (?, ?)",
        (name, email),
    )
    conn.commit()


# ---------------------- STREAMLIT UI ---------------------- #

st.set_page_config(
    page_title="RTC League | Asset Management Portal",
    page_icon="💻",
    layout="wide",
)

# ---------- GLOBAL THEME ---------- #
st.markdown(
    """
    <style>
    .stApp {
        background: #f5f7fb;
        color: #111827;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    }

    .main .block-container {
        padding-top: 0.8rem;
        padding-bottom: 1.5rem;
        max-width: 1200px;
    }

    /* Hide ANY old glass top bar if it still exists */
    .rtc-topbar-glass { display: none !important; }

    /* Reset any old black KPI buttons (stat-card-*) to white */
    div[data-testid="stButton"][id^="stat-card-"] > button {
        background: #ffffff !important;
        color: #111827 !important;
        border: 1px solid #d1d5db !important;
        box-shadow: 0 12px 26px rgba(15,23,42,0.08) !important;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #ffffff !important;
        border-right: 1px solid #e5e7eb;
        box-shadow: 4px 0 18px rgba(15,23,42,0.04);
    }
    section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h1 {
        font-size: 0.8rem !important;
        text-transform: uppercase;
        letter-spacing: .08em;
        color: #6b7280 !important;
    }
    section[data-testid="stSidebar"] input[type="radio"] {
        visibility: hidden;
        width: 0;
        height: 0;
        margin: 0;
        padding: 0;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] > label {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.45rem 0.75rem;
        margin-bottom: 0.25rem;
        border-radius: 0.7rem;
        cursor: pointer;
        border: 1px solid transparent;
        transition: all 0.15s ease-out;
        font-size: 0.9rem;
        color: #111827 !important;
        background: transparent;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
        background: #eef2ff;
        border-color: #c7d2fe;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] > label[aria-checked="true"] {
        background: #111827 !important;
        border-color: #111827 !important;
        color: #f9fafb !important;
        box-shadow: 0 8px 18px rgba(15,23,42,0.35);
    }

    /* Header white bar */
    .rtc-header-box {
        background: #ffffff;
        border-radius: 0.9rem;
        padding: 1.0rem 1.2rem;
        margin-bottom: 1.0rem;
        box-shadow: 0 14px 30px rgba(15,23,42,0.08);
        border: 1px solid #e5e7eb;
    }
    .rtc-logo-small {
        width: 28px;
        height: 28px;
        border-radius: 7px;
        background: linear-gradient(135deg,#2563eb,#4f46e5);
        display:flex;
        align-items:center;
        justify-content:center;
        color:white;
        font-size:0.95rem;
        font-weight:600;
        margin-right:0.55rem;
    }
    .rtc-header-title {
        font-size: 1.0rem;
        font-weight: 600;
        color: #111827;
    }
    .rtc-header-sub {
        font-size: 0.78rem;
        color: #6b7280;
    }

    /* Search in header */
    .rtc-search-wrap input[type="text"] {
        width: 100%;
        padding: 0.45rem 0.9rem;
        border-radius: 999px;
        border: 1px solid #d1d5db;
        background: #ffffff !important;
        color: #111827 !important;
        font-size: 0.83rem;
    }
    .rtc-search-wrap input[type="text"]::placeholder {
        color: #9ca3af !important;
    }

    /* Header buttons */
    div[data-testid="stButton"][id^="top-btn-"] > button {
        width: 100%;
        padding: 0.45rem 0.75rem;
        border-radius: 999px;
        border: 1px solid #d1d5db !important;
        background: #ffffff !important;
        color: #111827 !important;
        font-size: 0.83rem;
        font-weight: 500;
        box-shadow: 0 6px 15px rgba(15,23,42,0.08);
    }
    div[data-testid="stButton"][id^="top-btn-"] > button:hover {
        background: #f3f4f6 !important;
    }

    /* Page title & subtitle */
    .rtc-page-title {
        font-size: 1.35rem;
        font-weight: 600;
        margin-bottom: 0.05rem;
        color: #111827;
    }
    .rtc-page-sub {
        font-size: 0.82rem;
        color: #6b7280;
        margin-bottom: 0.7rem;
    }

    /* NEW KPI cards (kpi-*) */
    div[data-testid="stButton"][id^="kpi-"] > button {
        width: 100%;
        text-align: left;
        white-space: pre-line;
        padding: 0.9rem 1.0rem;
        border-radius: 0.8rem;
        border: 1px solid #d1d5db !important;
        background: #ffffff !important;
        color: #111827 !important;
        font-size: 0.85rem;
        font-weight: 500;
        box-shadow: 0 12px 26px rgba(15,23,42,0.08);
    }
    div[data-testid="stButton"][id^="kpi-"] > button:hover {
        box-shadow: 0 16px 32px rgba(15,23,42,0.14);
        transform: translateY(-1px);
    }

    /* Tables */
    .stDataFrame, .stTable {
        border-radius: 0.8rem;
        border: 1px solid #e5e7eb;
        box-shadow: 0 14px 30px rgba(15,23,42,0.06);
        background: #ffffff;
    }

    hr { border-color: #e5e7eb; }
    </style>
    """,
    unsafe_allow_html=True,
)

conn = get_connection()
init_db(conn)

# ---------- SESSION STATE ---------- #
if "nav_menu" not in st.session_state:
    st.session_state["nav_menu"] = "Dashboard"
if "search_query" not in st.session_state:
    st.session_state["search_query"] = ""
if "dashboard_view" not in st.session_state:
    st.session_state["dashboard_view"] = "none"

# ---------- HEADER (one white bar) ---------- #
with st.container():
    st.markdown('<div class="rtc-header-box">', unsafe_allow_html=True)
    col_left, col_mid, col_right = st.columns([3, 4, 3])

    # LEFT: title top-left
    with col_left:
        st.markdown(
            """
            <div style="display:flex;align-items:flex-start;">
                <div class="rtc-logo-small">R</div>
                <div>
                    <div class="rtc-header-title">RTC League Asset Management</div>
                    <div class="rtc-header-sub">
                        Fixed Asset Dashboard for tracking allocation, stock, and equipment performance.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # MIDDLE: search
    with col_mid:
        st.markdown('<div class="rtc-search-wrap">', unsafe_allow_html=True)
        q = st.text_input(
            "Search assets",
            value=st.session_state["search_query"],
            label_visibility="collapsed",
            key="top-search",
            placeholder="Search by asset ID or name",
        )
        st.session_state["search_query"] = q
        st.markdown("</div>", unsafe_allow_html=True)

    # RIGHT: buttons
    with col_right:
        b1, b2 = st.columns(2)
        with b1:
            if st.button("List of Assets", key="top-btn-assets"):
                st.session_state["nav_menu"] = "Assets"
                st.rerun()
        with b2:
            if st.button("Add Asset", key="top-btn-add"):
                st.session_state["nav_menu"] = "Add Asset"
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ---------- PAGE HEADER ---------- #
st.markdown('<div class="rtc-page-title">Fixed Asset Management Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="rtc-page-sub">Overview of asset purchases, allocations, and stock positions across RTC League.</div>',
    unsafe_allow_html=True,
)

# ---------- SIDEBAR NAV ---------- #
menu = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Assets", "Add Asset", "Allocate", "Return / Transfer / Scrap", "Employees"],
    key="nav_menu",
)

snapshot_df = get_snapshot(conn)
search_query = st.session_state["search_query"]

# ---------------------- DASHBOARD ---------------------- #
if menu == "Dashboard":
    stats = get_dashboard_stats(snapshot_df)
    card_clicked = None

    # KPI cards with label and value
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        text = f"Total Assets\n{stats['total_assets']:,}"
        if st.button(text, key="kpi-total-assets"):
            card_clicked = "all"
    with c2:
        text = f"Total Asset Amount\n{stats['total_amount']:,.0f}"
        if st.button(text, key="kpi-total-amount"):
            card_clicked = "all"
    with c3:
        text = f"Total Allocated Laptops\n{stats['total_allocated_laptops']:,}"
        if st.button(text, key="kpi-allocated"):
            card_clicked = "allocated"
    with c4:
        text = f"Laptops in Stock\n{stats['laptops_in_stock']:,}"
        if st.button(text, key="kpi-stock"):
            card_clicked = "stock"

    if card_clicked:
        st.session_state["dashboard_view"] = card_clicked

    st.markdown("---")

    view = st.session_state["dashboard_view"]

    if view == "all":
        st.subheader("All Assets")
        df = apply_search_filter(snapshot_df, search_query)
        if df.empty:
            st.info("No assets recorded yet (or no match for current search).")
        else:
            view_df = df[
                [
                    "asset_id",
                    "asset_type",
                    "asset_name",
                    "laptop_category",
                    "current_holder_name",
                    "status",
                    "purchase_date",
                    "purchase_amount",
                ]
            ].rename(
                columns={
                    "asset_id": "Asset ID",
                    "asset_type": "Type",
                    "asset_name": "Asset Name",
                    "laptop_category": "Category",
                    "current_holder_name": "Current Holder",
                    "status": "Status",
                    "purchase_date": "Purchase Date",
                    "purchase_amount": "Purchase Amount",
                }
            )
            st.dataframe(view_df, use_container_width=True)

    elif view == "allocated":
        st.subheader("Allocated Laptops")
        df = get_allocated_laptops(snapshot_df)
        df = apply_search_filter(df, search_query)
        if df.empty:
            st.info("No laptops are currently allocated (or no match for current search).")
        else:
            view_df = df[
                [
                    "current_holder_name",
                    "asset_name",
                    "laptop_description",
                    "in_usage_from",
                    "laptop_category",
                    "purchase_amount",
                ]
            ].rename(
                columns={
                    "current_holder_name": "Employee Name",
                    "asset_name": "Laptop (Name)",
                    "laptop_description": "Laptop Description",
                    "in_usage_from": "In Usage From",
                    "laptop_category": "Laptop Category",
                    "purchase_amount": "Laptop Purchase Amount",
                }
            )
            st.dataframe(view_df, use_container_width=True)

    elif view == "stock":
        st.subheader("Laptops in Stock")
        df = get_laptops_in_stock(snapshot_df)
        df = apply_search_filter(df, search_query)
        if df.empty:
            st.info("No laptops currently in stock (or no match for current search).")
        else:
            view_df = df[
                [
                    "asset_id",
                    "asset_name",
                    "laptop_description",
                    "laptop_category",
                    "purchase_date",
                    "purchase_amount",
                ]
            ].rename(
                columns={
                    "asset_id": "Asset ID",
                    "asset_name": "Laptop (Name)",
                    "laptop_description": "Laptop Description",
                    "laptop_category": "Laptop Category",
                    "purchase_date": "Purchase Date",
                    "purchase_amount": "Laptop Purchase Amount",
                }
            )
            st.dataframe(view_df, use_container_width=True)
    else:
        st.info(
            "Click any dashboard card above to drill down — "
            "Total Assets, Allocated Laptops, or Laptops in Stock."
        )

# ---------------------- ASSETS ---------------------- #
elif menu == "Assets":
    st.subheader("Assets Overview")

    asset_filter = st.radio(
        "Asset Type",
        ["Laptops", "Office Equipment"],
        horizontal=True,
    )

    if asset_filter == "Laptops":
        df = get_assets_by_type(snapshot_df, "Laptop")
    else:
        df = get_assets_by_type(snapshot_df, "Office Equipment")

    df = apply_search_filter(df, search_query)

    if df.empty:
        st.info("No assets found for this type (or no match for current search).")
    else:
        view = df[
            [
                "asset_id",
                "current_holder_name",
                "asset_name",
                "laptop_description",
                "in_usage_from",
                "laptop_category",
                "purchase_amount",
                "status",
            ]
        ].rename(
            columns={
                "asset_id": "Asset ID",
                "current_holder_name": "Current Holder",
                "asset_name": "Asset Name",
                "laptop_description": "Description",
                "in_usage_from": "In Usage From",
                "laptop_category": "Category",
                "purchase_amount": "Purchase Amount",
                "status": "Status",
            }
        )
        st.dataframe(view, use_container_width=True)

        st.markdown("### Movement History")
        asset_ids = df["asset_id"].tolist()
        selected_asset = st.selectbox("Select Asset for History", asset_ids)
        if selected_asset:
            hist = get_movement_history(conn, selected_asset)
            if hist.empty:
                st.info("No movement history for this asset yet.")
            else:
                st.dataframe(hist, use_container_width=True)

# ---------------------- ADD ASSET ---------------------- #
elif menu == "Add Asset":
    st.subheader("Add New Asset")

    with st.form("add_asset_form"):
        c1, c2 = st.columns(2)
        with c1:
            asset_type = st.selectbox("Asset Type", ["Laptop", "Office Equipment"])
            asset_name = st.text_input("Asset Name")
            laptop_category = st.text_input("Category (e.g., Dev, Admin, Office)")
            purchase_date = st.date_input("Purchase Date", value=date.today())
        with c2:
            purchase_amount = st.number_input("Purchase Amount", min_value=0.0, step=1000.0)
            vendor_name = st.text_input("Vendor Name")
            invoice_no = st.text_input("Invoice No")
        laptop_description = st.text_area("Description / Specs")

        submitted = st.form_submit_button("Save Asset")
        if submitted:
            if not asset_name:
                st.error("Asset Name is required.")
            else:
                asset_id = add_asset(
                    conn,
                    asset_type,
                    asset_name,
                    laptop_category,
                    laptop_description,
                    purchase_date,
                    purchase_amount,
                    vendor_name,
                    invoice_no,
                )
                st.success(f"Asset added with ID **{asset_id}**")

# ---------------------- ALLOCATE ---------------------- #
elif menu == "Allocate":
    st.subheader("Allocate Asset to Employee")

    if snapshot_df.empty:
        st.info("No assets available. Add assets first from the **Add Asset** tab.")
    else:
        is_stock = snapshot_df["current_holder_type"].str.lower().eq("stock")
        stock_df = snapshot_df[is_stock].copy()

        if stock_df.empty:
            st.info("No in-stock assets available for allocation.")
        else:
            stock_df["label"] = stock_df["asset_id"] + " — " + stock_df["asset_name"].fillna("")
            asset_label = st.selectbox(
                "Select Asset (In Stock)",
                stock_df["label"].tolist(),
            )

            employees = get_employees(conn)
            emp_names = [e[1] for e in employees]
            emp_name = st.selectbox(
                "Employee Name",
                emp_names + ["<Type manually>"] if emp_names else ["<Type manually>"],
            )

            manual_emp = None
            if emp_name == "<Type manually>" or not emp_names:
                manual_emp = st.text_input("Employee Name (manual)")

            alloc_date = st.date_input("Allocation Date", value=date.today())
            if st.button("Allocate"):
                if not asset_label:
                    st.error("Select an asset.")
                else:
                    asset_id = asset_label.split(" — ")[0]
                    final_emp_name = manual_emp if manual_emp else emp_name
                    if not final_emp_name or final_emp_name == "<Type manually>":
                        st.error("Please provide an employee name.")
                    else:
                        try:
                            allocate_asset(conn, snapshot_df, asset_id, final_emp_name, alloc_date)
                            st.success(f"Asset **{asset_id}** allocated to **{final_emp_name}**")
                        except Exception as e:
                            st.error(str(e))

# ---------------------- RETURN / TRANSFER / SCRAP ---------------------- #
elif menu == "Return / Transfer / Scrap":
    st.subheader("Return / Transfer / Scrap Asset")

    if snapshot_df.empty:
        st.info("No assets available.")
    else:
        asset_ids = snapshot_df["asset_id"].tolist()
        asset_id = st.selectbox("Select Asset", asset_ids)

        action = st.selectbox("Action", ["Return", "Transfer", "Scrap"])
        move_date = st.date_input("Movement Date", value=date.today())
        new_emp = None

        if action == "Transfer":
            employees = get_employees(conn)
            emp_names = [e[1] for e in employees]
            emp_name = st.selectbox(
                "New Employee Name",
                emp_names + ["<Type manually>"] if emp_names else ["<Type manually>"],
            )
            manual_emp = None
            if emp_name == "<Type manually>" or not emp_names:
                manual_emp = st.text_input("New Employee (manual)")
            new_emp = manual_emp if manual_emp else emp_name

        remarks = st.text_area("Remarks", "")

        if st.button("Save Movement"):
            try:
                process_movement(conn, snapshot_df, asset_id, action.lower(), move_date, new_emp, remarks)
                st.success(f"Movement saved for **{asset_id}** ({action})")
            except Exception as e:
                st.error(str(e))

# ---------------------- EMPLOYEES ---------------------- #
elif menu == "Employees":
    st.subheader("Employees")

    with st.form("add_employee_form"):
        name = st.text_input("Employee Name")
        email = st.text_input("Email (optional)")
        submitted = st.form_submit_button("Add / Update")
        if submitted:
            if not name.strip():
                st.error("Name is required.")
            else:
                add_employee(conn, name.strip(), email.strip() or None)
                st.success("Employee added (or already existed).")

    employees = get_employees(conn)
    if employees:
        df_emp = pd.read_sql_query("SELECT name, email FROM employees ORDER BY name", conn)
        st.dataframe(df_emp, use_container_width=True)
    else:
        st.info("No employees saved yet. Add your team here and they will appear in allocation dropdowns.")
