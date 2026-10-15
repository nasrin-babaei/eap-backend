from datetime import datetime

# TODO: Call this helper when role assignment or role change endpoint is implemented.
def log_role_change(user_email: str, old_role: str, new_role: str):
    print(
        f"[AUDIT] {datetime.now()} | "
        f"User: {user_email} | "
        f"{old_role} -> {new_role}"
    )