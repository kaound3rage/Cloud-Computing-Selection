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

TODO: lengkapi setiap job.commit() step dan transformasi datanya.
"""
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job

args = getResolvedOptions(sys.argv, ["JOB_NAME", "S3_BUCKET", "GLUE_DATABASE"])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

S3_BUCKET = args["S3_BUCKET"]
GLUE_DATABASE = args["GLUE_DATABASE"]

# ---- 1. Baca tabel dari Glue Data Catalog ----
learner_profiles = glueContext.create_dynamic_frame.from_catalog(
    database=GLUE_DATABASE, table_name="learner_profiles"
).toDF()

learner_activities = glueContext.create_dynamic_frame.from_catalog(
    database=GLUE_DATABASE, table_name="learner_activities"
).toDF()

course_catalog = glueContext.create_dynamic_frame.from_catalog(
    database=GLUE_DATABASE, table_name="course_catalog"
).toDF()

# ---- 2. TODO: Buat course_enrollment_matrix ----
# course_enrollment_matrix = ...

# ---- 3. TODO: Buat course_stats ----
# course_stats = ...

# ---- 4. TODO: Buat learner_features ----
# learner_features = ...

# ---- 5. TODO: Tulis output ke S3 dalam format Parquet ----
# course_enrollment_matrix.write.mode("overwrite").parquet(
#     f"s3://{S3_BUCKET}/processed-data/course_enrollment_matrix/"
# )
# course_stats.write.mode("overwrite").parquet(
#     f"s3://{S3_BUCKET}/processed-data/course_stats/"
# )
# learner_features.write.mode("overwrite").parquet(
#     f"s3://{S3_BUCKET}/processed-data/learner_features/"
# )

job.commit()
