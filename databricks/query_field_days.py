# Databricks notebook source
# MAGIC %md
# MAGIC # Field-day Product
# MAGIC
# MAGIC Upload `data/product/field_days` after `make run` (Hive-style
# MAGIC `date=YYYY-MM-DD/` Parquet) to DBFS or a Unity Catalog volume.
# MAGIC This notebook only queries that Product. It does not ingest Scenes
# MAGIC or compute NDVI.

# COMMAND ----------

# Edit to the uploaded Product directory (the folder that contains date=* partitions).
product_path = "/FileStore/field_days"

field_days = spark.read.parquet(product_path)
field_days.createOrReplaceTempView("field_days")
print(f"rows={field_days.count()}")

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT date, status, count(*) AS field_days, avg(ndvi) AS mean_ndvi
# MAGIC FROM field_days
# MAGIC GROUP BY 1, 2
# MAGIC ORDER BY 1, 2

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT field_id, crop_type, count(*) AS observed_days, avg(ndvi) AS mean_ndvi
# MAGIC FROM field_days
# MAGIC WHERE status = 'observed'
# MAGIC GROUP BY 1, 2
# MAGIC ORDER BY mean_ndvi DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT status, count(*) AS n
# MAGIC FROM field_days
# MAGIC GROUP BY 1
# MAGIC ORDER BY 1
