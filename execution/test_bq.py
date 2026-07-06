# /// script
# dependencies = [
#   "google-cloud-bigquery",
#   "python-dotenv",
# ]
# ///

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from execution.bq_connector import execute_query

sql = """
WITH first_visits AS (
  SELECT 
    user_pseudo_id,
    PARSE_DATE('%Y%m%d', MIN(_TABLE_SUFFIX)) as first_visit_date
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20201201' AND '20210131'
    AND event_name IN ('first_visit', 'first_open')
  GROUP BY user_pseudo_id
),
all_visits AS (
  SELECT DISTINCT
    user_pseudo_id,
    PARSE_DATE('%Y%m%d', _TABLE_SUFFIX) as visit_date
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20201201' AND '20210131'
)
SELECT
  CAST(DATE_TRUNC(fv.first_visit_date, ISOWEEK) AS STRING) as cohort,
  COUNT(DISTINCT fv.user_pseudo_id) as users,
  COUNT(DISTINCT CASE WHEN DATE_DIFF(av.visit_date, fv.first_visit_date, DAY) = 1 THEN av.user_pseudo_id END) as day_1,
  COUNT(DISTINCT CASE WHEN DATE_DIFF(av.visit_date, fv.first_visit_date, DAY) BETWEEN 2 AND 7 THEN av.user_pseudo_id END) as day_7,
  COUNT(DISTINCT CASE WHEN DATE_DIFF(av.visit_date, fv.first_visit_date, DAY) BETWEEN 8 AND 30 THEN av.user_pseudo_id END) as day_30
FROM first_visits fv
LEFT JOIN all_visits av
  ON fv.user_pseudo_id = av.user_pseudo_id
GROUP BY cohort
ORDER BY cohort
"""

try:
    results = execute_query(sql)
    print("Test Results:", results)
except Exception as e:
    print("Error:", e)
