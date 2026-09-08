"""
setup-bucket.py — Setup Amazon S3 bucket untuk pipeline AgroSense
(Smart Crop Risk & Yield Forecasting Platform — TaniCerdas)

Membuat struktur folder di S3 (placeholder object berakhiran "/", karena S3
tidak memiliki folder fisik) lalu meng-upload 4 file CSV raw data hasil
dataset.py dari dataset/output/:

    s3://[nama-bucket]/
    ├── raw-data/
    │   ├── farm-profiles/       <- farm_profiles.csv
    │   ├── crop-catalog/        <- crop_catalog.csv
    │   ├── farm-activities/     <- farm_activities.csv
    │   └── harvest-history/     <- harvest_history.csv
    └── processed-data/
        ├── farm_activity_matrix/   (diisi oleh ETL Glue: ETL/sparks.py)
        ├── crop_stats/
        ├── farm_features/
        └── rejected_records/

Konfigurasi (arg CLI menang atas env var — lihat .env.example):
  --bucket / S3_BUCKET    nama bucket target (wajib)
  --region / AWS_REGION   region bucket (default: config AWS / us-east-1)

Kredensial AWS mengikuti default credential chain boto3 (env vars,
AWS_PROFILE, ~/.aws/credentials, IAM role) — tidak pernah di-hardcode.

Contoh:
    python dataset/setup-bucket.py --bucket agrosense-raw --region ap-southeast-1
    python dataset/setup-bucket.py --no-upload    # hanya buat struktur folder
"""
import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_REGION = "us-east-1"

# Struktur folder target (placeholder key berakhiran "/")
RAW_FOLDERS = [
    "raw-data/farm-profiles/",
    "raw-data/crop-catalog/",
    "raw-data/farm-activities/",
    "raw-data/harvest-history/",
]
PROCESSED_FOLDERS = [
    "processed-data/farm_activity_matrix/",
    "processed-data/crop_stats/",
    "processed-data/farm_features/",
    "processed-data/rejected_records/",
]
ALL_FOLDERS = RAW_FOLDERS + PROCESSED_FOLDERS

# CSV raw data (hasil dataset.py) -> prefix tujuan di S3
UPLOAD_MAP = {
    "farm_profiles.csv": "raw-data/farm-profiles/",
    "crop_catalog.csv": "raw-data/crop-catalog/",
    "farm_activities.csv": "raw-data/farm-activities/",
    "harvest_history.csv": "raw-data/harvest-history/",
}


def load_env_file(path: Path = BASE_DIR / ".env") -> None:
    """Muat KEY=VALUE dari dataset/.env ke os.environ (tanpa menimpa nilai eksisting).

    Loader minimal tanpa dependency python-dotenv; baris kosong dan komentar (#)
    diabaikan. Dipanggil sebelum parse_args agar env var terbaca sebagai default CLI.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    logger.info("Loaded env vars from %s", path)


def build_s3_client(region: str | None) -> tuple[Any, str]:
    """Buat S3 client boto3 dan resolve region yang efektif dipakai."""
    session = boto3.Session(region_name=region)
    resolved = session.region_name or region or DEFAULT_REGION
    return session.client("s3", region_name=resolved), resolved


def ensure_bucket(s3: Any, bucket: str, region: str) -> bool:
    """Pastikan bucket tersedia; buat bila belum ada. Return True jika baru dibuat."""
    try:
        s3.head_bucket(Bucket=bucket)
        logger.info("Bucket exists: s3://%s", bucket)
        return False
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in ("404", "NoSuchBucket"):
            raise

    params: dict[str, Any] = {"Bucket": bucket}
    if region != "us-east-1":
        params["CreateBucketConfiguration"] = {"LocationConstraint": region}
    try:
        s3.create_bucket(**params)
        logger.info("Bucket created: s3://%s (%s)", bucket, region)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            logger.info("Bucket already available: s3://%s", bucket)
        else:
            raise

    # Bucket khusus data pipeline — blokir seluruh akses publik.
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    return True


def _head_exists(s3: Any, bucket: str, key: str) -> bool:
    """Cek apakah object key ada di bucket (False untuk 404, raise error lain)."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def create_folder_structure(s3: Any, bucket: str) -> list[str]:
    """Buat placeholder folder S3 yang belum ada. Return daftar folder baru."""
    created: list[str] = []
    for folder in ALL_FOLDERS:
        if _head_exists(s3, bucket, folder):
            logger.info("Folder exists: s3://%s/%s", bucket, folder)
            continue
        s3.put_object(Bucket=bucket, Key=folder, Body=b"")
        created.append(folder)
        logger.info("Folder created: s3://%s/%s", bucket, folder)
    return created


def upload_raw_data(s3: Any, bucket: str, output_dir: Path) -> list[str]:
    """Upload 4 CSV raw data dari output_dir ke folder raw-data/ masing-masing.

    File yang belum ada dilewati dengan warning (generate dulu via dataset.py).
    Return daftar S3 key yang berhasil di-upload.
    """
    uploaded: list[str] = []
    for filename, prefix in UPLOAD_MAP.items():
        local_path = output_dir / filename
        if not local_path.is_file():
            logger.warning(
                "Skipping %s — tidak ditemukan di %s (generate dulu: python dataset/dataset.py)",
                filename,
                output_dir,
            )
            continue
        key = f"{prefix}{filename}"
        s3.upload_file(str(local_path), bucket, key)
        uploaded.append(key)
        logger.info(
            "Uploaded: s3://%s/%s (%.1f KB)",
            bucket,
            key,
            local_path.stat().st_size / 1024,
        )
    return uploaded


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Setup S3 bucket AgroSense: buat struktur folder + upload raw data"
    )
    parser.add_argument("--bucket", "-b", default=os.environ.get("S3_BUCKET"),
                        help="Nama S3 bucket target (default: env S3_BUCKET)")
    parser.add_argument("--region", "-r",
                        default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
                        help="Region AWS (default: env AWS_REGION / config AWS)")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"Direktori sumber CSV raw data (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--no-upload", action="store_true",
                        help="Hanya buat struktur folder, tanpa upload CSV")
    args = parser.parse_args(argv)
    if not args.bucket:
        parser.error("--bucket / env S3_BUCKET wajib diisi")
    return args


def main(argv: list[str] | None = None) -> int:
    load_env_file()  # sebelum parse_args agar env var menjadi default CLI
    args = parse_args(argv)

    try:
        s3, region = build_s3_client(args.region)
        logger.info("Region: %s | Bucket target: s3://%s", region, args.bucket)

        ensure_bucket(s3, args.bucket, region)
        create_folder_structure(s3, args.bucket)

        if args.no_upload:
            logger.info("--no-upload aktif: CSV raw data tidak di-upload")
        else:
            uploaded = upload_raw_data(s3, args.bucket, args.output)
            if not uploaded:
                logger.warning(
                    "Tidak ada file yang ter-upload — generate dataset dulu: python dataset/dataset.py"
                )

        logger.info(
            "Struktur bucket s3://%s:\n%s",
            args.bucket,
            "\n".join(f"  - s3://{args.bucket}/{folder}" for folder in ALL_FOLDERS),
        )
    except ClientError as exc:
        logger.error("AWS API error: %s", exc)
        return 1
    except NoCredentialsError:
        logger.error(
            "AWS credentials tidak ditemukan — isi env AWS_ACCESS_KEY_ID/"
            "AWS_SECRET_ACCESS_KEY, gunakan AWS_PROFILE, atau ~/.aws/credentials"
        )
        return 1
    except (OSError, ValueError) as exc:
        logger.error("Setup bucket gagal: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())