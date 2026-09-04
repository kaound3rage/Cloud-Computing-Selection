"""
dataset.py — Generator dataset untuk skenario EduPintar
(Intelligent Course Recommendation & Enrollment Forecasting API)

Menghasilkan dataset sintetis yang konsisten (foreign key valid):
  - learner_profiles.csv   (~1000 baris)
  - course_catalog.csv     (~500 baris)
  - learner_activities.csv (~10000 baris)
  - membership_history.csv (~750 baris)

Output disimpan ke DATASET_OUTPUT_DIR (default: dataset/output/).
"""
import argparse
import csv
import logging
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

try:
    from faker import Faker
except ImportError:
    Faker = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"

NAMES = ["Alya Putri", "Bima Santoso", "Citra Dewi", "Dimas Pratama", "Eka Wijaya"]
CATEGORIES = ["Programming", "Data Science", "Business", "Design", "Marketing"]
MEMBERSHIP_PLANS = ["Free", "Plus", "Pro"]
SEGMENTS = ["Beginner", "Intermediate", "Advanced"]
ACTIVITY_TYPES = ["enroll", "complete", "like", "skip", "add_to_wishlist"]
BILLING_PERIODS = ["monthly", "yearly"]
MEMBERSHIP_STATUS = ["active", "cancelled", "expired"]

PLAN_PRICE = {"Free": 0.0, "Plus": 9.99, "Pro": 19.99}

FILENAME_LEARNERS = "learner_profiles.csv"
FILENAME_COURSES = "course_catalog.csv"
FILENAME_ACTIVITIES = "learner_activities.csv"
FILENAME_MEMBERSHIP = "membership_history.csv"

DEFAULT_LEARNERS = 1000
DEFAULT_COURSES = 500
DEFAULT_ACTIVITIES = 10000
DEFAULT_MEMBERSHIP = 750


def _get_faker(seed: Optional[int]) -> Optional["Faker"]:
    """Return a seeded Faker instance when available, else None."""
    if Faker is None:
        return None
    fake = Faker()
    if seed is not None:
        Faker.seed(seed)
        random.seed(seed)
    return fake


def _fake_name(fake: Optional["Faker"]) -> str:
    """Generate a realistic name using the provided Faker instance."""
    if fake is not None:
        return fake.name()
    return f"{random.choice(NAMES)} {random.randint(100, 999)}"


def _fake_date_between(start: date, end: date) -> date:
    """Return a random date in the inclusive range [start, end]."""
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))


def _format_date(value: date) -> str:
    """Format a date as ISO 8601 string."""
    return value.isoformat()


def generate_learner_profiles(n: int, output_dir: Path, fake: Optional["Faker"], seed: Optional[int]) -> list[str]:
    """Generate learner_profiles.csv and return the list of learner_id."""
    today = date.today()
    join_start = today - timedelta(days=3 * 365)
    rows: list[dict[str, Any]] = []
    names: set[str] = set()

    for learner_id in range(1, n + 1):
        name = _fake_name(fake)
        while name in names:
            name = _fake_name(fake)
        names.add(name)

        email = f"learner{learner_id:05d}@edupintar.com"
        if fake is not None:
            email = fake.unique.email(domain="edupintar.com")

        rows.append({
            "learner_id": f"L{learner_id:05d}",
            "name": name,
            "email": email,
            "membership_plan": random.choice(MEMBERSHIP_PLANS),
            "total_courses_completed": random.randint(0, 25),
            "learner_segment": random.choice(SEGMENTS),
            "join_date": _format_date(_fake_date_between(join_start, today)),
        })

    _write_csv(output_dir / FILENAME_LEARNERS, rows)
    logger.info("Generated %d learner profiles -> %s", n, FILENAME_LEARNERS)
    return [row["learner_id"] for row in rows]


def generate_course_catalog(n: int, output_dir: Path, fake: Optional["Faker"]) -> list[str]:
    """Generate course_catalog.csv and return the list of course_id."""
    rows: list[dict[str, Any]] = []

    for course_id in range(1, n + 1):
        rows.append({
            "course_id": f"C{course_id:05d}",
            "title": f"{random.choice(CATEGORIES)} Fundamentals {course_id}",
            "category": random.choice(CATEGORIES),
            "instructor": _fake_name(fake),
            "avg_rating": round(random.uniform(3.5, 5.0), 2),
            "is_premium": random.choice([True, False]),
            "duration_hours": random.randint(2, 40),
        })

    _write_csv(output_dir / FILENAME_COURSES, rows)
    logger.info("Generated %d course catalog rows -> %s", n, FILENAME_COURSES)
    return [row["course_id"] for row in rows]


def generate_learner_activities(
    n: int, output_dir: Path, learner_ids: list[str], course_ids: list[str]
) -> None:
    """Generate learner_activities.csv with valid foreign keys."""
    if not learner_ids or not course_ids:
        raise ValueError("learner_ids and course_ids must not be empty")

    today = date.today()
    activity_start = today - timedelta(days=365)
    rows: list[dict[str, Any]] = []

    for i in range(1, n + 1):
        rows.append({
            "activity_id": f"ACT{i:06d}",
            "learner_id": random.choice(learner_ids),
            "course_id": random.choice(course_ids),
            "activity_type": random.choice(ACTIVITY_TYPES),
            "study_duration_minutes": random.randint(0, 240),
            "activity_date": _format_date(_fake_date_between(activity_start, today)),
        })

    _write_csv(output_dir / FILENAME_ACTIVITIES, rows)
    logger.info("Generated %d learner activities -> %s", n, FILENAME_ACTIVITIES)


def generate_membership_history(n: int, output_dir: Path, learner_ids: list[str]) -> None:
    """Generate membership_history.csv with valid foreign keys."""
    if not learner_ids:
        raise ValueError("learner_ids must not be empty")

    today = date.today()
    history_start = today - timedelta(days=365)
    rows: list[dict[str, Any]] = []

    for _ in range(n):
        plan = random.choice(MEMBERSHIP_PLANS)
        rows.append({
            "learner_id": random.choice(learner_ids),
            "plan": plan,
            "amount": PLAN_PRICE[plan],
            "billing_period": random.choice(BILLING_PERIODS),
            "status": random.choice(MEMBERSHIP_STATUS),
            "start_date": _format_date(_fake_date_between(history_start, today)),
        })

    _write_csv(output_dir / FILENAME_MEMBERSHIP, rows)
    logger.info("Generated %d membership history rows -> %s", n, FILENAME_MEMBERSHIP)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write list of dicts to a CSV file."""
    if not rows:
        raise ValueError(f"No rows to write for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _read_ids(path: Path, column: str) -> list[str]:
    """Read all values of a column from a CSV file."""
    if not path.exists():
        raise FileNotFoundError(f"Required input file missing: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return [row[column] for row in csv.DictReader(f)]


def generate_all(
    output_dir: Optional[Path] = None,
    n_learners: int = DEFAULT_LEARNERS,
    n_courses: int = DEFAULT_COURSES,
    n_activities: int = DEFAULT_ACTIVITIES,
    n_membership: int = DEFAULT_MEMBERSHIP,
    seed: Optional[int] = None,
) -> Path:
    """Generate the full EduPintar dataset."""
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    fake = _get_faker(seed)

    learner_ids = generate_learner_profiles(n_learners, output_dir, fake, seed)
    course_ids = generate_course_catalog(n_courses, output_dir, fake)
    generate_learner_activities(n_activities, output_dir, learner_ids, course_ids)
    generate_membership_history(n_membership, output_dir, learner_ids)

    generated_at = datetime.now().isoformat(timespec="seconds")
    logger.info("Dataset generation complete at %s. Output: %s", generated_at, output_dir)
    return output_dir


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generator dataset sintetis EduPintar")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--learners", type=int, default=DEFAULT_LEARNERS,
                        help=f"Number of learner profiles (default: {DEFAULT_LEARNERS})")
    parser.add_argument("--courses", type=int, default=DEFAULT_COURSES,
                        help=f"Number of courses (default: {DEFAULT_COURSES})")
    parser.add_argument("--activities", type=int, default=DEFAULT_ACTIVITIES,
                        help=f"Number of learner activities (default: {DEFAULT_ACTIVITIES})")
    parser.add_argument("--membership", type=int, default=DEFAULT_MEMBERSHIP,
                        help=f"Number of membership history rows (default: {DEFAULT_MEMBERSHIP})")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    if args.learners < 1 or args.courses < 1 or args.activities < 1 or args.membership < 1:
        logger.error("All dataset sizes must be >= 1")
        return 1

    try:
        generate_all(
            output_dir=args.output,
            n_learners=args.learners,
            n_courses=args.courses,
            n_activities=args.activities,
            n_membership=args.membership,
            seed=args.seed,
        )
    except (ValueError, FileNotFoundError, OSError) as exc:
        logger.error("Dataset generation failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
