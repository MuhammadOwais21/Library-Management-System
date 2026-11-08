# Library Management System

A Streamlit + SQLite app for a librarian to manage books and members, issue and return books, and charge fines for late returns.

## Run

```
pip install -r requirements.txt
streamlit run app.py
```

The database file `library.db` is created next to `app.py` on first run. To use a different file, set the `LIBRARY_DB` environment variable.

## Files

- `app.py`: Streamlit UI (sidebar navigation, one function per page)
- `database.py`: SQLite schema and all business rules (limits, due dates, fines)

## Pages

| Page | What it does |
|---|---|
| Dashboard | Counts, most-borrowed chart, recent activity |
| Books | Search by title, author, or both; add a book (with number of copies); delete a book |
| Members | List/search/filter members; register a Student or Teacher; delete a member |
| Issue book | Issue an available copy; shows the due date before confirming |
| Return book | Previews days late and fine, then records the return |
| Overdue books | Unreturned books past their due date, with fines accrued so far; CSV export |
| Loan history | Every issue and return, with fines charged |
| Settings | Loan period, fine per day, currency label |

## Rules

- Borrow limits: Student 3 books, Teacher 5 books (`BORROW_LIMITS` in `database.py`).
- Due date = issue date + loan period (default 14 days).
- Fine = days late × fine per day (default 10). A return on or before the due date costs nothing.
- A member can't hold two copies of the same book at once.
- A book can't be issued when no copies are available.
- Books with copies on loan, and members holding books, can't be deleted.
- Deleting a book or member also deletes their past (returned) loan records.
- Issue and return dates can be back-dated (useful for entering paper records) but not set in the future.

## Database schema

- `books(id, title, author, isbn UNIQUE, category, total_copies, available_copies, added_on)`
- `members(id, name, member_type IN ('Student','Teacher'), email UNIQUE, phone, joined_on)`
- `issues(id, book_id → books, member_id → members, issue_date, due_date, return_date NULL until returned, fine)`
- `settings(key, value)`
