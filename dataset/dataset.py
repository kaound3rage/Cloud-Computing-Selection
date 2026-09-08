"""
dataset.py — Generator dataset untuk skenario AgroSense
(Smart Crop Risk & Yield Forecasting Platform — TaniCerdas)

Menghasilkan dataset sintetis yang konsisten (foreign key valid):
  - farm_profiles.csv     (~1000 baris):  farm_id, region, soil_type,
                                          farm_size_hectare, farmer_segment, irrigation_type
  - crop_catalog.csv      (~500 baris):   crop_id, crop_name, crop_category,
                                          planting_season, avg_yield_ton_per_ha, is_premium_variety
  - farm_activities.csv   (~10000 baris): farm_id, crop_id, activity_type, activity_volume_or_duration
  - harvest_history.csv   (~750 baris):   season, crop_id, region, area_planted_ha,
                                          quantity_harvested_ton, market_price, status

Secara sengaja disisipkan ~2-3% data rusak/outlier (negatif, 0/null pada kolom
wajib, nilai ekstrem) untuk menguji tahap validasi kualitas data di ETL Glue.

Output disimpan ke --output (default: dataset/output/).
"""
import argparse
import csv
import logging
import random
import sys
from pathlib import Path
from typing import Any, Optional

try:
    from faker import Faker
except ImportError:  # pragma: no cover - fallback jika faker tidak terinstall
    Faker = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"

REGIONS = ["Jawa Tengah", "Jawa Barat", "Jawa Timur", "Sumatera Utara", "Sulawesi Selatan", "Kalimantan Barat", "Bali", "Nusa Tenggara Barat"]
SOIL_TYPES = ["Aluvial", "Andosol", "Grumusol", "Latosol", "Podsolik", "Regosol", "Gambut"]
FARMER_SEGMENTS = ["subsisten", "komersial", "koperasi"]
IRRIGATION_TYPES = ["irigasi_teknis", "irigasi_setengah_teknis", "irigasi_sederhana", "tadah_hujan", "pompa"]

CROP_CATEGORIES = ["padi", "palawija", "hortikultura"]
PLANTING_SEASONS = ["musim_hujan", "musim_kemarau", "sepanjang_tahun"]
CROP_NAMES = {
    "padi": ["Padi IR64", "Padi Ciherang", "Padi Mekongga"],
    "palawija": ["Jagung Hibrida", "Kedelai", "Kacang Tanah", "Ubi Kayu"],
    "hortikultura": ["Cabai Merah", "Bawang Merah", "Tomat", "Kentang", "Kol"],
}
ACTIVITY_TYPES = ["planting", "fertilizing", "pest_control", "irrigation", "harvest"]
HARVEST_STATUS = ["berhasil", "gagal_sebagian", "gagal"]

MAX_CORRUPTION_FRACTION = 0.03

FILENAME_FARMS = "farm_profiles.csv"
FILENAME_CROPS = "crop_catalog.csv"
FILENAME_ACTIVITIES = "farm_activities.csv"
FILENAME_HARVEST = "harvest_history.csv"

DEFAULT_FARMS = 1000
DEFAULT_CROPS = 500
DEFAULT_ACTIVITIES = 10000
DEFAULT_HARVEST = 750


def _get_faker(seed: int | None) -> Optional["Faker"]:
    """Return a seeded Faker instance when available, else None."""
    if Faker is None:
        return None
    fake = Faker()
    if seed is not None:
        Faker.seed(seed)
        random.seed(seed)
    return fake


def generate_farm_profiles(
    n: int, output_dir: Path, fake: Optional["Faker"], corr_rows: set[int]
) -> list[str]:
    """Generate farm_profiles.csv and return list of farm_id."""
    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        farm_id = f"F{i:05d}"
        # ~2-3% data rusak: farm_size_hectare 0 atau None
        corrupted = i - 1 in corr_rows
        if corrupted and random.random() < 0.5:
            farm_size = 0
        else:
            farm_size = round(random.uniform(0.5, 50.0), 2)
        rows.append({
            "farm_id": farm_id,
            "region": random.choice(REGIONS),
            "soil_type": random.choice(SOIL_TYPES),
            "farm_size_hectare": farm_size,
            "farmer_segment": random.choice(FARMER_SEGMENTS),
            "irrigation_type": random.choice(IRRIGATION_TYPES),
        })
    _write_csv(output_dir / FILENAME_FARMS, rows)
    logger.info("Generated %d farm profiles -> %s", n, FILENAME_FARMS)
    return [row["farm_id"] for row in rows]


def generate_crop_catalog(n: int, output_dir: Path) -> list[str]:
    """Generate crop_catalog.csv and return list of crop_id."""
    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        category = random.choice(CROP_CATEGORIES)
        crop_name = random.choice(CROP_NAMES[category])
        avg_yield = random.uniform(1.0, 12.0)
        rows.append({
            "crop_id": f"C{i:05d}",
            "crop_name": crop_name,
            "crop_category": category,
            "planting_season": random.choice(PLANTING_SEASONS),
            "avg_yield_ton_per_ha": round(avg_yield, 2),
            "is_premium_variety": random.choice([True, False]),
        })
    _write_csv(output_dir / FILENAME_CROPS, rows)
    logger.info("Generated %d crop catalog rows -> %s", n, FILENAME_CROPS)
    return [row["crop_id"] for row in rows]


def generate_farm_activities(
    n: int,
    output_dir: Path,
    farm_ids: list[str],
    crop_ids: list[str],
    corr_rows: set[int],
) -> None:
    """Generate farm_activities.csv with valid foreign keys + corrupted rows."""
    if not farm_ids or not crop_ids:
        raise ValueError("farm_ids and crop_ids must not be empty")

    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        activity_type = random.choice(ACTIVITY_TYPES)
        corrupted = i - 1 in corr_rows
        if corrupted and random.random() < 0.5:
            # aktivitas negatif -> invalid di ETL
            volume = -abs(round(random.uniform(0.5, 10.0), 2))
        else:
            volume = round(random.uniform(0.5, 60.0), 2)
        rows.append({
            "farm_id": random.choice(farm_ids),
            "crop_id": random.choice(crop_ids),
            "activity_type": activity_type,
            "activity_volume_or_duration": volume,
        })

    _write_csv(output_dir / FILENAME_ACTIVITIES, rows)
    logger.info("Generated %d farm activities -> %s", n, FILENAME_ACTIVITIES)


def generate_harvest_history(
    n: int,
    output_dir: Path,
    crop_ids: list[str],
    corr_rows: set[int],
) -> None:
    """Generate harvest_history.csv with valid crop_id + corrupted rows."""
    if not crop_ids:
        raise ValueError("crop_ids must not be empty")

    seasons = [f"season_{y}-{num}" for y in range(2018, 2027) for num in (1, 2)]
    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        corrupted = i - 1 in corr_rows
        if corrupted and random.random() < 0.5:
            # quantity ekstrem tinggi -> outlier
            qty = round(random.uniform(5e5, 1e6), 2)
        else:
            area = round(random.uniform(1.0, 80.0), 2)
            qty = round(area * random.uniform(1.2, 6.0), 2)
        rows.append({
            "season": random.choice(seasons),
            "crop_id": random.choice(crop_ids),
            "region": random.choice(REGIONS),
            "area_planted_ha": round(random.uniform(1.0, 80.0), 2) if not corrupted or random.random() < 0.5 else 0,
            "quantity_harvested_ton": qty,
            "market_price": round(random.uniform(3000.0, 20000.0), 2),
            "status": random.choice(HARVEST_STATUS),
        })

    _write_csv(output_dir / FILENAME_HARVEST, rows)
    logger.info("Generated %d harvest history rows -> %s", n, FILENAME_HARVEST)


def pick_corruption_rows(total: int, fraction: float = 0.025) -> set[int]:
    """Pick ~fraction% of row indices to corrupt (deterministic via seed)."""
    count = max(1, int(total * fraction))
    return set(random.sample(range(total), count))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write list of dicts to a CSV file."""
    if not rows:
        raise ValueError(f"No rows to write for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def generate_all(
    output_dir: Path | None = None,
    n_farms: int = DEFAULT_FARMS,
    n_crops: int = DEFAULT_CROPS,
    n_activities: int = DEFAULT_ACTIVITIES,
    n_harvest: int = DEFAULT_HARVEST,
    seed: int | None = None,
) -> Path:
    """Generate the full AgroSense dataset."""
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    fake = _get_faker(seed)

    farm_ids = generate_farm_profiles(
        n_farms, output_dir, fake, pick_corruption_rows(n_farms)
    )
    crop_ids = generate_crop_catalog(n_crops, output_dir)
    generate_farm_activities(
        n_activities, output_dir, farm_ids, crop_ids, pick_corruption_rows(n_activities)
    )
    generate_harvest_history(
        n_harvest, output_dir, crop_ids, pick_corruption_rows(n_harvest)
    )

    logger.info("Dataset generation complete. Output: %s", output_dir)
    return output_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generator dataset sintetis AgroSense")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--farms", type=int, default=DEFAULT_FARMS,
                        help=f"Number of farm profiles (default: {DEFAULT_FARMS})")
    parser.add_argument("--crops", type=int, default=DEFAULT_CROPS,
                        help=f"Number of crops (default: {DEFAULT_CROPS})")
    parser.add_argument("--activities", type=int, default=DEFAULT_ACTIVITIES,
                        help=f"Number of farm activities (default: {DEFAULT_ACTIVITIES})")
    parser.add_argument("--harvest", type=int, default=DEFAULT_HARVEST,
                        help=f"Number of harvest history rows (default: {DEFAULT_HARVEST})")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if min(args.farms, args.crops, args.activities, args.harvest) < 1:
        logger.error("All dataset sizes must be >= 1")
        return 1

    try:
        generate_all(
            output_dir=args.output,
            n_farms=args.farms,
            n_crops=args.crops,
            n_activities=args.activities,
            n_harvest=args.harvest,
            seed=args.seed,
        )
    except (ValueError, FileNotFoundError, OSError) as exc:
        logger.error("Dataset generation failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
