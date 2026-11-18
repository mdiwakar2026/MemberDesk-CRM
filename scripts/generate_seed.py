"""Generate db/seed.sql with fictional demo data.

Every name, phone number and email here is made up:
* emails use the reserved example.com domain
* phone numbers use the 90000xxxxx placeholder range
Run:  python scripts/generate_seed.py [count]
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "db" / "seed.sql"
FEE = 2000

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karthik", "Siddharth", "Rahul", "Nikhil", "Varun",
         "Pranav", "Harish", "Manoj", "Suresh", "Ganesh", "Vikram", "Anand", "Deepak", "Rajesh", "Naveen",
         "Ananya", "Diya", "Isha", "Kavya", "Meera", "Nisha", "Pooja", "Priya", "Riya", "Sneha",
         "Divya", "Lakshmi", "Swathi", "Anjali", "Shruti", "Asha", "Revathi", "Neha", "Tara", "Uma"]
LAST = ["Sharma", "Iyer", "Nair", "Reddy", "Rao", "Menon", "Kumar", "Patel", "Gupta", "Joshi",
        "Pillai", "Krishnan", "Bhat", "Desai", "Kulkarni", "Mehta", "Verma", "Chopra", "Shetty", "Das"]
FEMALE = set(FIRST[20:])

CHAPTERS = [  # (place, state, pincode prefix, weight)
    ("BENGALURU", "KARNATAKA", "560", 18), ("PUNE", "MAHARASHTRA", "411", 14),
    ("HYDERABAD", "TELANGANA", "500", 13), ("MUMBAI", "MAHARASHTRA", "400", 12),
    ("KOCHI", "KERALA", "682", 9), ("AHMEDABAD", "GUJARAT", "380", 8),
    ("JAIPUR", "RAJASTHAN", "302", 7), ("KOLKATA", "WEST BENGAL", "700", 7),
    ("MYSURU", "KARNATAKA", "570", 5), ("NAGPUR", "MAHARASHTRA", "440", 4),
]
STATUS = [("Qualified", 70), ("Student", 12), ("In Training", 10), ("Retired", 3)]
CATEGORY = [("Fellow", 35), ("Associate", 40), ("Affiliate", 15), ("Student Member", 10)]
PRACTICING = [("Yes", 45), ("In Progress", 30), ("No", 25)]
EDUCATION = ["B.Com", "M.Com", "BBA", "MBA", "CA", "CMA", "CS", "LLB", "B.Sc", "B.A"]
SPECIAL = ["GST", "Income Tax", "Audit", "Corporate Law", "Payroll", "International Tax", "Accounting"]
ORGS = ["Sample Advisors LLP", "Demo Tax Services", "Acme Consultants", "Placeholder & Co",
        "Example Financial Services", "Self-employed", ""]
POSITIONS = ["President", "Vice President", "Secretary", "Joint Secretary", "Treasurer"]
STREETS = ["MG Road", "Park Street", "Station Road", "Lake View Road", "Temple Street", "Market Road"]


def pick(weighted):
    return random.choices([v for v, _ in weighted], [w for _, w in weighted])[0]


def q(v) -> str:
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def main(count: int = 180):
    random.seed(42)  # same output every time
    members, comms = [], []
    used_names = set()
    for i in range(count):
        mid = str(100001 + i)
        while True:
            first, last = random.choice(FIRST), random.choice(LAST)
            if (first, last) not in used_names or len(used_names) > 700:
                used_names.add((first, last))
                break
        place, state, pin, _ = random.choices(CHAPTERS, [c[3] for c in CHAPTERS])[0]
        paid = random.random() < 0.45
        pay_date = date(2026, 1, 5) + timedelta(days=random.randint(0, 300)) if paid else None
        detailed = random.random() < 0.6  # only some members have a full profile
        m = {
            "member_id": mid,
            "name": f"{first} {last}".upper(),
            "gender": ("Female" if first in FEMALE else "Male") if detailed else "",
            "dob": str(date(1965, 1, 1) + timedelta(days=random.randint(0, 13000))) if detailed else "",
            "marital_status": random.choice(["Single", "Married"]) if detailed else "",
            "mobile": f"90000{i + 10001:05d}",
            "alt_mobile": "",
            "email": f"{first}.{last}{i + 1}@example.com".lower(),
            "member_status": pick(STATUS),
            "category": pick(CATEGORY),
            "practicing": pick(PRACTICING),
            "position": POSITIONS[i] if i < len(POSITIONS) else "",
            "ob_ecm": "OB" if i < len(POSITIONS) else ("ECM" if random.random() < 0.05 else ""),
            "place": place, "state": state, "chapter": place,
            "address": f"{random.randint(1, 250)}, {random.choice(STREETS)}" if detailed else "",
            "pincode": f"{pin}{random.randint(1, 99):03d}" if detailed else "",
            "education": random.choice(EDUCATION) if detailed else "",
            "specialization": random.choice(SPECIAL) if detailed else "",
            "gstp_no": f"GSTP/DEMO/{random.randint(1000, 9999)}" if detailed and random.random() < 0.4 else "",
            "itp_no": f"ITP-DEMO-{random.randint(100, 999)}" if detailed and random.random() < 0.3 else "",
            "advocate_others": "",
            "organization": random.choice(ORGS) if detailed else "",
            "subscription": FEE if paid else 0,
            "payment_date": str(pay_date) if paid else "",
            "payment_mode": random.choice(["UPI", "Bank Transfer", "Cash", "Cheque"]) if paid else "",
            "receipt_no": f"R-2026-{i + 1:04d}" if paid else "",
            "comments": "",
            "record_status": "Archived" if random.random() < 0.02 else "Active",
            "created_on": "2026-01-01 09:00:00",
            "updated_on": f"2026-{random.randint(1, 10):02d}-{random.randint(1, 28):02d} {random.randint(9, 18):02d}:"
                          f"{random.randint(0, 59):02d}:00",
        }
        members.append(m)

    # a few sample messages so the Outbox is not empty
    for n, m in enumerate(random.sample([m for m in members if m["subscription"] == 0], 6)):
        status = ["Sent", "Sent", "Manual", "Pending Approval", "Pending Approval", "Rejected"][n]
        comms.append({
            "id": f"DEMO{n + 1:06d}", "created_on": f"2026-10-{10 + n:02d} 10:30:00",
            "member_id": m["member_id"], "name": m["name"], "channel": "Email" if n % 2 else "WhatsApp",
            "recipient": m["email"] if n % 2 else m["mobile"],
            "subject": "Annual subscription reminder" if n % 2 else "",
            "body": f"Dear {m['name'].title()},\n\nThis is a gentle reminder that your annual membership "
                    f"subscription of Rs. {FEE} (Member ID: {m['member_id']}) is pending.\n\nWarm regards,\n"
                    "Northbridge Professional Association",
            "status": status, "created_by": "admin",
            "approved_by": "admin" if status != "Pending Approval" else "",
            "sent_on": f"2026-10-{10 + n:02d} 11:00:00" if status == "Sent" else "",
            "error": "Sent manually" if status == "Manual" else "",
        })

    lines = ["-- Demo data for MemberDesk CRM (generated by scripts/generate_seed.py).",
             "-- All people, phone numbers and emails are fictional.", "BEGIN;"]
    cols = list(members[0])
    for m in members:
        lines.append(f"INSERT INTO members ({', '.join(cols)}) VALUES ({', '.join(q(m[c]) for c in cols)});")
    ccols = list(comms[0])
    for c in comms:
        lines.append(f"INSERT INTO communications ({', '.join(ccols)}) VALUES ({', '.join(q(c[k]) for k in ccols)});")
    lines.append("COMMIT;")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(members)} members and {len(comms)} messages to {OUT}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 180)
