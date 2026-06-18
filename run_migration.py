"""Run database migration to add new patient columns."""
from database import engine
from sqlalchemy import text

stmts = [
    "ALTER TABLE patients ADD COLUMN ic_number VARCHAR(20) UNIQUE AFTER patient_id",
    "ALTER TABLE patients ADD COLUMN date_of_birth DATE AFTER age",
    "ALTER TABLE patients ADD COLUMN phone_number VARCHAR(20) AFTER date_of_birth",
    "ALTER TABLE patients ADD COLUMN home_address TEXT AFTER phone_number",
    "ALTER TABLE patients ADD COLUMN allergies TEXT AFTER home_address",
]

with engine.connect() as conn:
    for s in stmts:
        try:
            conn.execute(text(s))
            conn.commit()
            print(f"OK: {s[:60]}")
        except Exception as e:
            if "Duplicate column" in str(e):
                print(f"SKIP (exists): {s[:60]}")
            else:
                print(f"ERR: {e}")

    conn.execute(text(
        "UPDATE patients SET ic_number='900101-01-1234', date_of_birth='1990-01-01', "
        "phone_number='012-3456789', home_address='123 Jalan Merdeka, KL', allergies='None' "
        "WHERE name='Ali bin Abu' AND ic_number IS NULL"
    ))
    conn.commit()
    print("Seed patient updated.")

print("Migration done!")
