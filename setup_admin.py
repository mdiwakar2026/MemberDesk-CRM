"""Set (or reset) the CRM admin username and password in the local .env file.

Usage:  python setup_admin.py
The password is stored only on this computer, in .env (never in the code).
"""
import getpass
import re
import sys

import config  # creates .env with random secrets on first run

ENV = config.ENV_FILE


def set_value(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        return re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.M)
    return text.rstrip("\n") + "\n" + line + "\n"


def main():
    print("\n  MemberDesk CRM - administrator login setup\n")
    user = input("  Admin username [admin]: ").strip() or "admin"
    while True:
        pw = getpass.getpass("  New password (min 8 characters, typing is hidden): ")
        if len(pw) < 8 or " " in pw:
            print("  -> Use at least 8 characters and no spaces.")
            continue
        if getpass.getpass("  Confirm password: ") != pw:
            print("  -> Passwords did not match, try again.")
            continue
        break
    text = ENV.read_text(encoding="utf-8")
    text = set_value(text, "ADMIN_USERNAME", user)
    text = set_value(text, "ADMIN_PASSWORD", pw)
    ENV.write_text(text, encoding="utf-8")
    print(f"\n  Saved. Sign in with username '{user}' and the password you just chose.")
    print("  (Restart the CRM if it is already running.)\n")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.exit("\n  Cancelled - nothing changed.")
