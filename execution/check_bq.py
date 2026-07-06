import os
import sys
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()
client = bigquery.Client()

query = """
SELECT 
  value.string_value, 
  value.int_value, 
  value.float_value, 
  value.double_value 
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`, UNNEST(event_params) 
WHERE _TABLE_SUFFIX = '20210131' 
AND key = 'session_engaged' 
LIMIT 5
"""

results = client.query(query).result()
for row in results:
    print(dict(row))
