#!/usr/bin/env python3
"""
Complete Law Firm Management App (Streamlit)
Includes: Dashboard, Clients, Cases, Hearings, Documents, Time & Billing,
Invoices, Calendar, Global Search, User Roles, and Settings.
"""

import os
import sys
import json
import sqlite3
import hashlib
import shutil
import logging
import datetime
from pathlib import Path
from datetime import date, timedelta
from io import BytesIO

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
# pyrefly: ignore [missing-import]
from streamlit_calendar import calendar
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

# ---------- Configuration ----------
DB_FILE = "law_firm.db"
CONFIG_DIR = Path.home() / ".case_mgmt"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = "law_firm.log"
PASSWORD_ENV_VAR = "CASE_MGMT_PASSWORD"
DOCUMENT_ROOT = Path("documents")
INVOICE_ROOT = Path("invoices")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("law_firm_app")

# Create directories
DOCUMENT_ROOT.mkdir(exist_ok=True)
INVOICE_ROOT.mkdir(exist_ok=True)

# ---------- Database & Schema ----------
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn

def create_tables(conn):
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            case_name TEXT NOT NULL,
            case_type TEXT,
            court TEXT,
            judge TEXT,
            opposing_counsel TEXT,
            filing_date DATE,
            status TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        );
        CREATE TABLE IF NOT EXISTS hearings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            hearing_date DATE NOT NULL,
            hearing_type TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (case_id) REFERENCES cases(id)
        );
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            description TEXT,
            upload_date DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY (case_id) REFERENCES cases(id)
        );
        CREATE TABLE IF NOT EXISTS time_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            entry_date DATE DEFAULT CURRENT_DATE,
            hours REAL NOT NULL,
            description TEXT,
            rate REAL,
            billable BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (case_id) REFERENCES cases(id)
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            invoice_number TEXT UNIQUE NOT NULL,
            invoice_date DATE NOT NULL,
            due_date DATE NOT NULL,
            total_amount REAL NOT NULL,
            paid BOOLEAN DEFAULT 0,
            pdf_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (case_id) REFERENCES cases(id)
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'staff',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # Insert default settings if not exists
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('firm_name', 'My Law Firm')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_rate', '150.0')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('next_invoice_number', '1')")
    # Create default admin user if no users exist
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_hash = hashlib.sha256("admin".encode()).hexdigest()
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                       ("admin", default_hash, "admin"))
        logger.info("Created default admin user (username: admin, password: admin)")
    conn.commit()

def get_next_invoice_number():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'next_invoice_number'")
    row = cursor.fetchone()
    num = int(row[0]) if row else 1
    conn.close()
    return num

def increment_invoice_number():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = value + 1 WHERE key = 'next_invoice_number'")
    conn.commit()
    conn.close()

# ---------- User & Password Management ----------
def authenticate_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash, role FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        if hashlib.sha256(password.encode()).hexdigest() == row["password_hash"]:
            return row["id"], row["role"]
    return None, None

def create_user(username, password, role="staff"):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                       (username, hashlib.sha256(password.encode()).hexdigest(), role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT id, username, role, created_at FROM users ORDER BY created_at", conn)
    conn.close()
    return df

# ---------- Helper Functions ----------
def get_setting(key, default=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row["value"]
    return default

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_client_name(client_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM clients WHERE id = ?", (client_id,))
    row = cursor.fetchone()
    conn.close()
    return row["name"] if row else "Unknown"

def get_case_name(case_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT case_name FROM cases WHERE id = ?", (case_id,))
    row = cursor.fetchone()
    conn.close()
    return row["case_name"] if row else "Unknown"

def get_total_billable(case_id, start_date=None, end_date=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT SUM(hours * rate) FROM time_entries WHERE case_id = ? AND billable = 1"
    params = [case_id]
    if start_date:
        query += " AND entry_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND entry_date <= ?"
        params.append(end_date)
    cursor.execute(query, params)
    row = cursor.fetchone()
    conn.close()
    return row[0] if row[0] else 0.0

def get_time_entries_for_invoice(case_id, start_date=None, end_date=None):
    conn = get_db_connection()
    query = """
        SELECT entry_date, hours, description, rate, (hours * rate) AS amount
        FROM time_entries
        WHERE case_id = ? AND billable = 1
    """
    params = [case_id]
    if start_date:
        query += " AND entry_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND entry_date <= ?"
        params.append(end_date)
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def generate_invoice_pdf(case_id, invoice_number, start_date=None, end_date=None):
    """Generate a PDF invoice and return the file path."""
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter

    # Get case and client info
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT case_name, client_id FROM cases WHERE id = ?", (case_id,))
    case = cursor.fetchone()
    client_name = get_client_name(case["client_id"])
    conn.close()

    # Get time entries
    df = get_time_entries_for_invoice(case_id, start_date, end_date)
    if df.empty:
        return None

    total = df["amount"].sum()
    # Build PDF
    pdf_file = INVOICE_ROOT / f"invoice_{invoice_number}.pdf"
    doc = SimpleDocTemplate(str(pdf_file), pagesize=letter)
    styles = getSampleStyleSheet()
    title_style = styles['Title']
    heading_style = styles['Heading2']
    normal_style = styles['Normal']

    story = []
    # Header
    firm = get_setting("firm_name", "My Law Firm")
    story.append(Paragraph(f"<b>{firm}</b>", title_style))
    story.append(Paragraph(f"Invoice #{invoice_number}", heading_style))
    story.append(Paragraph(f"Date: {date.today().strftime('%B %d, %Y')}", normal_style))
    story.append(Spacer(1, 0.2*inch))

    # Client & Case
    story.append(Paragraph(f"<b>Client:</b> {client_name}", normal_style))
    story.append(Paragraph(f"<b>Case:</b> {case['case_name']}", normal_style))
    if start_date and end_date:
        story.append(Paragraph(f"<b>Period:</b> {start_date} to {end_date}", normal_style))
    story.append(Spacer(1, 0.2*inch))

    # Table
    data = [["Date", "Description", "Hours", "Rate", "Amount"]]
    for _, row in df.iterrows():
        data.append([
            row["entry_date"],
            row["description"] or "",
            f"{row['hours']:.2f}",
            f"${row['rate']:.2f}",
            f"${row['amount']:.2f}"
        ])
    data.append(["", "", "", "Total", f"${total:.2f}"])

    table = Table(data, colWidths=[1.2*inch, 2.5*inch, 0.8*inch, 0.8*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('BACKGROUND', (0,1), (-1,-2), colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('ALIGN', (3,1), (3,-1), 'RIGHT'),
        ('ALIGN', (4,1), (4,-1), 'RIGHT'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]))
    story.append(table)

    # Build PDF
    doc.build(story)
    return pdf_file

# ---------- Streamlit App ----------
st.set_page_config(page_title="Law Firm Manager", layout="wide")
st.title("⚖️ Law Firm Management")

# Session state init
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "role" not in st.session_state:
    st.session_state.role = "staff"
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

# ----- Login (using username/password) -----
if not st.session_state.authenticated:
    st.subheader("🔐 Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username and password:
            user_id, role = authenticate_user(username, password)
            if user_id:
                st.session_state.authenticated = True
                st.session_state.user_id = user_id
                st.session_state.role = role
                st.session_state.username = username
                logger.info(f"User {username} logged in")
                st.rerun()
            else:
                st.error("Invalid username or password.")
        else:
            st.warning("Please enter username and password.")
    # Optional: show hint about default admin
    st.info("Default admin: username `admin`, password `admin`")
    st.stop()

# ----- Main App (authenticated) -----
# Sidebar navigation
st.sidebar.title("Navigation")
menu = ["Dashboard", "Clients", "Cases", "Hearings", "Documents", "Time & Billing",
        "Invoices", "Calendar", "Search", "Reports", "Settings"]
if st.session_state.role == "admin":
    menu.append("Users")
choice = st.sidebar.radio("Go to", menu, index=0)

if choice != st.session_state.page:
    st.session_state.page = choice
    st.rerun()

# Logout
if st.sidebar.button("Logout"):
    st.session_state.authenticated = False
    st.session_state.user_id = None
    st.session_state.role = "staff"
    st.rerun()

firm_name = get_setting("firm_name", "My Law Firm")
st.sidebar.markdown(f"**{firm_name}**")
st.sidebar.markdown(f"Logged in as: **{st.session_state.username}** ({st.session_state.role})")

# Helper functions for messages and permission checks
def show_success(msg):
    st.success(msg)

def show_error(msg):
    st.error(msg)

def is_admin():
    return st.session_state.role == "admin"

def is_staff():
    return st.session_state.role == "staff"

# ---------- Dashboard ----------
if st.session_state.page == "Dashboard":
    st.header("📊 Dashboard")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM clients")
    total_clients = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM cases")
    total_cases = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM cases WHERE status = 'active'")
    active_cases = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM hearings WHERE hearing_date >= date('now')")
    upcoming_hearings = cursor.fetchone()[0]
    conn.close()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Clients", total_clients)
    col2.metric("Total Cases", total_cases)
    col3.metric("Active Cases", active_cases)
    col4.metric("Upcoming Hearings", upcoming_hearings)

    st.subheader("Recent Cases")
    conn = get_db_connection()
    df_cases = pd.read_sql_query("""
        SELECT c.id, c.case_name, cl.name AS client, c.status, c.created_at
        FROM cases c
        JOIN clients cl ON c.client_id = cl.id
        ORDER BY c.created_at DESC LIMIT 5
    """, conn)
    if not df_cases.empty:
        st.dataframe(df_cases, use_container_width=True)
    else:
        st.info("No cases yet.")
    conn.close()

# ---------- Clients ----------
elif st.session_state.page == "Clients":
    st.header("👥 Clients")
    # Show full list with actions (staff can view, admin can edit/delete)
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT id, name, contact, email, phone FROM clients ORDER BY name", conn)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        selected_client = st.selectbox("Select a client to manage", df['id'].tolist(), format_func=lambda x: f"{x} - {df[df.id==x].iloc[0]['name']}")
        if selected_client:
            client_data = pd.read_sql_query("SELECT * FROM clients WHERE id = ?", conn, params=(selected_client,)).iloc[0]
            with st.expander("Client Details & Actions"):
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("Name", value=client_data["name"], disabled=is_staff(), key="edit_client_name")
                    contact = st.text_input("Contact", value=client_data["contact"] or "", disabled=is_staff(), key="edit_client_contact")
                with col2:
                    email = st.text_input("Email", value=client_data["email"] or "", disabled=is_staff(), key="edit_client_email")
                    phone = st.text_input("Phone", value=client_data["phone"] or "", disabled=is_staff(), key="edit_client_phone")
                address = st.text_area("Address", value=client_data["address"] or "", disabled=is_staff(), key="edit_client_address")
                notes = st.text_area("Notes", value=client_data["notes"] or "", disabled=is_staff(), key="edit_client_notes")
                if is_admin():
                    if st.button("Update Client"):
                        try:
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE clients SET name=?, contact=?, email=?, phone=?, address=?, notes=?
                                WHERE id=?
                            """, (name, contact, email, phone, address, notes, selected_client))
                            conn.commit()
                            logger.info(f"Updated client {selected_client}")
                            show_success("Client updated!")
                            st.rerun()
                        except Exception as e:
                            show_error(f"Error: {e}")
                    if st.button("Delete Client", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM cases WHERE client_id = ?", (selected_client,))
                        count = cursor.fetchone()[0]
                        if count > 0:
                            show_error(f"Cannot delete: client has {count} case(s).")
                        else:
                            if st.checkbox("I confirm deletion"):
                                cursor.execute("DELETE FROM clients WHERE id = ?", (selected_client,))
                                conn.commit()
                                logger.info(f"Deleted client {selected_client}")
                                show_success("Client deleted!")
                                st.rerun()
                else:
                    st.info("Staff: view-only mode. Contact admin for changes.")
    else:
        st.info("No clients found.")
    conn.close()

    if is_admin():
        st.subheader("Add New Client")
        with st.form("add_client_form"):
            name = st.text_input("Name *")
            contact = st.text_input("Contact")
            email = st.text_input("Email")
            phone = st.text_input("Phone")
            address = st.text_area("Address")
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Add Client")
            if submitted:
                if not name:
                    show_error("Name is required.")
                else:
                    try:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO clients (name, contact, email, phone, address, notes)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (name, contact, email, phone, address, notes))
                        conn.commit()
                        logger.info(f"Added client: {name}")
                        show_success("Client added!")
                        st.rerun()
                    except Exception as e:
                        show_error(f"Error: {e}")
                    finally:
                        conn.close()

# ---------- Cases ----------
elif st.session_state.page == "Cases":
    st.header("📁 Cases")
    tab1, tab2 = st.tabs(["List Cases", "Add Case"])

    with tab1:
        conn = get_db_connection()
        df = pd.read_sql_query("""
            SELECT c.id, c.case_name, cl.name AS client, c.status, c.case_type, c.filing_date
            FROM cases c
            JOIN clients cl ON c.client_id = cl.id
            ORDER BY c.id DESC
        """, conn)
        if not df.empty:
            st.dataframe(df, use_container_width=True)
            selected_case = st.selectbox("Select a case to view/manage", df['id'].tolist(), format_func=lambda x: f"{x} - {df[df.id==x].iloc[0]['case_name']}")
            if selected_case:
                case = pd.read_sql_query("SELECT * FROM cases WHERE id = ?", conn, params=(selected_case,)).iloc[0]
                client_name = get_client_name(case["client_id"])
                with st.expander(f"Case #{selected_case}: {case['case_name']}"):
                    st.markdown(f"**Client:** {client_name}")
                    st.markdown(f"**Type:** {case['case_type'] or 'N/A'}")
                    st.markdown(f"**Status:** {case['status']}")
                    st.markdown(f"**Court:** {case['court'] or 'N/A'}")
                    st.markdown(f"**Judge:** {case['judge'] or 'N/A'}")
                    st.markdown(f"**Opposing Counsel:** {case['opposing_counsel'] or 'N/A'}")
                    st.markdown(f"**Filing Date:** {case['filing_date'] or 'N/A'}")
                    st.markdown(f"**Description:** {case['description'] or 'N/A'}")
                    # Hearings, documents, time entries (view-only for staff)
                    st.subheader("Hearings")
                    hearings_df = pd.read_sql_query("SELECT id, hearing_date, hearing_type, notes FROM hearings WHERE case_id = ? ORDER BY hearing_date", conn, params=(selected_case,))
                    if not hearings_df.empty:
                        st.dataframe(hearings_df, use_container_width=True)
                    else:
                        st.write("No hearings.")
                    st.subheader("Documents")
                    docs_df = pd.read_sql_query("SELECT id, filename, description, upload_date FROM documents WHERE case_id = ?", conn, params=(selected_case,))
                    if not docs_df.empty:
                        st.dataframe(docs_df, use_container_width=True)
                    else:
                        st.write("No documents.")
                    st.subheader("Time Entries")
                    time_df = pd.read_sql_query("SELECT id, entry_date, hours, description, rate, billable FROM time_entries WHERE case_id = ? ORDER BY entry_date", conn, params=(selected_case,))
                    if not time_df.empty:
                        st.dataframe(time_df, use_container_width=True)
                        total = get_total_billable(selected_case)
                        st.metric("Total Billable", f"${total:,.2f}")
                    else:
                        st.write("No time entries.")
                    # Edit/Delete (admin only)
                    if is_admin():
                        with st.form("update_case_form"):
                            col1, col2 = st.columns(2)
                            with col1:
                                new_name = st.text_input("Case Name", value=case["case_name"])
                                new_type = st.text_input("Case Type", value=case["case_type"] or "")
                                new_court = st.text_input("Court", value=case["court"] or "")
                                new_judge = st.text_input("Judge", value=case["judge"] or "")
                            with col2:
                                new_opposing = st.text_input("Opposing Counsel", value=case["opposing_counsel"] or "")
                                new_filing = st.date_input("Filing Date", value=datetime.datetime.strptime(case["filing_date"], "%Y-%m-%d").date() if case["filing_date"] else None)
                                new_status = st.selectbox("Status", ["active", "pending", "closed", "archived"], index=["active","pending","closed","archived"].index(case["status"]))
                                new_desc = st.text_area("Description", value=case["description"] or "")
                            col3, col4 = st.columns(2)
                            with col3:
                                update_submit = st.form_submit_button("Update Case")
                            with col4:
                                delete_submit = st.form_submit_button("Delete Case", type="primary")
                            if update_submit:
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute("""
                                        UPDATE cases SET case_name=?, case_type=?, court=?, judge=?,
                                        opposing_counsel=?, filing_date=?, status=?, description=?
                                        WHERE id=?
                                    """, (new_name, new_type, new_court, new_judge, new_opposing,
                                          new_filing.strftime("%Y-%m-%d") if new_filing else None,
                                          new_status, new_desc, selected_case))
                                    conn.commit()
                                    logger.info(f"Updated case {selected_case}")
                                    show_success("Case updated!")
                                    st.rerun()
                                except Exception as e:
                                    show_error(f"Error: {e}")
                            if delete_submit:
                                if st.checkbox("I confirm deletion of this case and all related data"):
                                    try:
                                        cursor = conn.cursor()
                                        cursor.execute("DELETE FROM hearings WHERE case_id = ?", (selected_case,))
                                        cursor.execute("DELETE FROM documents WHERE case_id = ?", (selected_case,))
                                        cursor.execute("DELETE FROM time_entries WHERE case_id = ?", (selected_case,))
                                        cursor.execute("DELETE FROM cases WHERE id = ?", (selected_case,))
                                        conn.commit()
                                        logger.info(f"Deleted case {selected_case}")
                                        show_success("Case deleted!")
                                        st.rerun()
                                    except Exception as e:
                                        show_error(f"Error: {e}")
                    else:
                        st.info("Staff: view-only mode.")
        else:
            st.info("No cases found.")
        conn.close()

    with tab2:
        if is_admin():
            st.subheader("Add New Case")
            conn = get_db_connection()
            clients = pd.read_sql_query("SELECT id, name FROM clients ORDER BY name", conn)
            if clients.empty:
                st.warning("Please add a client first.")
            else:
                with st.form("add_case_form"):
                    client_id = st.selectbox("Client *", clients['id'].tolist(), format_func=lambda x: clients[clients.id==x].iloc[0]['name'])
                    case_name = st.text_input("Case Name *")
                    case_type = st.text_input("Case Type")
                    court = st.text_input("Court")
                    judge = st.text_input("Judge")
                    opposing = st.text_input("Opposing Counsel")
                    filing_date = st.date_input("Filing Date", value=date.today())
                    status = st.selectbox("Status", ["active", "pending", "closed", "archived"], index=0)
                    description = st.text_area("Description")
                    submitted = st.form_submit_button("Add Case")
                    if submitted:
                        if not case_name:
                            show_error("Case Name is required.")
                        else:
                            try:
                                cursor = conn.cursor()
                                cursor.execute("""
                                    INSERT INTO cases (client_id, case_name, case_type, court, judge,
                                    opposing_counsel, filing_date, status, description)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (client_id, case_name, case_type, court, judge, opposing,
                                      filing_date.strftime("%Y-%m-%d"), status, description))
                                conn.commit()
                                logger.info(f"Added case {case_name} for client {client_id}")
                                show_success("Case added!")
                                st.rerun()
                            except Exception as e:
                                show_error(f"Error: {e}")
            conn.close()
        else:
            st.info("Only admins can add cases.")

# ---------- Hearings ----------
elif st.session_state.page == "Hearings":
    st.header("🗓️ Hearings")
    tab1, tab2 = st.tabs(["View Hearings", "Add Hearing"])

    with tab1:
        conn = get_db_connection()
        upcoming_filter = st.checkbox("Show only upcoming")
        query = """
            SELECT h.id, h.hearing_date, h.hearing_type, h.notes,
                   c.case_name, cl.name AS client_name
            FROM hearings h
            JOIN cases c ON h.case_id = c.id
            JOIN clients cl ON c.client_id = cl.id
        """
        params = []
        if upcoming_filter:
            query += " WHERE h.hearing_date >= date('now')"
        query += " ORDER BY h.hearing_date"
        df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            st.dataframe(df, use_container_width=True)
            selected = st.selectbox("Select a hearing to edit/delete", df['id'].tolist(), format_func=lambda x: f"{x} - {df[df.id==x].iloc[0]['case_name']} ({df[df.id==x].iloc[0]['hearing_date']})")
            if selected:
                hearing = pd.read_sql_query("SELECT * FROM hearings WHERE id = ?", conn, params=(selected,)).iloc[0]
                with st.form("update_hearing_form"):
                    new_date = st.date_input("Hearing Date", value=datetime.datetime.strptime(hearing["hearing_date"], "%Y-%m-%d").date(), disabled=is_staff())
                    new_type = st.text_input("Hearing Type", value=hearing["hearing_type"] or "", disabled=is_staff())
                    new_notes = st.text_area("Notes", value=hearing["notes"] or "", disabled=is_staff())
                    if is_admin():
                        col1, col2 = st.columns(2)
                        with col1:
                            update_btn = st.form_submit_button("Update Hearing")
                        with col2:
                            delete_btn = st.form_submit_button("Delete Hearing", type="primary")
                        if update_btn:
                            try:
                                cursor = conn.cursor()
                                cursor.execute("""
                                    UPDATE hearings SET hearing_date=?, hearing_type=?, notes=?
                                    WHERE id=?
                                """, (new_date.strftime("%Y-%m-%d"), new_type, new_notes, selected))
                                conn.commit()
                                logger.info(f"Updated hearing {selected}")
                                show_success("Hearing updated!")
                                st.rerun()
                            except Exception as e:
                                show_error(f"Error: {e}")
                        if delete_btn:
                            try:
                                cursor = conn.cursor()
                                cursor.execute("DELETE FROM hearings WHERE id = ?", (selected,))
                                conn.commit()
                                logger.info(f"Deleted hearing {selected}")
                                show_success("Hearing deleted!")
                                st.rerun()
                            except Exception as e:
                                show_error(f"Error: {e}")
                    else:
                        st.info("Staff: view-only.")
        else:
            st.info("No hearings found.")
        conn.close()

    with tab2:
        if is_admin():
            conn = get_db_connection()
            cases = pd.read_sql_query("SELECT id, case_name FROM cases ORDER BY case_name", conn)
            if cases.empty:
                st.warning("Please add a case first.")
            else:
                with st.form("add_hearing_form"):
                    case_id = st.selectbox("Case", cases['id'].tolist(), format_func=lambda x: cases[cases.id==x].iloc[0]['case_name'])
                    hearing_date = st.date_input("Hearing Date", value=date.today())
                    hearing_type = st.selectbox("Hearing Type", ["Initial", "Status", "Motion", "Trial", "Other"])
                    notes = st.text_area("Notes")
                    submitted = st.form_submit_button("Add Hearing")
                    if submitted:
                        try:
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO hearings (case_id, hearing_date, hearing_type, notes)
                                VALUES (?, ?, ?, ?)
                            """, (case_id, hearing_date.strftime("%Y-%m-%d"), hearing_type, notes))
                            conn.commit()
                            logger.info(f"Added hearing for case {case_id}")
                            show_success("Hearing added!")
                            st.rerun()
                        except Exception as e:
                            show_error(f"Error: {e}")
            conn.close()
        else:
            st.info("Only admins can add hearings.")

# ---------- Documents ----------
elif st.session_state.page == "Documents":
    st.header("📄 Documents")
    if is_admin():
        conn = get_db_connection()
        cases = pd.read_sql_query("SELECT id, case_name FROM cases ORDER BY case_name", conn)
        if cases.empty:
            st.warning("No cases available.")
        else:
            with st.form("upload_document_form"):
                case_id = st.selectbox("Associate with Case", cases['id'].tolist(), format_func=lambda x: cases[cases.id==x].iloc[0]['case_name'])
                uploaded_file = st.file_uploader("Choose a file", type=["pdf", "docx", "doc", "txt", "jpg", "png", "xlsx"])
                description = st.text_input("Description (optional)")
                submitted = st.form_submit_button("Upload")
                if submitted and uploaded_file:
                    file_ext = Path(uploaded_file.name).suffix
                    safe_name = f"{case_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}{file_ext}"
                    file_path = DOCUMENT_ROOT / safe_name
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    try:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO documents (case_id, filename, filepath, description)
                            VALUES (?, ?, ?, ?)
                        """, (case_id, uploaded_file.name, str(file_path), description))
                        conn.commit()
                        logger.info(f"Uploaded document {uploaded_file.name} for case {case_id}")
                        show_success("File uploaded!")
                        st.rerun()
                    except Exception as e:
                        show_error(f"Error: {e}")
                elif submitted and not uploaded_file:
                    show_error("Please select a file.")
        conn.close()
    else:
        st.info("Only admins can upload documents.")

    # List documents (viewable by all)
    st.subheader("All Documents")
    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT d.id, d.filename, d.description, d.upload_date, c.case_name
        FROM documents d
        JOIN cases c ON d.case_id = c.id
        ORDER BY d.upload_date DESC
    """, conn)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        selected_doc = st.selectbox("Select a document to download or delete", df['id'].tolist(), format_func=lambda x: f"{x} - {df[df.id==x].iloc[0]['filename']}")
        if selected_doc:
            doc = pd.read_sql_query("SELECT filepath, filename FROM documents WHERE id = ?", conn, params=(selected_doc,)).iloc[0]
            with open(doc["filepath"], "rb") as f:
                st.download_button("Download", data=f, file_name=doc["filename"])
            if is_admin():
                if st.button("Delete Document", type="primary"):
                    try:
                        os.remove(doc["filepath"])
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM documents WHERE id = ?", (selected_doc,))
                        conn.commit()
                        logger.info(f"Deleted document {selected_doc}")
                        show_success("Document deleted!")
                        st.rerun()
                    except Exception as e:
                        show_error(f"Error: {e}")
    else:
        st.info("No documents uploaded.")
    conn.close()

# ---------- Time & Billing ----------
elif st.session_state.page == "Time & Billing":
    st.header("⏱️ Time & Billing")
    conn = get_db_connection()
    cases = pd.read_sql_query("SELECT id, case_name FROM cases ORDER BY case_name", conn)
    if cases.empty:
        st.warning("No cases available.")
    else:
        if is_admin():
            with st.form("add_time_entry"):
                case_id = st.selectbox("Case", cases['id'].tolist(), format_func=lambda x: cases[cases.id==x].iloc[0]['case_name'])
                entry_date = st.date_input("Date", value=date.today())
                hours = st.number_input("Hours", min_value=0.0, step=0.25, format="%.2f")
                description = st.text_input("Description")
                rate = st.number_input("Rate per hour (leave blank to use default)", value=float(get_setting("default_rate", 150.0)), step=1.0)
                billable = st.checkbox("Billable", value=True)
                submitted = st.form_submit_button("Log Time")
                if submitted and hours > 0:
                    try:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO time_entries (case_id, entry_date, hours, description, rate, billable)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (case_id, entry_date.strftime("%Y-%m-%d"), hours, description, rate, int(billable)))
                        conn.commit()
                        logger.info(f"Logged {hours}h for case {case_id}")
                        show_success("Time entry added!")
                        st.rerun()
                    except Exception as e:
                        show_error(f"Error: {e}")
                elif submitted:
                    show_error("Please enter hours > 0.")
        else:
            st.info("Staff: view-only. Contact admin to log time.")

        # Summary per case
        st.subheader("Summary per Case")
        summary = pd.read_sql_query("""
            SELECT c.id, c.case_name,
                   SUM(t.hours) AS total_hours,
                   SUM(t.hours * t.rate) AS total_billable
            FROM cases c
            LEFT JOIN time_entries t ON c.id = t.case_id AND t.billable = 1
            GROUP BY c.id
            ORDER BY c.case_name
        """, conn)
        if not summary.empty:
            st.dataframe(summary, use_container_width=True)
        else:
            st.info("No time entries yet.")
    conn.close()

# ---------- Invoices ----------
elif st.session_state.page == "Invoices":
    st.header("🧾 Invoices")
    if is_admin():
        # Generate new invoice
        st.subheader("Generate New Invoice")
        conn = get_db_connection()
        cases = pd.read_sql_query("SELECT id, case_name FROM cases ORDER BY case_name", conn)
        if not cases.empty:
            case_id = st.selectbox("Select Case", cases['id'].tolist(), format_func=lambda x: cases[cases.id==x].iloc[0]['case_name'])
            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("Start Date (optional)", value=None)
            with col2:
                end_date = st.date_input("End Date (optional)", value=None)
            if st.button("Preview Invoice"):
                df = get_time_entries_for_invoice(case_id, start_date, end_date)
                if df.empty:
                    st.warning("No billable time entries for this period.")
                else:
                    total = df["amount"].sum()
                    st.dataframe(df, use_container_width=True)
                    st.metric("Total Amount", f"${total:,.2f}")
            if st.button("Generate Invoice PDF"):
                # Generate invoice number
                inv_num = get_next_invoice_number()
                invoice_number = f"INV-{datetime.datetime.now().strftime('%Y%m')}-{inv_num:04d}"
                pdf_path = generate_invoice_pdf(case_id, invoice_number, start_date, end_date)
                if pdf_path:
                    # Save invoice record
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    total = get_total_billable(case_id, start_date, end_date)
                    due_date = date.today() + timedelta(days=30)
                    cursor.execute("""
                        INSERT INTO invoices (case_id, invoice_number, invoice_date, due_date, total_amount, pdf_path)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (case_id, invoice_number, date.today().isoformat(), due_date.isoformat(), total, str(pdf_path)))
                    conn.commit()
                    conn.close()
                    increment_invoice_number()
                    show_success(f"Invoice {invoice_number} generated!")
                    st.rerun()
                else:
                    show_error("No billable entries; invoice not generated.")
        conn.close()

    # List existing invoices
    st.subheader("Invoice History")
    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT i.id, i.invoice_number, i.invoice_date, i.due_date, i.total_amount, i.paid,
               c.case_name, cl.name AS client_name
        FROM invoices i
        JOIN cases c ON i.case_id = c.id
        JOIN clients cl ON c.client_id = cl.id
        ORDER BY i.invoice_date DESC
    """, conn)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
        selected_inv = st.selectbox("Select an invoice to download/update", df['id'].tolist(),
                                    format_func=lambda x: f"{x} - {df[df.id==x].iloc[0]['invoice_number']} ({df[df.id==x].iloc[0]['client_name']})")
        if selected_inv:
            inv = pd.read_sql_query("SELECT * FROM invoices WHERE id = ?", conn, params=(selected_inv,)).iloc[0]
            # Download PDF
            if inv["pdf_path"] and Path(inv["pdf_path"]).exists():
                with open(inv["pdf_path"], "rb") as f:
                    st.download_button("Download PDF", data=f, file_name=f"{inv['invoice_number']}.pdf")
            else:
                st.warning("PDF file not found.")
            if is_admin():
                # Toggle paid status
                paid_status = st.checkbox("Paid", value=bool(inv["paid"]), key="paid_check")
                if paid_status != bool(inv["paid"]):
                    if st.button("Update Payment Status"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE invoices SET paid = ? WHERE id = ?", (int(paid_status), selected_inv))
                        conn.commit()
                        logger.info(f"Updated invoice {selected_inv} paid={paid_status}")
                        show_success("Payment status updated!")
                        st.rerun()
    else:
        st.info("No invoices generated yet.")
    conn.close()

# ---------- Calendar ----------
elif st.session_state.page == "Calendar":
    st.header("📅 Calendar View")
    conn = get_db_connection()
    # Fetch hearings
    df = pd.read_sql_query("""
        SELECT h.id, h.hearing_date, h.hearing_type, h.notes,
               c.case_name, cl.name AS client_name
        FROM hearings h
        JOIN cases c ON h.case_id = c.id
        JOIN clients cl ON c.client_id = cl.id
        ORDER BY h.hearing_date
    """, conn)
    conn.close()

    if not df.empty:
        # Convert to format for streamlit-calendar: list of events
        events = []
        for _, row in df.iterrows():
            events.append({
                "title": f"{row['case_name'][:20]}",
                "start": row["hearing_date"],
                "end": row["hearing_date"],
                "resourceId": "hearing",
                "id": str(row["id"])
            })
        # Use calendar component
        calendar_options = {
            "editable": False,
            "selectable": True,
            "headerToolbar": {
                "left": "today prev,next",
                "center": "title",
                "right": "dayGridMonth,timeGridWeek,timeGridDay",
            },
            "slotMinTime": "06:00:00",
            "slotMaxTime": "20:00:00",
            "initialView": "dayGridMonth",
        }
        custom_css = """
            .fc-event-past { opacity: 0.8; }
            .fc-event-time { font-weight: bold; }
        """
        cal = calendar(events=events, options=calendar_options, custom_css=custom_css)
        st.markdown("Click on a hearing date to see details below.")
        # Show details for selected date? The calendar returns selected date; we can display hearings for that day.
        # Since calendar returns a dict, we can extract selected date if any.
        # For simplicity, we'll show all hearings in a table as well.
        st.subheader("All Hearings")
        st.dataframe(df[["hearing_date", "case_name", "client_name", "hearing_type", "notes"]], use_container_width=True)
    else:
        st.info("No hearings to display.")

# ---------- Search ----------
elif st.session_state.page == "Search":
    st.header("🔎 Global Search")
    query = st.text_input("Enter search term")
    if query and len(query) >= 2:
        term = f"%{query}%"
        conn = get_db_connection()
        # Search clients
        clients = pd.read_sql_query("""
            SELECT id, name, contact, email, phone, 'Client' AS type
            FROM clients
            WHERE name LIKE ? OR contact LIKE ? OR email LIKE ? OR phone LIKE ?
        """, conn, params=(term, term, term, term))
        # Search cases
        cases = pd.read_sql_query("""
            SELECT c.id, c.case_name, cl.name AS client, c.description, 'Case' AS type
            FROM cases c
            JOIN clients cl ON c.client_id = cl.id
            WHERE c.case_name LIKE ? OR c.description LIKE ?
        """, conn, params=(term, term))
        # Search hearings
        hearings = pd.read_sql_query("""
            SELECT h.id, h.hearing_date, h.notes, c.case_name, 'Hearing' AS type
            FROM hearings h
            JOIN cases c ON h.case_id = c.id
            WHERE h.notes LIKE ?
        """, conn, params=(term,))
        # Search documents
        docs = pd.read_sql_query("""
            SELECT d.id, d.filename, d.description, c.case_name, 'Document' AS type
            FROM documents d
            JOIN cases c ON d.case_id = c.id
            WHERE d.filename LIKE ? OR d.description LIKE ?
        """, conn, params=(term, term))
        conn.close()

        if clients.empty and cases.empty and hearings.empty and docs.empty:
            st.info("No results found.")
        else:
            if not clients.empty:
                st.subheader("Clients")
                st.dataframe(clients[["name", "contact", "email", "phone"]], use_container_width=True)
            if not cases.empty:
                st.subheader("Cases")
                st.dataframe(cases[["case_name", "client", "description"]], use_container_width=True)
            if not hearings.empty:
                st.subheader("Hearings")
                st.dataframe(hearings[["case_name", "hearing_date", "notes"]], use_container_width=True)
            if not docs.empty:
                st.subheader("Documents")
                st.dataframe(docs[["case_name", "filename", "description"]], use_container_width=True)
    elif query:
        st.warning("Please enter at least 2 characters.")

# ---------- Reports ----------
elif st.session_state.page == "Reports":
    st.header("📈 Reports")
    conn = get_db_connection()

    st.subheader("Cases by Status")
    status_df = pd.read_sql_query("SELECT status, COUNT(*) AS count FROM cases GROUP BY status", conn)
    if not status_df.empty:
        fig = px.pie(status_df, values='count', names='status', title='Case Status Distribution')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No cases.")

    st.subheader("Upcoming Hearings (Next 30 Days)")
    upcoming_df = pd.read_sql_query("""
        SELECT h.hearing_date, c.case_name, cl.name AS client
        FROM hearings h
        JOIN cases c ON h.case_id = c.id
        JOIN clients cl ON c.client_id = cl.id
        WHERE h.hearing_date BETWEEN date('now') AND date('now', '+30 days')
        ORDER BY h.hearing_date
    """, conn)
    if not upcoming_df.empty:
        st.dataframe(upcoming_df, use_container_width=True)
    else:
        st.info("No upcoming hearings in the next 30 days.")

    st.subheader("Top Clients by Case Count")
    client_cases = pd.read_sql_query("""
        SELECT cl.name, COUNT(c.id) AS case_count
        FROM clients cl
        LEFT JOIN cases c ON cl.id = c.client_id
        GROUP BY cl.id
        ORDER BY case_count DESC
        LIMIT 10
    """, conn)
    if not client_cases.empty:
        fig = px.bar(client_cases, x='name', y='case_count', title='Clients by Number of Cases')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data.")

    st.subheader("Billable Summary")
    billing = pd.read_sql_query("""
        SELECT c.case_name, SUM(t.hours) AS hours, SUM(t.hours * t.rate) AS amount
        FROM cases c
        LEFT JOIN time_entries t ON c.id = t.case_id AND t.billable = 1
        GROUP BY c.id
        ORDER BY amount DESC
    """, conn)
    if not billing.empty:
        st.dataframe(billing, use_container_width=True)
    else:
        st.info("No billable entries.")
    conn.close()

# ---------- Settings ----------
elif st.session_state.page == "Settings":
    st.header("⚙️ Settings")
    with st.form("settings_form"):
        firm = st.text_input("Firm Name", value=get_setting("firm_name", "My Law Firm"))
        default_rate = st.number_input("Default Hourly Rate ($)", value=float(get_setting("default_rate", 150.0)), step=1.0)
        submitted = st.form_submit_button("Save Settings")
        if submitted:
            set_setting("firm_name", firm)
            set_setting("default_rate", str(default_rate))
            show_success("Settings saved!")
            st.rerun()
    st.info("Password can be changed by a user with admin rights via the Users page.")

# ---------- Users (Admin only) ----------
elif st.session_state.page == "Users":
    if not is_admin():
        st.error("You do not have permission to access this page.")
        st.stop()
    st.header("👤 User Management")
    users_df = get_all_users()
    st.dataframe(users_df, use_container_width=True)

    # Add new user
    with st.form("add_user_form"):
        new_username = st.text_input("New Username")
        new_password = st.text_input("New Password", type="password")
        new_role = st.selectbox("Role", ["admin", "staff"])
        submitted = st.form_submit_button("Add User")
        if submitted:
            if new_username and new_password:
                if create_user(new_username, new_password, new_role):
                    show_success(f"User {new_username} added.")
                    st.rerun()
                else:
                    show_error("Username already exists.")
            else:
                show_error("Username and password required.")

    # Delete user (cannot delete self)
    st.subheader("Delete User")
    users = get_all_users()
    user_options = {f"{row['username']} ({row['role']})": row['id'] for _, row in users.iterrows() if row['id'] != st.session_state.user_id}
    if user_options:
        selected_user_label = st.selectbox("Select user to delete", list(user_options.keys()))
        selected_user_id = user_options[selected_user_label]
        if st.button("Delete User", type="primary"):
            if st.checkbox("I confirm deletion"):
                delete_user(selected_user_id)
                show_success("User deleted.")
                st.rerun()
    else:
        st.info("No other users to delete.")