"""
Library Management System — Streamlit UI.

Run with:  streamlit run app.py
"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import database as db

st.set_page_config(page_title="Library Management System", page_icon="📚", layout="wide")
db.init_db()


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def flash(kind, message):
    """Store a message so it survives the rerun that follows an action."""
    st.session_state["_flash"] = (kind, message)


def show_flash():
    if "_flash" in st.session_state:
        kind, message = st.session_state.pop("_flash")
        getattr(st, kind)(message)


def money(amount):
    return f"{db.get_settings()['currency']} {amount:,.2f}"


def table(rows, columns, empty_text):
    """Render a list of dicts as a table with friendly column names."""
    if not rows:
        st.info(empty_text)
        return None
    df = pd.DataFrame(rows)[list(columns.keys())].rename(columns=columns)
    st.dataframe(df, hide_index=True, width="stretch")
    return df


def book_label(b):
    return f"#{b['id']} — {b['title']} by {b['author']} ({b['available_copies']}/{b['total_copies']} available)"


def member_label(m):
    return (f"#{m['id']} — {m['name']} ({m['member_type']}, "
            f"{m['books_held']}/{m['borrow_limit']} books)")


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def page_dashboard():
    st.header("Dashboard")
    s = db.dashboard_stats()
    c = st.columns(5)
    c[0].metric("Book titles", s["titles"], f"{s['copies']} copies", delta_color="off")
    c[1].metric("Copies available", s["available"])
    c[2].metric("Members", s["members"],
                f"{s['students']} students · {s['teachers']} teachers", delta_color="off")
    c[3].metric("Books on loan", s["on_loan"])
    c[4].metric("Overdue", s["overdue"])
    st.caption(f"Total fines charged on returned books: **{money(s['fines_collected'])}**")

    left, right = st.columns(2)
    with left:
        st.subheader("Most borrowed books")
        if s["top_books"]:
            chart = pd.DataFrame(s["top_books"]).set_index("title")
            st.bar_chart(chart, y="times_issued", horizontal=True)
        else:
            st.info("No books have been issued yet.")
    with right:
        st.subheader("Recent activity")
        rows = db.loan_history(limit=10)
        for r in rows:
            r["status"] = "Returned" if r["return_date"] else "On loan"
        table(rows,
              {"title": "Book", "member": "Member", "issue_date": "Issued",
               "due_date": "Due", "status": "Status"},
              "No activity yet.")


def page_books():
    st.header("Books")
    show_flash()
    tab_search, tab_add, tab_delete = st.tabs(["Search", "Add book", "Delete book"])

    with tab_search:
        c1, c2 = st.columns([3, 2])
        query = c1.text_input("Search", placeholder="Type part of a title or author name")
        field = c2.radio("Search in", ["Title or author", "Title", "Author"], horizontal=True)
        rows = db.search_books(query, field)
        st.caption(f"{len(rows)} book(s) found")
        table(rows,
              {"id": "ID", "title": "Title", "author": "Author", "isbn": "ISBN",
               "category": "Category", "available_copies": "Available",
               "total_copies": "Total copies"},
              "No books match your search." if query else "No books in the library yet.")

    with tab_add:
        with st.form("add_book", clear_on_submit=True):
            c1, c2 = st.columns(2)
            title = c1.text_input("Title *")
            author = c2.text_input("Author *")
            isbn = c1.text_input("ISBN (optional)")
            category = c2.text_input("Category (optional)")
            copies = st.number_input("Number of copies", min_value=1, max_value=1000, value=1)
            if st.form_submit_button("Add book", type="primary"):
                try:
                    book_id = db.add_book(title, author, copies, isbn, category)
                    flash("success", f"Added '{title.strip()}' (ID {book_id}) with {copies} cop{'y' if copies == 1 else 'ies'}.")
                    st.rerun()
                except db.LibraryError as e:
                    st.error(str(e))

    with tab_delete:
        books = db.search_books()
        if not books:
            st.info("No books to delete.")
        else:
            book = st.selectbox("Choose a book", books, format_func=book_label, key="del_book")
            st.caption("Books with copies still issued can't be deleted. "
                       "Deleting a book also removes its past loan records.")
            sure = st.checkbox("I want to permanently delete this book", key="del_book_ok")
            if st.button("Delete book", type="primary", disabled=not sure):
                try:
                    title = db.delete_book(book["id"])
                    flash("success", f"Deleted '{title}'.")
                    st.rerun()
                except db.LibraryError as e:
                    st.error(str(e))


def page_members():
    st.header("Members")
    show_flash()
    tab_list, tab_add, tab_delete = st.tabs(["All members", "Register member", "Delete member"])

    with tab_list:
        c1, c2 = st.columns([3, 2])
        query = c1.text_input("Search by name or email", key="mem_q")
        mtype = c2.radio("Type", ["All", "Student", "Teacher"], horizontal=True)
        rows = db.list_members(query, mtype)
        st.caption(f"{len(rows)} member(s)")
        table(rows,
              {"id": "ID", "name": "Name", "member_type": "Type", "email": "Email",
               "phone": "Phone", "books_held": "Books held", "borrow_limit": "Limit",
               "joined_on": "Joined"},
              "No members found.")

    with tab_add:
        st.caption(f"Borrow limits: Student {db.BORROW_LIMITS['Student']} books, "
                   f"Teacher {db.BORROW_LIMITS['Teacher']} books.")
        with st.form("add_member", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Full name *")
            mtype = c2.selectbox("Member type *", db.MEMBER_TYPES)
            email = c1.text_input("Email (optional)")
            phone = c2.text_input("Phone (optional)")
            if st.form_submit_button("Register member", type="primary"):
                try:
                    member_id = db.add_member(name, mtype, email, phone)
                    flash("success", f"Registered {name.strip()} as a {mtype} (member ID {member_id}).")
                    st.rerun()
                except db.LibraryError as e:
                    st.error(str(e))

    with tab_delete:
        members = db.list_members()
        if not members:
            st.info("No members to delete.")
        else:
            member = st.selectbox("Choose a member", members, format_func=member_label, key="del_mem")
            st.caption("Members still holding books can't be deleted.")
            sure = st.checkbox("I want to permanently delete this member", key="del_mem_ok")
            if st.button("Delete member", type="primary", disabled=not sure):
                try:
                    name = db.delete_member(member["id"])
                    flash("success", f"Deleted member {name}.")
                    st.rerun()
                except db.LibraryError as e:
                    st.error(str(e))


def page_issue():
    st.header("Issue a book")
    show_flash()
    members = db.list_members()
    books = db.available_books()
    if not members:
        st.warning("Register a member first.")
        return
    if not books:
        st.warning("No books are available to issue.")
        return

    settings = db.get_settings()
    member = st.selectbox("Member", members, format_func=member_label)
    book = st.selectbox("Book", books, format_func=book_label)
    issue_date = st.date_input("Issue date", value=date.today(), max_value=date.today())
    due = issue_date + timedelta(days=settings["loan_days"])
    st.info(f"Due date: **{due:%d %b %Y}** ({settings['loan_days']}-day loan). "
            f"Late fine: {money(settings['fine_per_day'])} per day.")

    if member["books_held"] >= member["borrow_limit"]:
        st.error(f"{member['name']} has reached the {member['member_type'].lower()} "
                 f"limit of {member['borrow_limit']} books.")

    if st.button("Issue book", type="primary"):
        try:
            _, due_date = db.issue_book(member["id"], book["id"], issue_date)
            flash("success", f"Issued '{book['title']}' to {member['name']}. "
                             f"Due back on {due_date:%d %b %Y}.")
            st.rerun()
        except db.LibraryError as e:
            st.error(str(e))

    st.subheader("Books currently on loan")
    table(db.active_loans(),
          {"issue_id": "Issue ID", "title": "Book", "member": "Member",
           "member_type": "Type", "issue_date": "Issued", "due_date": "Due"},
          "No books are on loan.")


def page_return():
    st.header("Return a book")
    show_flash()
    loans = db.active_loans()
    if not loans:
        st.info("No books are currently on loan.")
        return

    settings = db.get_settings()
    loan = st.selectbox(
        "Loan",
        loans,
        format_func=lambda l: f"#{l['issue_id']} — {l['title']} · {l['member']} · due {l['due_date']}",
    )
    return_date = st.date_input(
        "Return date",
        value=date.today(),
        min_value=date.fromisoformat(loan["issue_date"]),
        max_value=date.today(),
    )
    late = db.days_overdue(loan["due_date"], return_date)
    fine = db.calculate_fine(loan["due_date"], return_date, settings["fine_per_day"])
    if late:
        st.warning(f"Returned {late} day(s) late. Fine: **{money(fine)}** "
                   f"({late} × {money(settings['fine_per_day'])}).")
    else:
        st.success("On time — no fine.")

    if st.button("Confirm return", type="primary"):
        try:
            fine, late = db.return_book(loan["issue_id"], return_date)
            msg = f"'{loan['title']}' returned by {loan['member']}."
            msg += f" Fine charged: {money(fine)} ({late} day(s) late)." if fine else " No fine."
            flash("success", msg)
            st.rerun()
        except db.LibraryError as e:
            st.error(str(e))


def page_overdue():
    st.header("Overdue books")
    rows = db.overdue_loans()
    st.caption(f"As of {date.today():%d %b %Y}. Fines shown are what would be charged "
               "if the book were returned today.")
    df = table(rows,
               {"issue_id": "Issue ID", "title": "Book", "member": "Member",
                "member_type": "Type", "issue_date": "Issued", "due_date": "Due",
                "days_overdue": "Days overdue", "fine_so_far": "Fine so far"},
               "No overdue books. 🎉")
    if df is not None:
        st.metric("Total outstanding fines", money(sum(r["fine_so_far"] for r in rows)))
        st.download_button("Download as CSV", df.to_csv(index=False),
                           file_name=f"overdue_{date.today()}.csv", mime="text/csv")


def page_history():
    st.header("Loan history")
    rows = db.loan_history(limit=1000)
    for r in rows:
        r["status"] = "Returned" if r["return_date"] else "On loan"
    table(rows,
          {"issue_id": "Issue ID", "title": "Book", "member": "Member",
           "member_type": "Type", "issue_date": "Issued", "due_date": "Due",
           "return_date": "Returned", "fine": "Fine", "status": "Status"},
          "No loans recorded yet.")


def page_settings():
    st.header("Settings")
    show_flash()
    s = db.get_settings()
    with st.form("settings"):
        loan_days = st.number_input("Loan period (days)", min_value=1, max_value=365,
                                    value=s["loan_days"])
        fine = st.number_input("Fine per day late", min_value=0.0, value=s["fine_per_day"],
                               step=1.0)
        currency = st.text_input("Currency label", value=s["currency"])
        st.caption("A new loan period applies to books issued from now on; "
                   "existing due dates don't change. The fine rate applies to "
                   "returns processed from now on.")
        if st.form_submit_button("Save", type="primary"):
            try:
                db.update_settings(loan_days, fine, currency)
                flash("success", "Settings saved.")
                st.rerun()
            except db.LibraryError as e:
                st.error(str(e))


# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------

PAGES = {
    "Dashboard": page_dashboard,
    "Books": page_books,
    "Members": page_members,
    "Issue book": page_issue,
    "Return book": page_return,
    "Overdue books": page_overdue,
    "Loan history": page_history,
    "Settings": page_settings,
}

with st.sidebar:
    st.title("📚 Library")
    choice = st.radio("Go to", list(PAGES.keys()), label_visibility="collapsed")
    overdue_count = db.dashboard_stats()["overdue"]
    if overdue_count:
        st.error(f"{overdue_count} overdue book(s)")

PAGES[choice]()
