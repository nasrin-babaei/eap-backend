from app.database import SessionLocal
from app.models.request_type import RequestType
# US-017 (M5): slug is NOT NULL, so the seed has to fill it. It is derived from
# the name with the same function the create endpoint uses, so a seeded type and
# an admin-created type can never end up with slugs built by different rules.
from app.services.request_type_service import slugify


def seed_request_types():
    db = SessionLocal()

    try:
        types = [
            {
                "name": "Hardware & Devices",
                "description": "Laptop, monitor, peripherals etc.",
                "prefix": "HD",
                "counter": 0,
                "is_active": True,
            },
            {
                "name": "Software & Access",
                "description": "Software licenses and access rights",
                "prefix": "SA",
                "counter": 0,
                "is_active": True,
            },
            {
                "name": "Workplace & Facilities",
                "description": "Office equipment and facilities",
                "prefix": "WF",
                "counter": 0,
                "is_active": True,
            },
            {
                "name": "Human Resources",
                "description": "HR related requests",
                "prefix": "HR",
                "counter": 0,
                "is_active": True,
            },
            {
                "name": "Financial & Travel",
                "description": "Financial and travel approvals",
                "prefix": "FT",
                "counter": 0,
                "is_active": True,
            },
            {
                "name": "Security & Compliance",
                "description": "Security and compliance requests",
                "prefix": "SC",
                "counter": 0,
                "is_active": True,
            },
            {
                "name": "Other",
                "description": "Other requests",
                "prefix": "O",
                "counter": 0,
                "is_active": True,
            },
        ]

        for t in types:
            existing = (
                db.query(RequestType)
                .filter(RequestType.name == t["name"])
                .first()
            )

            if existing:
                print(f"{t['name']} already exists, skipping")
                continue

            request_type = RequestType(
                slug=slugify(t["name"]),
                name=t["name"],
                description=t["description"],
                prefix=t["prefix"],
                counter=t["counter"],
                is_active=t["is_active"],
            )

            db.add(request_type)
            print(f"Created request type: {t['name']} ({t['prefix']}) -> {request_type.slug}")

        db.commit()
        print("Request types seeded successfully.")

    except Exception as e:
        db.rollback()
        print(f"Error seeding request types: {e}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed_request_types()