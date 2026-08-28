-- Field-day Product — Databricks SQL
-- After `databricks bundle deploy`, Product is at
-- /Workspace/Users/<you>/geopipeline/data/product/field_days
-- This workspace does not generate rasters.

-- CREATE OR REPLACE TABLE field_days
-- AS SELECT * FROM parquet.`/Workspace/Users/<you>/geopipeline/data/product/field_days`;

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
