"""MemberDesk CRM - Flask application.

Run:  python app.py [port]   ->  http://127.0.0.1:5000
"""
from __future__ import annotations

import hmac
import io
import re
import secrets
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from openpyxl import Workbook

from config import Config
from crm.sql_store import MEMBER_FIELDS, SqlStore, StoreLockedError
from crm.messaging import (ORG, TEMPLATES, Messenger, mailto_link, normalize_phone, render,
                           sent_today, valid_email, whatsapp_link)

app = Flask(__name__)
app.config.from_object(Config)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

store = SqlStore(Config.DB_PATH, Config.BACKUP_DIR, Config.BACKUP_KEEP, Config.SUBSCRIPTION_FEE)
store.ensure(Config.SCHEMA_SQL, Config.SEED_SQL)
Config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
messenger = Messenger(Config)
ORG.update(org=Config.ORG_SHORT, org_name=Config.ORG_NAME)

CHOICES = {
    "gender": ["Male", "Female", "Other", "Prefer not to say"],
    "marital_status": ["Single", "Married", "Divorced", "Widowed"],
    "education": ["10th", "12th", "Diploma", "B.Com", "BBA", "B.A", "B.Sc", "BCA", "M.Com",
                  "MBA", "M.A", "LLB", "CA", "CMA", "CS", "Ph.D", "Other"],
    "payment_mode": ["Cash", "UPI", "Bank Transfer", "Cheque", "Online"],
    "record_status": ["Active", "Archived"],
}
FIELD_LABELS = dict(MEMBER_FIELDS)
PROFILE_FIELDS = ["gender", "dob", "marital_status", "education", "mobile", "email"]


# ---------------------------------------------------------------- helpers / security
def current_user():
    return session.get("user")


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


@app.before_request
def csrf_protect():
    session.setdefault("csrf", secrets.token_hex(16))
    if request.method == "POST":
        token = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(token, session["csrf"]):
            abort(400, "Invalid form token - please reload the page.")


@app.context_processor
def inject_globals():
    pending = 0
    if current_user():
        pending = sum(1 for c in store.communications() if c["status"] == "Pending Approval")
    return {"cfg": Config, "csrf_token": session.get("csrf", ""), "user": current_user(),
            "pending_count": pending, "now": datetime.now()}


@app.errorhandler(StoreLockedError)
def handle_locked(exc):
    flash(str(exc), "danger")
    return redirect(request.referrer or url_for("dashboard"))


@app.template_filter("inr")
def inr(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return ("-" if n < 0 else "") + "₹" + s


@app.template_filter("title_name")
def title_name(v):
    return (v or "").title()


@app.template_filter("initials")
def initials(v):
    parts = [p for p in re.split(r"[\s.]+", v or "") if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def digits(s):
    return re.sub(r"\D", "", s or "")


def search_members(members, q):
    q = (q or "").strip()
    if not q:
        return members
    ql, qd = q.lower(), digits(q)
    out = []
    for m in members:
        if ql in m["name"].lower() or ql in m["member_id"].lower():
            out.append(m)
        elif len(qd) >= 3 and (qd in digits(m["mobile"]) or qd in digits(m["alt_mobile"])):
            out.append(m)
    return out


def filter_members(args):
    members = store.members(include_archived=args.get("record") == "all")
    members = search_members(members, args.get("q"))
    for key in ("payment_status", "place", "chapter", "member_status", "category", "practicing", "gender"):
        val = args.get(key)
        if val:
            members = [m for m in members if m[key] == val]
    if args.get("missing") == "mobile":
        members = [m for m in members if not m["mobile"]]
    elif args.get("missing") == "email":
        members = [m for m in members if not m["email"]]
    elif args.get("missing") == "aadhaar":
        members = [m for m in members if not m["aadhaar_file"]]
    sort = args.get("sort", "name")
    if sort in ("name", "member_id", "place", "subscription", "updated_on"):
        members.sort(key=lambda m: (m[sort] if sort != "subscription" else m[sort]),
                     reverse=sort in ("subscription", "updated_on"))
    return members


def profile_score(m):
    return round(100 * sum(1 for f in PROFILE_FIELDS if m.get(f)) / len(PROFILE_FIELDS))


def validate_member(form, creating):
    data = {k: (form.get(k) or "").strip() for k, _ in MEMBER_FIELDS
            if k not in ("payment_status", "aadhaar_file", "aadhaar_uploaded_on",
                         "created_on", "updated_on")}
    errors = {}
    if creating and not re.fullmatch(r"\d{3,10}", data.get("member_id", "")):
        errors["member_id"] = "Member ID must be 3-10 digits."
    elif creating and store.get_member(data["member_id"]):
        errors["member_id"] = f"Member ID {data['member_id']} already exists."
    if not data["name"]:
        errors["name"] = "Name is required."
    data["name"] = data["name"].upper()
    for f in ("mobile", "alt_mobile"):
        if data[f]:
            d = digits(data[f])
            if len(d) == 12 and d.startswith("91"):
                d = d[2:]
            if not re.fullmatch(r"[6-9]\d{9}", d):
                errors[f] = "Enter a valid 10-digit Indian mobile number."
            data[f] = d
    if data["email"]:
        data["email"] = data["email"].lower()
        if not valid_email(data["email"]):
            errors["email"] = "Enter a valid email address."
    if data["pincode"] and not re.fullmatch(r"\d{6}", data["pincode"]):
        errors["pincode"] = "Pincode must be 6 digits."
    for f, label in (("gstp_no", "GSTP No"), ("itp_no", "ITP No")):
        data[f] = data[f].upper()
        if data[f] and not re.fullmatch(r"[A-Z0-9/\-]{2,30}", data[f]):
            errors[f] = f"{label} may contain only letters, numbers, / and - (max 30)."
    if data["subscription"]:
        if not re.fullmatch(r"\d+", data["subscription"].replace(",", "")):
            errors["subscription"] = "Subscription must be a whole rupee amount."
        data["subscription"] = data["subscription"].replace(",", "")
    for f in ("place", "state", "chapter"):
        data[f] = data[f].upper() if f in ("place", "state", "chapter") else data[f]
    if data.get("mobile") and not errors.get("mobile"):
        clash = [m for m in store.members(True) if m["mobile"] == data["mobile"]
                 and m["member_id"] != (data.get("member_id") or form.get("_orig_id"))]
        if clash:
            errors["mobile"] = f"Mobile already registered to {clash[0]['name']} ({clash[0]['member_id']})."
    return data, errors


def distinct(key):
    return sorted({m[key] for m in store.members(True) if m[key]})


# ---------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, p = request.form.get("username", ""), request.form.get("password", "")
        ok = (Config.ADMIN_PASSWORD and hmac.compare_digest(u, Config.ADMIN_USERNAME)
              and hmac.compare_digest(p, Config.ADMIN_PASSWORD))
        if ok:
            session.clear()
            session["user"] = u
            session["csrf"] = secrets.token_hex(16)
            store.log(u, "login", "Signed in")
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------- dashboard
@app.route("/")
@login_required
def dashboard():
    ms = store.members()
    total = len(ms)
    paid = [m for m in ms if m["payment_status"] == "Paid"]
    collected = sum(m["subscription"] for m in ms)
    pending_amount = (total - len(paid)) * Config.SUBSCRIPTION_FEE

    by_place = Counter(m["chapter"] or "Not set" for m in ms).most_common(10)
    by_category = Counter(m["category"] or "Not set" for m in ms).most_common(8)
    by_status = Counter(m["member_status"] or "Not set" for m in ms).most_common()
    by_practicing = Counter(m["practicing"] or "Not set" for m in ms).most_common()
    monthly = defaultdict(int)
    for m in ms:
        if m["payment_date"][:7] and m["subscription"]:
            monthly[m["payment_date"][:7]] += m["subscription"]
    months = sorted(monthly)
    paid_by_place = defaultdict(lambda: [0, 0])
    for m in ms:
        paid_by_place[m["chapter"] or "Not set"][0 if m["payment_status"] == "Paid" else 1] += 1
    place_rows = sorted(paid_by_place.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:8]

    quality = {
        "mobile": sum(1 for m in ms if m["mobile"]),
        "email": sum(1 for m in ms if m["email"]),
        "aadhaar": sum(1 for m in ms if m["aadhaar_file"]),
        "profile": round(sum(profile_score(m) for m in ms) / total) if total else 0,
    }
    comms = store.communications()
    stats = {
        "total": total, "paid": len(paid), "unpaid": total - len(paid),
        "collected": collected, "pending_amount": pending_amount,
        "paid_pct": round(100 * len(paid) / total) if total else 0,
        "sent": sum(1 for c in comms if c["status"] == "Sent"),
    }
    chart = {
        "place_labels": [p.title() for p, _ in by_place], "place_values": [v for _, v in by_place],
        "category_labels": [p for p, _ in by_category], "category_values": [v for _, v in by_category],
        "month_labels": [datetime.strptime(mo, "%Y-%m").strftime("%b %Y") for mo in months],
        "month_values": [monthly[mo] for mo in months],
    }
    recent = sorted(ms, key=lambda m: m["updated_on"], reverse=True)[:6]
    return render_template("dashboard.html", stats=stats, chart=chart, quality=quality,
                           place_rows=place_rows, recent=recent, audit=store.audit(8),
                           by_status=by_status, by_practicing=by_practicing)


# ---------------------------------------------------------------- members
@app.route("/members")
@login_required
def members():
    ms = filter_members(request.args)
    page = max(1, request.args.get("page", 1, type=int))
    per = 25
    pages = max(1, (len(ms) + per - 1) // per)
    page = min(page, pages)
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template("members.html", members=ms[(page - 1) * per: page * per], count=len(ms),
                           page=page, pages=pages, args=args,
                           places=distinct("place"), chapters=distinct("chapter"),
                           statuses=distinct("member_status"), categories=distinct("category"),
                           practicing=distinct("practicing"), choices=CHOICES)


@app.route("/api/search")
@login_required
def api_search():
    q = request.args.get("q", "")
    if len(q.strip()) < 2:
        return jsonify([])
    res = search_members(store.members(True), q)[:8]
    return jsonify([{"member_id": m["member_id"], "name": m["name"].title(), "mobile": m["mobile"],
                     "place": m["place"].title(), "status": m["payment_status"],
                     "url": url_for("member_detail", member_id=m["member_id"])} for m in res])


@app.route("/members/export")
@login_required
def export_members():
    ms = filter_members(request.args)
    wb = Workbook()
    ws = wb.active
    ws.title = "Members"
    fields = [(k, h) for k, h in MEMBER_FIELDS if k != "aadhaar_file"]
    ws.append([h for _, h in fields])
    for m in ms:
        ws.append([m[k] for k, _ in fields])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    store.log(current_user(), "export", f"{len(ms)} members exported")
    return send_file(buf, as_attachment=True,
                     download_name=f"Members_{datetime.now():%Y%m%d_%H%M}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/members/new", methods=["GET", "POST"])
@login_required
def member_new():
    if request.method == "POST":
        data, errors = validate_member(request.form, creating=True)
        if not errors:
            try:
                store.add_member(data, current_user())
                flash(f"Member {data['name'].title()} added.", "success")
                return redirect(url_for("member_detail", member_id=data["member_id"]))
            except ValueError as exc:
                errors["member_id"] = str(exc)
        flash("Please correct the highlighted fields.", "danger")
        return render_template("member_form.html", m=data, errors=errors, creating=True,
                               choices=CHOICES, suggestions=_suggestions())
    m = {k: "" for k, _ in MEMBER_FIELDS}
    m.update(member_id=store.next_member_id(), record_status="Active")
    return render_template("member_form.html", m=m, errors={}, creating=True,
                           choices=CHOICES, suggestions=_suggestions())


def _suggestions():
    return {"place": distinct("place"), "position": distinct("position"),
            "member_status": distinct("member_status"), "category": distinct("category"),
            "practicing": sorted(set(["Yes", "In Progress"] + distinct("practicing"))),
            "chapter": distinct("chapter"), "state": distinct("state"),
            "specialization": distinct("specialization"), "advocate_others": ["Advocate", "Others"] + distinct("advocate_others")}


@app.route("/members/<member_id>")
@login_required
def member_detail(member_id):
    m = store.get_member(member_id) or abort(404)
    history = [c for c in store.communications() if c["member_id"] == member_id]
    history.sort(key=lambda c: c["created_on"], reverse=True)
    for c in history:
        c["link"] = (whatsapp_link(c["recipient"], c["body"], Config.DEFAULT_COUNTRY_CODE)
                     if c["channel"] == "WhatsApp" else mailto_link(c["recipient"], c["subject"], c["body"]))
    return render_template("member_detail.html", m=m, history=history, score=profile_score(m),
                           labels=FIELD_LABELS, wa_ready=bool(normalize_phone(m["mobile"])))


@app.route("/members/<member_id>/edit", methods=["GET", "POST"])
@login_required
def member_edit(member_id):
    m = store.get_member(member_id) or abort(404)
    if request.method == "POST":
        data, errors = validate_member(request.form, creating=False)
        data.pop("member_id", None)
        if not errors:
            store.update_member(member_id, data, current_user())
            flash("Member details saved.", "success")
            return redirect(url_for("member_detail", member_id=member_id))
        flash("Please correct the highlighted fields.", "danger")
        m = {**m, **data}
        return render_template("member_form.html", m=m, errors=errors, creating=False,
                               choices=CHOICES, suggestions=_suggestions())
    return render_template("member_form.html", m=m, errors={}, creating=False,
                           choices=CHOICES, suggestions=_suggestions())


@app.route("/members/<member_id>/archive", methods=["POST"])
@login_required
def member_archive(member_id):
    m = store.get_member(member_id) or abort(404)
    new = "Active" if m["record_status"] == "Archived" else "Archived"
    store.update_member(member_id, {"record_status": new}, current_user(), action=f"member.{new.lower()}")
    flash(f"Member {'restored' if new == 'Active' else 'archived'}.", "info")
    return redirect(url_for("member_detail", member_id=member_id))


# ---------------------------------------------------------------- Aadhaar
MAGIC = {b"%PDF": "pdf", b"\xff\xd8\xff": "jpg", b"\x89PNG": "png"}


@app.route("/members/<member_id>/aadhaar", methods=["POST"])
@login_required
def aadhaar_upload(member_id):
    m = store.get_member(member_id) or abort(404)
    f = request.files.get("aadhaar")
    if not f or not f.filename:
        flash("Choose a file to upload.", "warning")
        return redirect(url_for("member_detail", member_id=member_id))
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    head = f.stream.read(8)
    f.stream.seek(0)
    kind = next((v for k, v in MAGIC.items() if head.startswith(k)), None)
    if ext not in Config.ALLOWED_UPLOADS or not kind:
        flash("Only PDF, JPG or PNG files are allowed.", "danger")
        return redirect(url_for("member_detail", member_id=member_id))
    name = f"{member_id}_{uuid.uuid4().hex[:12]}.{kind}"
    f.save(Config.UPLOAD_DIR / name)
    old = m["aadhaar_file"]
    store.update_member(member_id, {"aadhaar_file": name,
                                    "aadhaar_uploaded_on": datetime.now().strftime("%Y-%m-%d %H:%M")},
                        current_user(), action="aadhaar.upload")
    if old and (Config.UPLOAD_DIR / old).exists() and old != name:
        (Config.UPLOAD_DIR / old).unlink()
    flash("Aadhaar document uploaded securely.", "success")
    return redirect(url_for("member_detail", member_id=member_id))


@app.route("/members/<member_id>/aadhaar/view")
@login_required
def aadhaar_view(member_id):
    m = store.get_member(member_id) or abort(404)
    if not m["aadhaar_file"]:
        abort(404)
    store.log(current_user(), "aadhaar.view", member_id)
    return send_from_directory(Config.UPLOAD_DIR, m["aadhaar_file"])


@app.route("/members/<member_id>/aadhaar/delete", methods=["POST"])
@login_required
def aadhaar_delete(member_id):
    m = store.get_member(member_id) or abort(404)
    if m["aadhaar_file"]:
        store.update_member(member_id, {"aadhaar_file": "", "aadhaar_uploaded_on": ""},
                            current_user(), action="aadhaar.delete")
        p = Config.UPLOAD_DIR / m["aadhaar_file"]
        if p.exists():
            p.unlink()
        flash("Aadhaar document removed.", "info")
    return redirect(url_for("member_detail", member_id=member_id))


# ---------------------------------------------------------------- messaging (HITL)
@app.route("/messages/compose", methods=["GET", "POST"])
@login_required
def compose():
    ids = request.values.getlist("ids") or [i for i in request.values.get("id_list", "").split(",") if i]
    if request.values.get("filter_all"):
        ids = [m["member_id"] for m in filter_members(request.args)]
    recipients = [m for m in (store.get_member(i) for i in ids) if m]
    if request.method == "POST" and request.form.get("action") == "queue":
        channels = request.form.getlist("channels")
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        if not channels or not body or ("Email" in channels and not subject):
            flash("Pick a channel and write the message (email needs a subject).", "danger")
        else:
            items, skipped = [], 0
            for m in recipients:
                for ch in channels:
                    to = m["email"] if ch == "Email" else m["mobile"]
                    ok = valid_email(to) if ch == "Email" else bool(normalize_phone(to, Config.DEFAULT_COUNTRY_CODE))
                    if not ok:
                        skipped += 1
                        continue
                    items.append({"member_id": m["member_id"], "name": m["name"], "channel": ch,
                                  "recipient": to, "subject": render(subject, m, Config.SUBSCRIPTION_FEE),
                                  "body": render(body, m, Config.SUBSCRIPTION_FEE),
                                  "status": "Pending Approval"})
            if items:
                store.add_communications(items, current_user())
            flash(f"{len(items)} message(s) queued for approval"
                  + (f"; {skipped} skipped (missing/invalid contact)." if skipped else "."), "success")
            return redirect(url_for("outbox"))
    tpl_key = request.values.get("template", "payment_reminder")
    tpl = TEMPLATES.get(tpl_key, TEMPLATES["custom"])
    preview = render(tpl["body"], recipients[0], Config.SUBSCRIPTION_FEE) if recipients else ""
    return render_template("compose.html", recipients=recipients, templates=TEMPLATES, tpl_key=tpl_key,
                           tpl=tpl, preview=preview, email_ready=messenger.email_ready,
                           whatsapp_ready=messenger.whatsapp_ready)


@app.route("/outbox")
@login_required
def outbox():
    status = request.args.get("status", "Pending Approval")
    comms = store.communications()
    counts = Counter(c["status"] for c in comms)
    items = [c for c in comms if status == "All" or c["status"] == status]
    items.sort(key=lambda c: c["created_on"], reverse=True)
    for c in items:
        c["link"] = (whatsapp_link(c["recipient"], c["body"], Config.DEFAULT_COUNTRY_CODE)
                     if c["channel"] == "WhatsApp" else mailto_link(c["recipient"], c["subject"], c["body"]))
    return render_template("outbox.html", items=items, status=status, counts=counts,
                           email_ready=messenger.email_ready, whatsapp_ready=messenger.whatsapp_ready,
                           sent_today=sent_today(comms))


@app.route("/outbox/action", methods=["POST"])
@login_required
def outbox_action():
    action = request.form.get("action")
    ids = request.form.getlist("ids")
    comms = {c["id"]: c for c in store.communications()}
    selected = [comms[i] for i in ids if i in comms]
    user = current_user()
    if not selected:
        flash("Select at least one message.", "warning")
        return redirect(url_for("outbox"))
    if action == "reject":
        for c in selected:
            store.update_communication(c["id"], {"status": "Rejected", "approved_by": user}, user, "message.reject")
        flash(f"{len(selected)} message(s) rejected.", "info")
    elif action == "mark_sent":
        for c in selected:
            store.update_communication(c["id"], {"status": "Sent", "approved_by": user,
                                                 "sent_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                                 "error": "Sent manually"}, user, "message.manual_sent")
        flash(f"{len(selected)} message(s) marked as sent.", "success")
    elif action == "approve":
        if request.form.get("confirm") != "yes":
            flash("Tick the confirmation box before approving.", "warning")
            return redirect(url_for("outbox"))
        budget_left = Config.MAX_SEND_PER_DAY - sent_today(list(comms.values()))
        batch = [c for c in selected if c["status"] in ("Pending Approval", "Failed", "Manual")]
        batch = batch[: max(0, min(Config.MAX_SEND_PER_BATCH, budget_left))]
        if not batch:
            flash("Daily sending budget reached or nothing eligible to send.", "warning")
            return redirect(url_for("outbox"))
        result = Counter()
        for c in batch:
            status, err = messenger.send(c)
            result[status] += 1
            store.update_communication(c["id"], {
                "status": status, "approved_by": user, "error": err,
                "sent_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "Sent" else ""},
                user, f"message.{status.lower()}")
        note = ", ".join(f"{v} {k.lower()}" for k, v in result.items())
        if len(selected) > len(batch):
            note += f". {len(selected) - len(batch)} held back by the batch/daily limit"
        flash(f"Approved: {note}.", "success")
    return redirect(url_for("outbox", status=request.form.get("return_status", "Pending Approval")))


# ---------------------------------------------------------------- settings
@app.route("/settings")
@login_required
def settings():
    counts = {"members": len(store.members(True)), "messages": len(store.communications())}
    return render_template("settings.html", counts=counts, email_ready=messenger.email_ready,
                           whatsapp_ready=messenger.whatsapp_ready, audit=store.audit(60),
                           backups=sorted(Config.BACKUP_DIR.glob("*.db"), reverse=True)[:5])


@app.route("/download/database")
@login_required
def download_db():
    snapshot = store.backup()  # consistent copy, safe while the app is running
    store.log(current_user(), "export", "Full database downloaded")
    return send_file(snapshot, as_attachment=True,
                     download_name=f"memberdesk_{datetime.now():%Y%m%d}.db")


if __name__ == "__main__":
    import os
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("PORT", 5000))
    print(f"\n  MemberDesk CRM ({Config.ORG_SHORT}) running at  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
