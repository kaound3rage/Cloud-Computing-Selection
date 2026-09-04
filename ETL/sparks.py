"""
ETL/sparks.py — AWS Glue PySpark job untuk EduPintar

Membaca tabel dari Glue Data Catalog (database: edupintar_database):
  - learner_profiles
  - learner_activities
  - course_catalog

Menghasilkan (disimpan ke s3://[bucket]/processed-data/ dalam format Parquet):
  - course_enrollment_matrix  (matrix interaksi learner x course untuk model)
  - course_stats              (statistik agregat per course: jumlah enroll,
                                completion rate, avg rating, dst.)
  - learner_features          (fitur per learner: total course selesai,
                                kategori favorit, dst.)

Usage (AWS Glue):
  aws glue start-job-run --job-name [JOB_NAME] \
    --arguments '{"--S3_BUCKET":"my-bucket","--GLUE_DATABASE":"edupintar_database"}'
"""
import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.functions import col, count, countDistinct, lit, when
from pyspark.sql.window import Window

args = getResolvedOptions(sys.argv, ["JOB_NAME", "S3_BUCKET", "GLUE_DATABASE"])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

S3_BUCKET = args["S3_BUCKET"]
GLUE_DATABASE = args["GLUE_DATABASE"]
OUTPUT_BASE = f"s3://{S3_BUCKET}/processed-data"


def read_glue_table(table_name: str):
    """Read a table from the Glue Data Catalog with error handling."""
    try:
        df = glueContext.create_dynamic_frame.from_catalog(
            database=GLUE_DATABASE, table_name=table_name
        ).toDF()
        print(f"[INFO] Loaded table: {table_name} ({df.count()} rows)")
        return df
    except Exception as exc:  # noqa: BLE001 - Glue surfaces different exceptions
        print(f"[ERROR] Failed to load table {table_name}: {exc}")
        raise


def build_course_enrollment_matrix(activities_df, courses_df):
    """Create a sparse learner x course interaction matrix.

    Score per (learner, course):
      1.0 enroll | 2.0 complete | 0.5 like | -1.0 skip | 0.25 wishlist
    """
    weights = {
        "enroll": 1.0,
        "complete": 2.0,
        "like": 0.5,
        "skip": -1.0,
        "add_to_wishlist": 0.25,
    }

    matrix = activities_df.groupBy("learner_id", "course_id").agg(
        F.sum(when(col("activity_type") == "enroll", 1.0).otherwise(0.0)).alias("enroll_count"),
        F.sum(when(col("activity_type") == "complete", 1.0).otherwise(0.0)).alias("complete_count"),
        F.sum(when(col("activity_type") == "like", 1.0).otherwise(0.0)).alias("like_count"),
        F.sum(when(col("activity_type") == "skip", 1.0).otherwise(0.0)).alias("skip_count"),
        F.sum(when(col("activity_type") == "add_to_wishlist", 1.0).otherwise(0.0)).alias("wishlist_count"),
    ).withColumn(
        "interaction_score",
        col("enroll_count") * lit(weights["enroll"])
        + col("complete_count") * lit(weights["complete"])
        + col("like_count") * lit(weights["like"])
        + col("skip_count") * lit(weights["skip"])
        + col("wishlist_count") * lit(weights["add_to_wishlist"]),
    )

    # Include every course (even with no activity) joined from catalog
    matrix = courses_df.select("course_id", "category").join(
        matrix, on="course_id", how="left"
    )
    return matrix


def build_course_stats(activities_df, courses_df):
    """Aggregate per-course statistics."""
    enroll_df = activities_df.filter(col("activity_type") == "enroll")
    complete_df = activities_df.filter(col("activity_type") == "complete")

    enroll_stats = enroll_df.groupBy("course_id").agg(
        count("learner_id").alias("total_enrollments"),
        countDistinct("learner_id").alias("unique_learners"),
    )
    complete_stats = complete_df.groupBy("course_id").agg(
        count("learner_id").alias("total_completions"),
    )

    duration_stats = activities_df.groupBy("course_id").agg(
        F.sum("study_duration_minutes").alias("total_study_minutes"),
        F.avg("study_duration_minutes").alias("avg_study_minutes"),
    )

    stats = (
        courses_df.alias("c")
        .join(enroll_stats.alias("e"), col("c.course_id") == col("e.course_id"), "left")
        .join(complete_stats.alias("cc"), col("c.course_id") == col("cc.course_id"), "left")
        .join(duration_stats.alias("d"), col("c.course_id") == col("d.course_id"), "left")
        .select(
            col("c.course_id"),
            col("c.title"),
            col("c.category"),
            col("c.instructor"),
            col("c.avg_rating"),
            col("c.is_premium"),
            col("c.duration_hours"),
            when(col("e.total_enrollments").isNull(), 0).otherwise(col("e.total_enrollments")).alias("total_enrollments"),
            when(col("e.unique_learners").isNull(), 0).otherwise(col("e.unique_learners")).alias("unique_learners"),
            when(col("cc.total_completions").isNull(), 0).otherwise(col("cc.total_completions")).alias("total_completions"),
            when(col("d.total_study_minutes").isNull(), 0).otherwise(col("d.total_study_minutes")).alias("total_study_minutes"),
            when(col("d.avg_study_minutes").isNull(), 0).otherwise(col("d.avg_study_minutes")).alias("avg_study_minutes"),
        ).withColumn(
            "completion_rate",
            when(col("total_enrollments") > 0, col("total_completions") / col("total_enrollments")).otherwise(0.0),
        )
    )
    return stats


def build_learner_features(profiles_df, activities_df, courses_df):
    """Build per-learner feature set for modeling."""
    completed = activities_df.filter(col("activity_type") == "complete")

    # Category popularity per learner from completed courses
    completion_with_cat = (
        completed.alias("a")
        .join(courses_df.select("course_id", "category").alias("c"), col("a.course_id") == col("c.course_id"), "left")
        .filter(col("c.category").isNotNull())
        .groupBy("a.learner_id", "c.category")
        .count()
        .withColumnRenamed("count", "category_count")
    )

    # Pick the most frequent category per learner as favorite
    window = Window.partitionBy("learner_id").orderBy(col("category_count").desc())
    favorite_cat = (
        completion_with_cat.withColumn("rank", F.row_number().over(window))
        .filter(col("rank") == 1)
        .select(
            col("learner_id").alias("f_learner_id"),
            col("category").alias("favorite_category"),
        )
    )

    activity_counts = activities_df.groupBy("learner_id").agg(
        count("activity_id").alias("total_activities"),
        F.sum(col("study_duration_minutes")).alias("total_study_minutes"),
    )

    features = (
        profiles_df.alias("p")
        .join(activity_counts.alias("ac"), col("p.learner_id") == col("ac.learner_id"), "left")
        .join(favorite_cat.alias("fc"), col("p.learner_id") == col("fc.f_learner_id"), "left")
        .select(
            col("p.learner_id"),
            col("p.membership_plan"),
            col("p.learner_segment"),
            col("p.join_date"),
            col("p.total_courses_completed"),
            when(col("ac.total_activities").isNull(), 0).otherwise(col("ac.total_activities")).alias("total_activities"),
            when(col("ac.total_study_minutes").isNull(), 0).otherwise(col("ac.total_study_minutes")).alias("total_study_minutes"),
            col("fc.favorite_category").alias("favorite_category"),
        )
    )
    return features


def write_parquet(df, output_path: str) -> None:
    """Write a DataFrame to S3 in Parquet format (overwrite mode)."""
    print(f"[INFO] Writing {df.count()} rows to {output_path}")
    df.write.mode("overwrite").parquet(output_path)
    print(f"[INFO] Written: {output_path}")


def main() -> None:
    print(f"[INFO] Starting job {args['JOB_NAME']}")
    print(f"[INFO] S3 bucket: {S3_BUCKET}, Glue database: {GLUE_DATABASE}")

    learner_profiles = read_glue_table("learner_profiles")
    learner_activities = read_glue_table("learner_activities")
    course_catalog = read_glue_table("course_catalog")

    print("[INFO] Building course_enrollment_matrix ...")
    course_enrollment_matrix = build_course_enrollment_matrix(learner_activities, course_catalog)
    write_parquet(course_enrollment_matrix, f"{OUTPUT_BASE}/course_enrollment_matrix/")

    print("[INFO] Building course_stats ...")
    course_stats = build_course_stats(learner_activities, course_catalog)
    write_parquet(course_stats, f"{OUTPUT_BASE}/course_stats/")

    print("[INFO] Building learner_features ...")
    learner_features = build_learner_features(learner_profiles, learner_activities, course_catalog)
    write_parquet(learner_features, f"{OUTPUT_BASE}/learner_features/")

    print(f"[INFO] Job {args['JOB_NAME']} completed successfully.")
    job.commit()


if __name__ == "__main__":
    main()
