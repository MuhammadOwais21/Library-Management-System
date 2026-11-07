"""
Database layer for the Library Management System.

All persistence goes through SQLite (sqlite3). Dates are stored as ISO
strings (YYYY-MM-DD) so they sort and compare correctly as text.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

DB_PATH = os.environ.get(
    "LIBRARY_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.db"),
)

MEMBER_TYPES = ("Student", "Teacher")
BORROW_LIMITS = {"Student": 3, "Teacher": 5}

# Defaults the librarian can change on the Settings page.
DEFAULT_SETTINGS = {
    "loan_days": "14",      # days a book may be kept before it is overdue
    "fine_per_day": "10",   # fine charged per day late
    "currency": "Rs.",      # label shown next to fine amounts
}


class LibraryError(Exception):
    """Raised for rule violations the UI should show to the librarian."""


# --------------------------------------------------------------------------
# Connection and schema
# --------------------------------------------------------------------------

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL,
    author           TEXT    NOT NULL,
    isbn             TEXT    UNIQUE,
    category         TEXT,
    total_copies     INTEGER NOT NULL CHECK (total_copies >= 1),
    available_copies INTEGER NOT NULL CHECK (available_copies >= 0),
    added_on         TEXT    NOT NULL,
    CHECK (available_copies <= total_copies)
);

CREATE TABLE IF NOT EXISTS members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    member_type TEXT NOT NULL CHECK (member_type IN ('Student', 'Teacher')),
    email       TEXT UNIQUE,
    phone       TEXT,
    joined_on   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id     INTEGER NOT NULL REFERENCES books(id)   ON DELETE CASCADE,
    member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    issue_date  TEXT    NOT NULL,
    due_date    TEXT    NOT NULL,
    return_date TEXT,
    fine        REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_issues_open ON issues(return_date);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _to_date(value):
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _clean(text):
    text = (text or "").strip()
    return text or None


def calculate_fine(due_date, return_date, fine_per_day):
    """Fine = days late x fine per day. Returning on or before the due date costs nothing."""
    days_late = (_to_date(return_date) - _to_date(due_date)).days
    return max(0, days_late) * float(fine_per_day)


def days_overdue(due_date, as_of=None):
    as_of = _to_date(as_of or date.today())
    return max(0, (as_of - _to_date(due_date)).days)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def get_settings():
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(DEFAULT_SETTINGS)
    settings.update({r["key"]: r["value"] for r in rows})
    return {
        "loan_days": int(settings["loan_days"]),
        "fine_per_day": float(settings["fine_per_day"]),
        "currency": settings["currency"],
    }


def update_settings(loan_days, fine_per_day, currency):
    if int(loan_days) < 1:
        raise LibraryError("Loan period must be at least 1 day.")
    if float(fine_per_day) < 0:
        raise LibraryError("Fine per day cannot be negative.")
    with get_conn() as conn:
        for key, value in (
            ("loan_days", str(int(loan_days))),
            ("fine_per_day", str(float(fine_per_day))),
            ("currency", (currency or "").strip() or "Rs."),
        ):
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


# --------------------------------------------------------------------------
# Books
# --------------------------------------------------------------------------

def add_book(title, author, copies=1, isbn=None, category=None):
    title, author = _clean(title), _clean(author)
    if not title or not author:
        raise LibraryError("Title and author are required.")
    copies = int(copies)
    if copies < 1:
        raise LibraryError("Number of copies must be at least 1.")
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO books (title, author, isbn, category, total_copies, "
                "available_copies, added_on) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, author, _clean(isbn), _clean(category), copies, copies,
                 date.today().isoformat()),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        raise LibraryError(f"A book with ISBN '{isbn}' already exists.")


def delete_book(book_id):
    with get_conn() as conn:
        book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if book is None:
            raise LibraryError("Book not found.")
        out = conn.execute(
            "SELECT COUNT(*) FROM issues WHERE book_id = ? AND return_date IS NULL",
            (book_id,),
        ).fetchone()[0]
        if out:
            raise LibraryError(
                f"Cannot delete '{book['title']}': {out} cop{'y is' if out == 1 else 'ies are'} "
                "still issued. Return them first."
            )
        # Returned-loan history for this book is removed with it (ON DELETE CASCADE).
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        return book["title"]


def search_books(query="", field="Title or author"):
    sql = "SELECT * FROM books"
    params = []
    query = (query or "").strip()
    if query:
        like = f"%{query}%"
        if field == "Title":
            sql += " WHERE title LIKE ?"
            params = [like]
        elif field == "Author":
            sql += " WHERE author LIKE ?"
            params = [like]
        else:
            sql += " WHERE title LIKE ? OR author LIKE ?"
            params = [like, like]
    sql += " ORDER BY title COLLATE NOCASE"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def available_books():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM books WHERE available_copies > 0 ORDER BY title COLLATE NOCASE"
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Members
# --------------------------------------------------------------------------

def add_member(name, member_type, email=None, phone=None):
    name = _clean(name)
    if not name:
        raise LibraryError("Member name is required.")
    if member_type not in MEMBER_TYPES:
        raise LibraryError("Member type must be Student or Teacher.")
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO members (name, member_type, email, phone, joined_on) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, member_type, _clean(email), _clean(phone), date.today().isoformat()),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        raise LibraryError(f"A member with email '{email}' is already registered.")


def list_members(query="", member_type="All"):
    sql = """
        SELECT m.*,
               (SELECT COUNT(*) FROM issues i
                 WHERE i.member_id = m.id AND i.return_date IS NULL) AS books_held
        FROM members m WHERE 1 = 1
    """
    params = []
    if member_type in MEMBER_TYPES:
        sql += " AND m.member_type = ?"
        params.append(member_type)
    query = (query or "").strip()
    if query:
        sql += " AND (m.name LIKE ? OR m.email LIKE ?)"
        params += [f"%{query}%", f"%{query}%"]
    sql += " ORDER BY m.name COLLATE NOCASE"
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        r["borrow_limit"] = BORROW_LIMITS[r["member_type"]]
    return rows


def delete_member(member_id):
    with get_conn() as conn:
        member = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
        if member is None:
            raise LibraryError("Member not found.")
        held = conn.execute(
            "SELECT COUNT(*) FROM issues WHERE member_id = ? AND return_date IS NULL",
            (member_id,),
        ).fetchone()[0]
        if held:
            raise LibraryError(
                f"Cannot delete {member['name']}: they still hold {held} book(s)."
            )
        conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
        return member["name"]


# --------------------------------------------------------------------------
# Issue and return
# --------------------------------------------------------------------------

def issue_book(member_id, book_id, issue_date=None):
    """Issue one copy of a book. Returns (issue_id, due_date)."""
    issue_date = _to_date(issue_date or date.today())
    if issue_date > date.today():
        raise LibraryError("Issue date cannot be in the future.")
    loan_days = get_settings()["loan_days"]
    due_date = issue_date + timedelta(days=loan_days)

    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")  # lock so two issues can't race for the last copy
        member = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
        if member is None:
            raise LibraryError("Member not found.")
        book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if book is None:
            raise LibraryError("Book not found.")

        held = conn.execute(
            "SELECT COUNT(*) FROM issues WHERE member_id = ? AND return_date IS NULL",
            (member_id,),
        ).fetchone()[0]
        limit = BORROW_LIMITS[member["member_type"]]
        if held >= limit:
            raise LibraryError(
                f"{member['name']} ({member['member_type']}) already holds {held} book(s); "
                f"the limit is {limit}."
            )

        already = conn.execute(
            "SELECT 1 FROM issues WHERE member_id = ? AND book_id = ? AND return_date IS NULL",
            (member_id, book_id),
        ).fetchone()
        if already:
            raise LibraryError(f"{member['name']} already has a copy of '{book['title']}'.")

        cur = conn.execute(
            "UPDATE books SET available_copies = available_copies - 1 "
            "WHERE id = ? AND available_copies > 0",
            (book_id,),
        )
        if cur.rowcount == 0:
            raise LibraryError(f"No copies of '{book['title']}' are available.")

        cur = conn.execute(
            "INSERT INTO issues (book_id, member_id, issue_date, due_date) VALUES (?, ?, ?, ?)",
            (book_id, member_id, issue_date.isoformat(), due_date.isoformat()),
        )
        return cur.lastrowid, due_date


def return_book(issue_id, return_date=None):
    """Mark a loan returned and record its fine. Returns (fine, days_late)."""
    return_date = _to_date(return_date or date.today())
    if return_date > date.today():
        raise LibraryError("Return date cannot be in the future.")
    fine_per_day = get_settings()["fine_per_day"]

    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        loan = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if loan is None:
            raise LibraryError("Issue record not found.")
        if loan["return_date"] is not None:
            raise LibraryError("This book has already been returned.")
        if return_date < _to_date(loan["issue_date"]):
            raise LibraryError("Return date cannot be before the issue date.")

        fine = calculate_fine(loan["due_date"], return_date, fine_per_day)
        conn.execute(
            "UPDATE issues SET return_date = ?, fine = ? WHERE id = ?",
            (return_date.isoformat(), fine, issue_id),
        )
        conn.execute(
            "UPDATE books SET available_copies = available_copies + 1 WHERE id = ?",
            (loan["book_id"],),
        )
        return fine, days_overdue(loan["due_date"], return_date)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

_LOAN_SELECT = """
    SELECT i.id AS issue_id, b.id AS book_id, b.title, b.author,
           m.id AS member_id, m.name AS member, m.member_type,
           i.issue_date, i.due_date, i.return_date, i.fine
    FROM issues i
    JOIN books b   ON b.id = i.book_id
    JOIN members m ON m.id = i.member_id
"""


def active_loans():
    with get_conn() as conn:
        rows = conn.execute(
            _LOAN_SELECT + " WHERE i.return_date IS NULL ORDER BY i.due_date"
        ).fetchall()
    return [dict(r) for r in rows]


def overdue_loans(as_of=None):
    """Loans not yet returned whose due date has passed, with fine accrued so far."""
    as_of = _to_date(as_of or date.today())
    fine_per_day = get_settings()["fine_per_day"]
    with get_conn() as conn:
        rows = conn.execute(
            _LOAN_SELECT + " WHERE i.return_date IS NULL AND i.due_date < ? ORDER BY i.due_date",
            (as_of.isoformat(),),
        ).fetchall()
    result = []
    for r in rows:
        r = dict(r)
        r["days_overdue"] = days_overdue(r["due_date"], as_of)
        r["fine_so_far"] = calculate_fine(r["due_date"], as_of, fine_per_day)
        result.append(r)
    return result


def loan_history(limit=200):
    with get_conn() as conn:
        rows = conn.execute(
            _LOAN_SELECT + " ORDER BY i.id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def dashboard_stats():
    today = date.today().isoformat()
    with get_conn() as conn:
        one = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]
        stats = {
            "titles": one("SELECT COUNT(*) FROM books"),
            "copies": one("SELECT COALESCE(SUM(total_copies), 0) FROM books"),
            "available": one("SELECT COALESCE(SUM(available_copies), 0) FROM books"),
            "members": one("SELECT COUNT(*) FROM members"),
            "students": one("SELECT COUNT(*) FROM members WHERE member_type = 'Student'"),
            "teachers": one("SELECT COUNT(*) FROM members WHERE member_type = 'Teacher'"),
            "on_loan": one("SELECT COUNT(*) FROM issues WHERE return_date IS NULL"),
            "overdue": one(
                "SELECT COUNT(*) FROM issues WHERE return_date IS NULL AND due_date < ?",
                (today,),
            ),
            "fines_collected": one("SELECT COALESCE(SUM(fine), 0) FROM issues"),
        }
        top = conn.execute(
            "SELECT b.title, COUNT(*) AS times_issued FROM issues i "
            "JOIN books b ON b.id = i.book_id GROUP BY b.id "
            "ORDER BY times_issued DESC, b.title LIMIT 5"
        ).fetchall()
    stats["top_books"] = [dict(r) for r in top]
    return stats
