import sqlite3
import os

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Billing")
os.makedirs(APP_DIR, exist_ok=True)
DB_PATH = os.path.join(APP_DIR, "billing.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn, table, column):
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL CHECK(category IN ('income', 'expense')),
            is_recurring INTEGER NOT NULL DEFAULT 0,
            is_active   INTEGER NOT NULL DEFAULT 1,
            start_month TEXT    NOT NULL,
            end_month   TEXT,
            date        TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS amount_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            amount          REAL    NOT NULL,
            effective_month TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checked_items (
            item_id     INTEGER NOT NULL,
            month       TEXT    NOT NULL,
            is_checked  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (item_id, month),
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
    """)
    if not _column_exists(conn, "items", "date"):
        conn.execute("ALTER TABLE items ADD COLUMN date TEXT")
    conn.commit()
    conn.close()


def add_item(name, amount, category, is_recurring, start_month, date=None):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO items (name, amount, category, is_recurring, start_month, date) VALUES (?, ?, ?, ?, ?, ?)",
        (name, amount, category, int(is_recurring), start_month, date),
    )
    if is_recurring:
        conn.execute(
            "INSERT INTO amount_history (item_id, amount, effective_month) VALUES (?, ?, ?)",
            (cursor.lastrowid, amount, start_month),
        )
    conn.commit()
    conn.close()


def update_recurring_amount(item_id, new_amount, effective_month, only_this_month=False):
    conn = get_connection()

    old_amount_row = conn.execute(
        """SELECT amount FROM amount_history
           WHERE item_id = ? AND effective_month <= ?
           ORDER BY effective_month DESC, id DESC LIMIT 1""",
        (item_id, effective_month),
    ).fetchone()
    old_amount = old_amount_row["amount"] if old_amount_row else None

    conn.execute(
        "DELETE FROM amount_history WHERE item_id = ? AND effective_month = ?",
        (item_id, effective_month),
    )

    conn.execute(
        "INSERT INTO amount_history (item_id, amount, effective_month) VALUES (?, ?, ?)",
        (item_id, new_amount, effective_month),
    )

    if only_this_month and old_amount is not None:
        next_month = _next_month(effective_month)
        existing = conn.execute(
            "SELECT id FROM amount_history WHERE item_id = ? AND effective_month = ?",
            (item_id, next_month),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO amount_history (item_id, amount, effective_month) VALUES (?, ?, ?)",
                (item_id, old_amount, next_month),
            )

    conn.execute(
        "UPDATE items SET amount = ? WHERE id = ?",
        (new_amount, item_id),
    )
    conn.commit()
    conn.close()


def _next_month(month_str):
    y, m = map(int, month_str.split("-"))
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


def deactivate_item(item_id, end_month):
    conn = get_connection()
    conn.execute(
        "UPDATE items SET is_active = 0, end_month = ? WHERE id = ?",
        (end_month, item_id),
    )
    conn.commit()
    conn.close()


def activate_item(item_id):
    conn = get_connection()
    conn.execute(
        "UPDATE items SET is_active = 1, end_month = NULL WHERE id = ?",
        (item_id,),
    )
    conn.commit()
    conn.close()


def delete_item(item_id):
    conn = get_connection()
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def update_item_name(item_id, new_name):
    conn = get_connection()
    conn.execute("UPDATE items SET name = ? WHERE id = ?", (new_name, item_id))
    conn.commit()
    conn.close()


def update_item_date(item_id, new_date):
    conn = get_connection()
    conn.execute("UPDATE items SET date = ? WHERE id = ?", (new_date, item_id))
    conn.commit()
    conn.close()


def set_checked(item_id, month, checked):
    conn = get_connection()
    conn.execute(
        "INSERT INTO checked_items (item_id, month, is_checked) VALUES (?, ?, ?)"
        " ON CONFLICT(item_id, month) DO UPDATE SET is_checked = excluded.is_checked",
        (item_id, month, int(checked)),
    )
    conn.commit()
    conn.close()


def get_items_for_month(month_str):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT i.*,
               CASE
                   WHEN i.is_recurring = 1 THEN
                       COALESCE(
                           (SELECT ah.amount FROM amount_history ah
                            WHERE ah.item_id = i.id AND ah.effective_month <= ?
                            ORDER BY ah.effective_month DESC, ah.id DESC LIMIT 1),
                           i.amount
                       )
                   ELSE i.amount
               END AS effective_amount,
               COALESCE(c.is_checked, 0) AS is_checked
        FROM items i
        LEFT JOIN checked_items c ON c.item_id = i.id AND c.month = ?
        WHERE (i.is_recurring = 1 AND i.start_month <= ? AND (i.end_month IS NULL OR i.end_month >= ?))
           OR (i.is_recurring = 0 AND i.start_month = ?)
        """,
        (month_str, month_str, month_str, month_str, month_str),
    ).fetchall()
    conn.close()
    return rows
