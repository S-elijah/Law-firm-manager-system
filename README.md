# ⚖️ Law Firm Management System

A complete, web‑based case management application for small law firms. Built with **Streamlit**, **SQLite**, and **Plotly**.

![Streamlit](https://img.shields.io/badge/Streamlit-1.28-FF4B4B?style=flat&logo=streamlit)
![Python](https://img.shields.io/badge/Python-3.9+-blue?style=flat&logo=python)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Features

- **Dashboard** – key metrics (clients, cases, upcoming hearings) and recent activity.
- **Client Management** – add, edit, delete, and search clients.
- **Case Management** – full CRUD with fields: type, court, judge, opposing counsel, filing date, status.
- **Hearings** – add, edit, delete; filter upcoming; interactive calendar view.
- **Document Upload** – associate files with cases; download and delete documents.
- **Time & Billing** – log hours per case with rate; view billable totals.
- **Invoice Generation** – create PDF invoices from billable time entries; track payments.
- **Calendar** – interactive month/week/day view of all hearings (using `streamlit-calendar`).
- **Global Search** – one search box across clients, cases, hearings, and documents.
- **User Roles** – `admin` (full CRUD) and `staff` (view‑only) with separate logins.
- **User Management** – admin can add/delete users.
- **Reports** – case status pie chart, upcoming hearings, top clients, billing summary.
- **Settings** – configure firm name and default hourly rate.

---

## 🛠️ Technology Stack

| Component | Technology |
|-----------|------------|
| Frontend / UI | [Streamlit](https://streamlit.io/) |
| Database | SQLite (local) |
| Charts | Matplotlib, Plotly |
| Calendar | [streamlit-calendar](https://github.com/imxiaoyu/streamlit-calendar) |
| PDF generation | ReportLab |
| Authentication | custom (username/password hashed) |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.9 or higher
- Git (optional, for cloning)
