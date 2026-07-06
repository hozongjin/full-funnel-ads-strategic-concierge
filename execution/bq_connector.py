# /// script
# dependencies = [
#   "google-cloud-bigquery",
#   "python-dotenv",
# ]
# ///

import os
from google.cloud import bigquery

# Load local environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_bq_client():
    """Initializes and returns a BigQuery client using local credentials or default ADC."""
    # In local development, the user runs `gcloud auth application-default login`
    # In Kaggle/GCP environments, this is authenticated automatically.
    return bigquery.Client()

def execute_query(query_str: str):
    """Executes a SQL query on BigQuery and returns the rows as dictionaries."""
    client = get_bq_client()
    query_job = client.query(query_str)
    results = query_job.result()
    return [dict(row) for row in results]

def validate_query(query_str: str) -> tuple[bool, str]:
    """Dry-runs a query to validate its syntax and schema against BigQuery for free.
    Returns (True, "") if valid, or (False, error_message) if invalid.
    """
    client = get_bq_client()
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    try:
        client.query(query_str, job_config=job_config)
        return True, ""
    except Exception as e:
        return False, str(e)

def dry_run_schema(query_str: str) -> tuple[list[str], str]:
    """Dry-runs a query and returns the output column names from BQ API metadata.
    Returns (list_of_column_names, "") on success, or ([], error_message) on failure.
    This is used by the EvaluationAgent for deterministic schema compliance checks.
    """
    client = get_bq_client()
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    try:
        job = client.query(query_str, job_config=job_config)
        columns = [field.name for field in job.schema]
        return columns, ""
    except Exception as e:
        return [], str(e)

if __name__ == "__main__":
    # Quick connectivity test
    test_query = """
        SELECT event_name, COUNT(1) as event_count 
        FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_20210131`
        GROUP BY event_name 
        ORDER BY event_count DESC 
        LIMIT 5
    """
    try:
        print("Testing BigQuery GA4 public dataset connection...")
        rows = execute_query(test_query)
        print("Successfully connected! Top events on 2021-01-31:")
        for r in rows:
            print(f"- {r['event_name']}: {r['event_count']}")
    except Exception as e:
        print(f"Connection test failed: {e}")
        print("Please ensure you have run 'gcloud auth application-default login' locally.")
