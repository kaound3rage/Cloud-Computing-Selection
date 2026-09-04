"""
dataset.py — Generator dataset untuk skenario EduPintar
(Intelligent Course Recommendation & Enrollment Forecasting API)

TODO:
- Generate learner_profiles.csv   (~1000 baris)
    kolom minimal: learner_id, membership_plan, total_courses_completed,
                   learner_segment, join_date, ...
- Generate course_catalog.csv     (~500 baris)
    kolom minimal: course_id, title, category, instructor, avg_rating,
                   is_premium, duration_hours, ...
- Generate learner_activities.csv (~10000 baris)
    kolom minimal: learner_id, course_id, activity_type
                   (enroll/complete/like/skip/add_to_wishlist),
                   study_duration_minutes, activity_date
- Generate membership_history.csv (~750 baris)
    kolom minimal: learner_id, plan (Free/Plus/Pro), billing_period,
                   amount, status

Gunakan library seperti `faker` dan `random` untuk membuat data sintetis
yang realistis dan konsisten (foreign key antar file harus valid).
"""
import csv
from datetime import date, timedelta
import random
from pathlib import Path

try:
    from faker import Faker
except ImportError:
    Faker = None

OUTPUT_DIR = Path(__file__).parent / "output"
NAMES = ["Alya Putri", "Bima Santoso", "Citra Dewi", "Dimas Pratama", "Eka Wijaya"]


def _fake_name():
    return Faker().name() if Faker else random.choice(NAMES)


def _fake_date(days_ago):
    return date.today() - timedelta(days=random.randint(0, days_ago))


def generate_learner_profiles(n=1000):
    rows = []
    for learner_id in range(1, n + 1):
        rows.append({
            "learner_id": f"L{learner_id:05d}",
            "name": _fake_name(),
            "membership_plan": random.choice(["Free", "Plus", "Pro"]),
            "total_courses_completed": random.randint(0, 25),
            "learner_segment": random.choice(["Beginner", "Intermediate", "Advanced"]),
            "join_date": _fake_date(3 * 365),
        })
    _write_csv("learner_profiles.csv", rows)
    return [row["learner_id"] for row in rows]


def generate_course_catalog(n=500):
    categories = ["Programming", "Data Science", "Business", "Design", "Marketing"]
    rows = []
    for course_id in range(1, n + 1):
        rows.append({
            "course_id": f"C{course_id:05d}",
            "title": f"{random.choice(categories)} Fundamentals {course_id}",
            "category": random.choice(categories),
            "instructor": _fake_name(),
            "avg_rating": round(random.uniform(3.5, 5.0), 2),
            "is_premium": random.choice([True, False]),
            "duration_hours": random.randint(2, 40),
        })
    _write_csv("course_catalog.csv", rows)
    return [row["course_id"] for row in rows]


def generate_learner_activities(n=10000):
    learner_ids = _read_ids("learner_profiles.csv", "learner_id")
    course_ids = _read_ids("course_catalog.csv", "course_id")
    activity_types = ["enroll", "complete", "like", "skip", "add_to_wishlist"]
    rows = []
    for _ in range(n):
        rows.append({
            "learner_id": random.choice(learner_ids),
            "course_id": random.choice(course_ids),
            "activity_type": random.choice(activity_types),
            "study_duration_minutes": random.randint(0, 240),
            "activity_date": _fake_date(365),
        })
    _write_csv("learner_activities.csv", rows)


def generate_membership_history(n=750):
    learner_ids = _read_ids("learner_profiles.csv", "learner_id")
    rows = []
    for _ in range(n):
        plan = random.choice(["Free", "Plus", "Pro"])
        rows.append({
            "learner_id": random.choice(learner_ids),
            "plan": plan,
            "billing_period": random.choice(["monthly", "yearly"]),
            "amount": {"Free": 0, "Plus": 9.99, "Pro": 19.99}[plan],
            "status": random.choice(["active", "cancelled", "expired"]),
        })
    _write_csv("membership_history.csv", rows)


def _write_csv(filename, rows):
    with (OUTPUT_DIR / filename).open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _read_ids(filename, column):
    with (OUTPUT_DIR / filename).open(newline="", encoding="utf-8") as input_file:
        return [row[column] for row in csv.DictReader(input_file)]


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating learner_profiles.csv ...")
    generate_learner_profiles()
    print("Generating course_catalog.csv ...")
    generate_course_catalog()
    print("Generating learner_activities.csv ...")
    generate_learner_activities()
    print("Generating membership_history.csv ...")
    generate_membership_history()
    print(f"Done. Dataset tersimpan di {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
