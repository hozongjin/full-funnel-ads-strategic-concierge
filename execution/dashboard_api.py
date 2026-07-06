import os
import sys
import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from google.cloud import bigquery
from .bq_connector import execute_query

def get_dashboard_data(period_days: int, countries: list = None) -> dict:
    """
    Fetches the aggregate data for the Overview dashboard.
    Anchored to Jan 31, 2021 since the public dataset ends there.
    """
    end_date = datetime.date(2021, 1, 31)
    start_date = end_date - datetime.timedelta(days=period_days - 1)
    
    start_str = start_date.strftime('%Y%m%d')
    end_str = end_date.strftime('%Y%m%d')

    geo_filter = ""
    if countries:
        safe_countries = [c.replace("'", "''") for c in countries]
        formatted_countries = ", ".join(f"'{c}'" for c in safe_countries)
        geo_filter = f"AND geo.country IN ({formatted_countries})"

    # Query 1: Time Series (Sessions, Bounce Rate, ECR, Purchases, Revenue)
    sql_timeseries = f"""
    WITH session_stats AS (
      SELECT 
        event_date,
        user_pseudo_id,
        (SELECT COALESCE(CAST(value.int_value AS STRING), value.string_value) FROM UNNEST(event_params) WHERE key = 'ga_session_id') as session_id,
        MAX(CASE WHEN event_name IN ('first_visit', 'first_open') THEN 1 ELSE 0 END) as is_new_user,
        SUM((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'engagement_time_msec')) as total_eng_time,
        MAX(CASE WHEN event_name = 'purchase' THEN 1 ELSE 0 END) as has_purchase,
        SUM(ecommerce.purchase_revenue_in_usd) as revenue
      FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
      WHERE _TABLE_SUFFIX BETWEEN '{start_str}' AND '{end_str}'
      {geo_filter}
      GROUP BY event_date, user_pseudo_id, session_id
    )
    SELECT 
        event_date,
        COUNT(DISTINCT user_pseudo_id) as users,
        COUNT(DISTINCT CASE WHEN is_new_user = 1 THEN user_pseudo_id ELSE NULL END) as new_users,
        COUNT(DISTINCT CONCAT(user_pseudo_id, session_id)) as sessions,
        COUNT(DISTINCT CASE WHEN total_eng_time > 10000 THEN CONCAT(user_pseudo_id, session_id) ELSE NULL END) as engaged_sessions,
        SUM(total_eng_time) / 1000.0 as total_engagement_time_sec,
        SUM(has_purchase) as purchases,
        SUM(revenue) as revenue
    FROM session_stats
    GROUP BY event_date
    ORDER BY event_date
    """
    
    # Query 2: Channels
    sql_channels = f"""
    SELECT 
        traffic_source.medium as channel, 
        COUNT(DISTINCT CASE WHEN event_name IN ('first_visit', 'first_open') THEN user_pseudo_id ELSE NULL END) as new_users
    FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '{start_str}' AND '{end_str}'
    {geo_filter}
    GROUP BY channel
    ORDER BY new_users DESC
    LIMIT 5
    """
    
    # Query 3: Mid-Funnel Events
    sql_events = f"""
    SELECT 
        event_name, 
        COUNT(*) as event_count
    FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '{start_str}' AND '{end_str}'
    AND event_name IN ('view_item', 'view_item_list', 'add_to_cart', 'add_to_wishlist', 'begin_checkout')
    {geo_filter}
    GROUP BY event_name
    ORDER BY event_count DESC
    """

    # Query 4: Funnel (Session Start -> View Item -> Add to Cart -> Purchase)
    sql_funnel = f"""
    SELECT 
        event_name, 
        COUNT(DISTINCT user_pseudo_id) as event_count
    FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '{start_str}' AND '{end_str}'
    AND event_name IN ('session_start', 'view_item', 'add_to_cart', 'purchase')
    {geo_filter}
    GROUP BY event_name
    """
    
    # Query 5: Cohort (Weekly Acquisition -> Day 1, 7, 30 Retention)
    sql_cohort = f"""
    WITH first_visits AS (
      SELECT 
        user_pseudo_id,
        PARSE_DATE('%Y%m%d', MIN(_TABLE_SUFFIX)) as first_visit_date
      FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
      WHERE _TABLE_SUFFIX BETWEEN '{start_str}' AND '{end_str}'
        AND event_name IN ('first_visit', 'first_open')
        {geo_filter}
      GROUP BY user_pseudo_id
    ),
    all_visits AS (
      SELECT DISTINCT
        user_pseudo_id,
        PARSE_DATE('%Y%m%d', _TABLE_SUFFIX) as visit_date
      FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
      WHERE _TABLE_SUFFIX BETWEEN '{start_str}' AND '{end_str}'
        {geo_filter}
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
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        f_timeseries = executor.submit(execute_query, sql_timeseries)
        f_channels = executor.submit(execute_query, sql_channels)
        f_events = executor.submit(execute_query, sql_events)
        f_funnel = executor.submit(execute_query, sql_funnel)
        f_cohort = executor.submit(execute_query, sql_cohort)
        
        ts_rows = f_timeseries.result()
        ch_rows = f_channels.result()
        evt_rows = f_events.result()
        funnel_rows = f_funnel.result()
        cohort_rows = f_cohort.result()
    
    # Format data for Chart.js
    
    # Time Series
    ts_labels = []
    ts_users = []
    ts_new_users = []
    ts_sessions = []
    ts_eng_rates = []
    ts_avg_eng_times = []
    ts_ecr = []
    total_purchases = 0
    total_revenue = 0.0
    
    if ts_rows:
        for row in ts_rows:
            d = str(row['event_date'])
            formatted_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            ts_labels.append(formatted_date)
            
            ts_users.append(int(row['users']))
            ts_new_users.append(int(row['new_users']))
            
            s = int(row['sessions'])
            ts_sessions.append(s)
            
            eng = int(row['engaged_sessions'])
            eng_rate = (eng / s) * 100 if s > 0 else 0
            ts_eng_rates.append(round(eng_rate, 2))
            
            total_time = float(row['total_engagement_time_sec'] or 0)
            avg_time = total_time / s if s > 0 else 0
            ts_avg_eng_times.append(round(avg_time, 2))
            
            p = int(row['purchases'])
            total_purchases += p
            ecr_val = (p / s) * 100 if s > 0 else 0
            ts_ecr.append(round(ecr_val, 2))
            
            if row['revenue']:
                total_revenue += float(row['revenue'])
                
    # Channels
    ch_labels = []
    ch_users = []
    if ch_rows:
        for row in ch_rows:
            ch = row['channel']
            if not ch or str(ch) == '<NA>': ch = '(none)'
            ch_labels.append(str(ch))
            ch_users.append(int(row['new_users']))
            
    # Events
    evt_labels = []
    evt_data = []
    
    event_counts = {
        'view_item': 0,
        'view_item_list': 0,
        'add_to_cart': 0,
        'add_to_wishlist': 0,
        'begin_checkout': 0
    }
    
    if evt_rows:
        for row in evt_rows:
            evt = row['event_name']
            if evt in event_counts:
                event_counts[evt] = int(row['event_count'])
                
    for evt, count in event_counts.items():
        evt_labels.append(str(evt))
        evt_data.append(count)

    # Funnel
    funnel_map = {row['event_name']: int(row['event_count']) for row in funnel_rows} if funnel_rows else {}
    funnel_labels = ['session_start', 'view_item', 'add_to_cart', 'purchase']
    funnel_data = [funnel_map.get(label, 0) for label in funnel_labels]

    # Cohort
    cohort_data = []
    if cohort_rows:
        for row in cohort_rows:
            cohort_data.append({
                'cohort': row['cohort'],
                'users': int(row['users']),
                'day_1': int(row['day_1']),
                'day_7': int(row['day_7']),
                'day_30': int(row['day_30'])
            })

    return {
        "timeseries": {
            "labels": ts_labels,
            "users": ts_users,
            "new_users": ts_new_users,
            "sessions": ts_sessions,
            "engagement_rates": ts_eng_rates,
            "avg_engagement_times": ts_avg_eng_times,
            "ecr": ts_ecr
        },
        "channels": {
            "labels": ch_labels,
            "new_users": ch_users
        },
        "events": {
            "labels": evt_labels,
            "counts": evt_data
        },
        "funnel": {
            "labels": funnel_labels,
            "counts": funnel_data
        },
        "cohorts": cohort_data,
        "kpis": {
            "purchases": total_purchases,
            "revenue": f"${total_revenue:,.2f}"
        }
    }
