
import os
import gradio as gr
from databricks import sql
from datetime import datetime, timezone

# ----------------------------------------------------------
# Connection
# ----------------------------------------------------------
def get_conn():
    return sql.connect(
        server_hostname = os.environ["DATABRICKS_HOST"],
        http_path       = os.environ["DATABRICKS_HTTP_PATH"],
        access_token    = os.environ["DATABRICKS_TOKEN"],
    )

def now():
    return datetime.now(timezone.utc)

# ----------------------------------------------------------
# ID generators (no auto-increment in Delta)
# ----------------------------------------------------------
def next_ticket_id(cur):
    cur.execute("SELECT COALESCE(MAX(ticket_id), 0) + 1 FROM ticketing_system.tickets")
    return cur.fetchone()[0]

def next_message_id(cur):
    cur.execute("SELECT COALESCE(MAX(message_id), 0) + 1 FROM ticketing_system.ticket_messages")
    return cur.fetchone()[0]

# ----------------------------------------------------------
# Validation
# ----------------------------------------------------------
def validate_email(email):
    e = email.strip()
    if not e:
        return "Email is required."
    if "@" not in e or "." not in e.split("@")[-1]:
        return f"'{e}' is not a valid email."
    return None

def validate_required(value, field):
    if not value.strip():
        return f"{field} is required."
    if len(value.strip()) < 3:
        return f"{field} must be at least 3 characters."
    return None

def validate_ticket_exists(ticket_id):
    try:
        tid = int(ticket_id)
        if tid <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return "Ticket ID must be a positive number."
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM ticketing_system.tickets WHERE ticket_id = ?", [tid]
            )
            if not cur.fetchone():
                return f"No ticket found with ID {tid}."
    return None

# ----------------------------------------------------------
# Database functions
# ----------------------------------------------------------
def fetch_tickets(status_filter="All"):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if status_filter == "All":
                cur.execute("""
                    SELECT ticket_id, title, status, priority, category, created_by, created_at
                    FROM ticketing_system.tickets
                    ORDER BY created_at DESC
                """)
            else:
                cur.execute("""
                    SELECT ticket_id, title, status, priority, category, created_by, created_at
                    FROM ticketing_system.tickets
                    WHERE status = ?
                    ORDER BY created_at DESC
                """, [status_filter])
            return cur.fetchall()

def fetch_messages(ticket_id):
    err = validate_ticket_exists(ticket_id)
    if err:
        return [], f"❌ {err}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT author, message_text, created_at
                FROM ticketing_system.ticket_messages
                WHERE ticket_id = ?
                ORDER BY created_at ASC
            """, [int(ticket_id)])
            rows = cur.fetchall()
    if not rows:
        return [], "ℹ️ No messages yet for this ticket."
    return rows, f"✅ {len(rows)} message(s) loaded."

def create_ticket(title, created_by, priority, category):
    errors = []
    err = validate_required(title, "Title");
    if err: errors.append(err)
    err = validate_email(created_by)
    if err: errors.append(err)
    if errors:
        return "❌ " + " | ".join(errors)
    with get_conn() as conn:
        with conn.cursor() as cur:
            tid = next_ticket_id(cur)
            cur.execute("""
                INSERT INTO ticketing_system.tickets
                    (ticket_id, title, status, priority, category, created_by, created_at)
                VALUES (?, ?, 'open', ?, ?, ?, ?)
            """, [tid, title.strip(), priority, category, created_by.strip(), now()])
    return f"✅ Ticket created! ID: {tid} | Title: {title.strip()} | Priority: {priority}"

def add_message(ticket_id, author, message_text):
    errors = []
    err = validate_ticket_exists(ticket_id)
    if err: errors.append(err)
    err = validate_email(author)
    if err: errors.append(err)
    err = validate_required(message_text, "Message")
    if err: errors.append(err)
    if errors:
        return "❌ " + " | ".join(errors)
    with get_conn() as conn:
        with conn.cursor() as cur:
            mid = next_message_id(cur)
            cur.execute("""
                INSERT INTO ticketing_system.ticket_messages
                    (message_id, ticket_id, message_text, author, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, [mid, int(ticket_id), message_text.strip(), author.strip(), now()])
    return f"✅ Message added to ticket {int(ticket_id)}."

def update_status(ticket_id, new_status):
    err = validate_ticket_exists(ticket_id)
    if err:
        return f"❌ {err}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE ticketing_system.tickets
                SET status = ?
                WHERE ticket_id = ?
            """, [new_status, int(ticket_id)])
    return f"✅ Ticket {int(ticket_id)} status updated to '{new_status}'."
