
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
    # ----------------------------------------------------------
# Gradio UI
# ----------------------------------------------------------
STATUSES   = ["open", "in_progress", "resolved"]
PRIORITIES = ["low", "medium", "high", "critical"]
CATEGORIES = ["general", "bug", "feature", "billing", "security"]

with gr.Blocks(title="Support Ticket System") as demo:

    gr.Markdown("# 🎫 Support Ticket System")

    # ── Tab 1: View All Tickets ──────────────────────────
    with gr.Tab("📋 All Tickets"):
        with gr.Row():
            status_filter = gr.Dropdown(
                choices=["All"] + STATUSES,
                value="All",
                label="Filter by Status",
                scale=1,
            )
            refresh_btn = gr.Button("🔄 Refresh", variant="primary", scale=1)

        tickets_table = gr.Dataframe(
            headers=["ID", "Title", "Status", "Priority", "Category", "Created By", "Created At"],
            interactive=False,
            wrap=True,
        )
        refresh_btn.click(fn=fetch_tickets, inputs=status_filter, outputs=tickets_table)
        status_filter.change(fn=fetch_tickets, inputs=status_filter, outputs=tickets_table)

    # ── Tab 2: View Messages ─────────────────────────────
    with gr.Tab("💬 View Messages"):
        gr.Markdown("Enter a Ticket ID from the All Tickets tab.")
        msg_ticket_id = gr.Number(label="Ticket ID", precision=0, minimum=1)
        view_btn      = gr.Button("Load Messages", variant="primary")
        msg_status    = gr.Textbox(label="Status", interactive=False)
        messages_out  = gr.Dataframe(
            headers=["Author", "Message", "Sent At"],
            interactive=False,
            wrap=True,
        )
        view_btn.click(
            fn=fetch_messages,
            inputs=msg_ticket_id,
            outputs=[messages_out, msg_status],
        )

    # ── Tab 3: Create Ticket ─────────────────────────────
    with gr.Tab("➕ Create Ticket"):
        new_title    = gr.Textbox(label="Title *", placeholder="Brief description of the issue")
        with gr.Row():
            new_author   = gr.Textbox(label="Your Email *", placeholder="you@example.com", scale=2)
            new_priority = gr.Dropdown(choices=PRIORITIES, value="medium", label="Priority", scale=1)
            new_category = gr.Dropdown(choices=CATEGORIES, value="general", label="Category", scale=1)
        create_btn = gr.Button("Create Ticket", variant="primary")
        create_out = gr.Textbox(label="Result", interactive=False)
        gr.Markdown("_* Required fields_")
        create_btn.click(
            fn=create_ticket,
            inputs=[new_title, new_author, new_priority, new_category],
            outputs=create_out,
        )

    # ── Tab 4: Add Message ───────────────────────────────
    with gr.Tab("✉️ Add Message"):
        with gr.Row():
            am_ticket_id = gr.Number(label="Ticket ID *", precision=0, minimum=1, scale=1)
            am_author    = gr.Textbox(label="Your Email *", placeholder="you@example.com", scale=2)
        am_message = gr.Textbox(label="Message *", lines=4, placeholder="Type your message...")
        am_btn     = gr.Button("Send Message", variant="primary")
        am_out     = gr.Textbox(label="Result", interactive=False)
        gr.Markdown("_* Required fields_")
        am_btn.click(
            fn=add_message,
            inputs=[am_ticket_id, am_author, am_message],
            outputs=am_out,
        )

    # ── Tab 5: Update Status ─────────────────────────────
    with gr.Tab("🔄 Update Status"):
        with gr.Row():
            us_ticket_id = gr.Number(label="Ticket ID", precision=0, minimum=1, scale=1)
            us_status    = gr.Dropdown(choices=STATUSES, label="New Status", scale=1)
        us_btn = gr.Button("Update Status", variant="primary")
        us_out = gr.Textbox(label="Result", interactive=False)
        us_btn.click(
            fn=update_status,
            inputs=[us_ticket_id, us_status],
            outputs=us_out,
        )

demo.launch()
