from app.database import SessionLocal
from app.models.user import User
from app.core.security import hash_password


def create_users():
    db = SessionLocal()
    try:
        users = [
            {
                "email": "admin@company.com",
                "password": "Admin123!",
                "name": "System Admin",
                "role": "admin"
            },
            {
                "email": "requester@company.com",
                "password": "Requester123!",
                "name": "Test Requester",
                "role": "requester"
            },
            {
                "email": "approver@company.com",
                "password": "Approver123!",
                "name": "Test Approver",
                "role": "approver"
            }
        ]

        for u in users:
            existing = db.query(User).filter(User.email == u["email"]).first()

            if existing:
                print(f"{u['email']} already exists, skipping")
                continue

            user = User(
                email=u["email"],
                hashed_password=hash_password(u["password"]),
                name=u["name"],
                role=u["role"],
                is_active=True
            )

            db.add(user)
            print(f"{u['email']} created successfully")

        db.commit()

    finally:
        db.close()


if __name__ == "__main__":
    create_users()