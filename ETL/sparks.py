"""
ETL/sparks.py — AWS Glue PySpark job untuk AgroSense
(Smart Crop Risk & Yield Forecasting Platform)

Membaca 4 tabel dari Glue Data Catalog (database: agrosense_database):
  - farm_profiles
  - crop_catalog
  - farm_activities
  - harvest_history

Dua tahap:
1. VALIDASI KUALITAS DATA
   Filter record tidak valid (nilai negatif, null kolom wajib, nilai di luar
   rentang wajar). Record yang ditolak ditulis ke:
     s3://[BUCKET]/processed-data/rejected_records/   (Parquet)
   dengan kolom tambahan `rejection_reason`.

2. FEATURE ENGINEERING (dari data valid) -> 3 output Parquet:
     s3://[BUCKET]/processed-data/
       farm_activity_matrix/  (agregasi aktivitas per farm x crop)
       crop_stats/            (statistik hasil panen per crop)
       farm_features/         (fitur gabungan per farm untuk model risiko)

Usage (AWS Glue):
  aws glue start-job-run --job-name [JOB_NAME] \
    --arguments '{"--S3_BUCKET":"my-bucket","--DATABASE_NAME":"agrosense_database"}'

Bisa dijalankan lokal: spark-submit ETL/sparks.py --JOB_NAME test --S3_BUCKET x --DATABASE_NAME y
"""
import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.transforms import *  # noqa: F401,F403
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import DataFrame, functions as F
from pyspark.sql.functions import col, count, countDistinct, lit, trim, when
from pyspark.sql.window import Window

args = getResolvedOptions(sys.argv, ["JOB_NAME", "S3_BUCKET", "DATABASE_NAME"])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

S3_BUCKET = args["S3_BUCKET"]
DATABASE_NAME = args["DATABASE_NAME"]
OUTPUT_BASE = f"s3://{S3_BUCKET}/processed-data"

REASON_NEGATIVE = "nilai_negatif"
REASON_NULL_REQUIRED = "null_kolom_wajib"
REASON_OUT_OF_RANGE = "nilai_di_luar_rentang"


def read_glue_table(table_name: str) -> DataFrame:
    """Baca tabel dari Glue Data Catalog dengan error handling."""
    try:
        df = glueContext.create_dynamic_frame.from_catalog(
            database=DATABASE_NAME, table_name=table_name
        ).toDF()
        print(f"[INFO] Loaded table: {table_name} ({df.count()} rows)")
        return df
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to load table {table_name}: {exc}")
        raise


# ---------------------------------------------------------------------------
# TAHAP 1: VALIDASI KUALITAS DATA
# ---------------------------------------------------------------------------
def validate_farms(df: DataFrame) -> list[DataFrame]:
    """Validasi farm_profiles. Return [valid_df, rejected_df]."""
    required = ["farm_id", "region", "soil_type", "farmer_segment"]
    cond_null = None
    for c in required:
        cond = col(c).isNull() | (trim(col(c).cast("string")) == "")
        cond_null = cond if cond_null is None else (cond_null | cond)

    cond_neg = (col("farm_size_hectare") < 0) | (col("farm_size_hectare") == 0)
    cond_range = col("farm_size_hectare") > 1000  # luar rentang wajar

    valid = df.filter(~(cond_null | cond_neg | cond_range))
    rejected = df.where(cond_null | cond_neg | cond_range).withColumn(
        "rejection_reason",
        when(cond_null, lit(REASON_NULL_REQUIRED))
        .when(cond_neg, lit(REASON_NEGATIVE))
        .otherwise(lit(REASON_OUT_OF_RANGE)),
    )
    return [valid, rejected]


def validate_crops(df: DataFrame) -> list[DataFrame]:
    """Validasi crop_catalog. Return [valid_df, rejected_df]."""
    required = ["crop_id", "crop_name", "crop_category"]
    cond_null = None
    for c in required:
        cond = col(c).isNull() | (trim(col(c).cast("string")) == "")
        cond_null = cond if cond_null is None else (cond_null | cond)

    cond_neg = col("avg_yield_ton_per_ha") < 0
    cond_range = col("avg_yield_ton_per_ha") > 100

    valid = df.filter(~(cond_null | cond_neg | cond_range))
    rejected = df.where(cond_null | cond_neg | cond_range).withColumn(
        "rejection_reason",
        when(cond_null, lit(REASON_NULL_REQUIRED))
        .when(cond_neg, lit(REASON_NEGATIVE))
        .otherwise(lit(REASON_OUT_OF_RANGE)),
    )
    return [valid, rejected]


def validate_activities(df: DataFrame) -> list[DataFrame]:
    """Validasi farm_activities. Return [valid_df, rejected_df]."""
    required = ["farm_id", "crop_id", "activity_type"]
    cond_null = None
    for c in required:
        cond = col(c).isNull() | (trim(col(c).cast("string")) == "")
        cond_null = cond if cond_null is None else (cond_null | cond)

    cond_neg = col("activity_volume_or_duration") < 0
    cond_range = col("activity_volume_or_duration") > 10000

    valid = df.filter(~(cond_null | cond_neg | cond_range))
    rejected = df.where(cond_null | cond_neg | cond_range).withColumn(
        "rejection_reason",
        when(cond_null, lit(REASON_NULL_REQUIRED))
        .when(cond_neg, lit(REASON_NEGATIVE))
        .otherwise(lit(REASON_OUT_OF_RANGE)),
    )
    return [valid, rejected]


def validate_harvest(df: DataFrame) -> list[DataFrame]:
    """Validasi harvest_history. Return [valid_df, rejected_df]."""
    required = ["season", "crop_id", "status"]
    cond_null = None
    for c in required:
        cond = col(c).isNull() | (trim(col(c).cast("string")) == "")
        cond_null = cond if cond_null is None else (cond_null | cond)

    cond_neg = (
        (col("area_planted_ha") < 0)
        | (col("quantity_harvested_ton") < 0)
        | (col("market_price") < 0)
    )
    cond_zero = col("area_planted_ha") == 0
    cond_outlier = col("quantity_harvested_ton") > 10000  # ekstrem tinggi

    valid = df.filter(~(cond_null | cond_neg | cond_zero | cond_outlier))
    rejected = df.where(cond_null | cond_neg | cond_zero | cond_outlier).withColumn(
        "rejection_reason",
        when(cond_null, lit(REASON_NULL_REQUIRED))
        .when(cond_neg | cond_zero, lit(REASON_NEGATIVE))
        .otherwise(lit(REASON_OUT_OF_RANGE)),
    )
    return [valid, rejected]


# ---------------------------------------------------------------------------
# TAHAP 2: FEATURE ENGINEERING
# ---------------------------------------------------------------------------
def build_farm_activity_matrix(activities_df: DataFrame) -> DataFrame:
    """Agregasi aktivitas per farm x crop (count per aktivitas + total)."""
    return (
        activities_df.groupBy("farm_id", "crop_id")
        .agg(
            count(when(col("activity_type") == "planting", 1)).alias("planting_count"),
            count(when(col("activity_type") == "fertilizing", 1)).alias("fertilizing_count"),
            count(when(col("activity_type") == "pest_control", 1)).alias("pest_control_count"),
            count(when(col("activity_type") == "irrigation", 1)).alias("irrigation_count"),
            count(when(col("activity_type") == "harvest", 1)).alias("harvest_count"),
            F.sum("activity_volume_or_duration").alias("total_volume"),
        )
    )


def build_crop_stats(harvest_df: DataFrame) -> DataFrame:
    """Statistik hasil panen per crop (rata-rata yield, tingkat keberhasilan)."""
    stats = harvest_df.groupBy("crop_id").agg(
        count("season").alias("record_count"),
        F.sum("area_planted_ha").alias("total_area_ha"),
        F.sum("quantity_harvested_ton").alias("total_quantity_ton"),
        F.avg("quantity_harvested_ton").alias("avg_quantity_ton"),
        F.avg("market_price").alias("avg_market_price"),
        # yield per hektar per record, lalu rata-rata
        F.avg(col("quantity_harvested_ton") / col("area_planted_ha")).alias("avg_yield_ton_per_ha"),
    ).withColumn(
        "success_rate",
        F.count(when(col("status") == "berhasil", 1)) / count("season"),
    ).withColumn(
        "partial_failure_rate",
        F.count(when(col("status") == "gagal_sebagian", 1)) / count("season"),
    ).withColumn(
        "failure_rate",
        F.count(when(col("status") == "gagal", 1)) / count("season"),
    )
    return stats


def build_farm_features(
    farms_df: DataFrame, activities_df: DataFrame, harvest_df: DataFrame
) -> DataFrame:
    """Fitur gabungan per farm untuk model risiko gagal panen."""
    activity = activities_df.groupBy("farm_id").agg(
        count("crop_id").alias("total_activities"),
        F.sum("activity_volume_or_duration").alias("total_activity_volume"),
        countDistinct("crop_id").alias("crop_diversity"),
        F.avg("activity_volume_or_duration").alias("avg_activity_volume"),
    )

    # Agregasi hasil panen per region (farm -> region di crop_stats-level region)
    harvest = harvest_df.groupBy("region").agg(
        F.avg("quantity_harvested_ton").alias("region_avg_quantity"),
        F.avg("market_price").alias("region_avg_price"),
    )

    features = (
        farms_df.alias("f")
        # farm_size 0 sudah di-filter di tahap validasi, jadi aman divide
        .withColumn(
            "has_negative_yield",
            lit(0),
        )  # placeholder; risk label di-training di notebook
        .join(activity.alias("a"), col("f.farm_id") == col("a.farm_id"), "left")
        .join(harvest.alias("h"), col("f.region") == col("h.region"), "left")
        .select(
            col("f.farm_id"),
            col("f.region"),
            col("f.soil_type"),
            col("f.farmer_segment"),
            col("f.irrigation_type"),
            col("f.farm_size_hectare"),
            when(col("a.total_activities").isNull(), 0).otherwise(col("a.total_activities")).alias("total_activities"),
            when(col("a.total_activity_volume").isNull(), 0).otherwise(col("a.total_activity_volume")).alias("total_activity_volume"),
            when(col("a.avg_activity_volume").isNull(), 0).otherwise(col("a.avg_activity_volume")).alias("avg_activity_volume"),
            when(col("a.crop_diversity").isNull(), 0).otherwise(col("a.crop_diversity")).alias("crop_diversity"),
            when(col("h.region_avg_quantity").isNull(), 0).otherwise(col("h.region_avg_quantity")).alias("region_avg_quantity"),
            when(col("h.region_avg_price").isNull(), 0).otherwise(col("h.region_avg_price")).alias("region_avg_price"),
        )
    )
    return features


def assert_column(df: DataFrame, name: str) -> None:
    """Assert kolom wajib ada; fail fast untuk kualitas data."""
    if name not in df.columns:
        raise ValueError(f"Column '{name}' is required but missing from {df}")


def write_parquet(df: DataFrame, output_path: str) -> None:
    """Write DataFrame ke S3 Parquet (overwrite)."""
    print(f"[INFO] Writing {df.count()} rows to {output_path}")
    df.write.mode("overwrite").parquet(output_path)
    print(f"[INFO] Written: {output_path}")


def main() -> None:
    print(f"[INFO] Starting job {args['JOB_NAME']}")
    print(f"[INFO] S3 bucket: {S3_BUCKET}, Databases: {DATABASE_NAME}")

    # ---- TAHAP 1: VALIDASI ----
    farms_df = read_glue_table("farm_profiles")
    crops_df = read_glue_table("crop_catalog")
    activities_df = read_glue_table("farm_activities")
    harvest_df = read_glue_table("harvest_history")

    farms_valid, farms_rejected = validate_farms(farms_df)
    crops_valid, crops_rejected = validate_crops(crops_df)
    activities_valid, activities_rejected = validate_activities(activities_df)
    harvest_valid, harvest_rejected = validate_harvest(harvest_df)

    rejected = farms_rejected.unionByName(crops_rejected, allowMissingColumns=True) \
        .unionByName(activities_rejected, allowMissingColumns=True) \
        .unionByName(harvest_rejected, allowMissingColumns=True)
    write_parquet(rejected, f"{OUTPUT_BASE}/rejected_records/")

    # ---- TAHAP 2: FEATURE ENGINEERING ----
    print("[INFO] Building farm_activity_matrix ...")
    for c in ["farm_id", "crop_id"]:
        assert_column(activities_valid, c)
    farm_activity_matrix = build_farm_activity_matrix(activities_valid)
    write_parquet(farm_activity_matrix, f"{OUTPUT_BASE}/farm_activity_matrix/")

    print("[INFO] Building crop_stats ...")
    assert_column(harvest_valid, "crop_id")
    crop_stats = build_crop_stats(harvest_valid)
    write_parquet(crop_stats, f"{OUTPUT_BASE}/crop_stats/")

    print("[INFO] Building farm_features ...")
    assert_column(farms_valid, "farm_id")
    assert_column(activities_valid, "farm_id")
    farm_features = build_farm_features(farms_valid, activities_valid, harvest_valid)
    write_parquet(farm_features, f"{OUTPUT_BASE}/farm_features/")

    print(f"[INFO] Job {args['JOB_NAME']} completed successfully.")
    job.commit()


if __name__ == "__main__":
    main()