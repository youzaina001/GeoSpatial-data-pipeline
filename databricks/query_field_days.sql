-- Field-day Product — Databricks SQL
-- Upload data/product/field_days after `make run` and point the path
-- below at it. This workspace does not generate rasters.

-- CREATE OR REPLACE TABLE field_days
-- AS SELECT * FROM parquet.`/FileStore/field_days`;

SELECT
    date,
    status,
    count(*) AS field_days,
    avg(ndvi) AS mean_ndvi
FROM field_days
GROUP BY 1, 2
ORDER BY 1, 2;

SELECT
    field_id,
    crop_type,
    count(*) AS observed_days,
    avg(ndvi) AS mean_ndvi
FROM field_days
WHERE status = 'observed'
GROUP BY 1, 2
ORDER BY mean_ndvi DESC;

SELECT status, count(*) AS n
FROM field_days
GROUP BY 1
ORDER BY 1;
