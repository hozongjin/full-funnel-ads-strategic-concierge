def inject_chart_data(chart_config: dict, query_results: list[dict]) -> dict:
    """
    Deterministically injects 'labels' and 'datasets' into a Chart.js config based on the raw data.
    This prevents the LLM from truncating or hallucinating data points when processing large JSON arrays.
    """
    if not query_results:
        return chart_config

    first_row = query_results[0]
    keys = list(first_row.keys())
    
    # Identify column types heuristically
    date_cols = [k for k in keys if any(d in k.lower() for d in ["date", "week", "month", "day", "time"])]
    metric_cols = [k for k in keys if type(first_row[k]) in (int, float)]
    dimension_cols = [k for k in keys if k not in date_cols and k not in metric_cols]

    date_col = date_cols[0] if date_cols else None
    
    # Fallback default metric
    if metric_cols:
        default_metric = metric_cols[0]
    else:
        default_metric = keys[-1]

    chart_type = chart_config.get("type", chart_config.get("chart_type", "bar")).lower()

    # Get existing dataset styles from the LLM if they exist
    existing_data = chart_config.get("data", {})
    existing_datasets = existing_data.get("datasets", [])
    
    data_payload = {"labels": [], "datasets": []}
    
    # Check if the LLM provided explicit dataset-level target metrics
    has_dataset_level_metrics = any(ds.get("target_metric") for ds in existing_datasets)

    if has_dataset_level_metrics:
        # Trust the LLM's multi-dataset configuration (e.g. double axis, multi metric)
        x_col = date_col if date_col else (dimension_cols[0] if dimension_cols else keys[0])
        
        # Get unique labels for the X-axis
        unique_labels = []
        for row in query_results:
            val = str(row.get(x_col, "Unknown"))
            if val not in unique_labels:
                unique_labels.append(val)
                
        data_payload["labels"] = unique_labels
        
        # Populate each dataset requested by the LLM
        for ds in existing_datasets:
            ds_metric = ds.get("target_metric", chart_config.get("target_metric", default_metric))
            if ds_metric not in keys:
                # If hallucinated metric, fallback to the first numeric column
                ds_metric = default_metric
                
            data_pts = []
            for lbl in unique_labels:
                # Find the row matching the label
                row_match = next((r for r in query_results if str(r.get(x_col, "Unknown")) == lbl), None)
                data_pts.append(row_match.get(ds_metric, 0) if row_match else 0)
                
            new_ds = ds.copy()
            new_ds["data"] = data_pts
            data_payload["datasets"].append(new_ds)

    else:
        # Fallback to single metric parsing logic
        metric_col = chart_config.get("target_metric", default_metric)
        if metric_col not in keys:
            metric_col = default_metric

        def create_or_update_dataset(label_name, data_array, index=0):
            if index < len(existing_datasets):
                ds = existing_datasets[index].copy()
                ds["label"] = label_name
                ds["data"] = data_array
                return ds
            else:
                return {"label": label_name, "data": data_array, "borderWidth": 2}

        if chart_type in ["line", "bar"] and date_col and dimension_cols:
            dim_col = dimension_cols[0]
            unique_dates = sorted(list(set(str(row[date_col]) for row in query_results if row[date_col] is not None)))
            data_payload["labels"] = unique_dates
            
            series_data = {}
            for row in query_results:
                dim_val = str(row.get(dim_col, "Unknown"))
                date_val = str(row.get(date_col))
                metric_val = row.get(metric_col, 0)
                
                if dim_val not in series_data:
                    series_data[dim_val] = {d: 0 for d in unique_dates}
                series_data[dim_val][date_val] = metric_val
                
            ds_index = 0
            for dim_val, dates_dict in series_data.items():
                dataset = create_or_update_dataset(dim_val, [dates_dict[d] for d in unique_dates], ds_index)
                data_payload["datasets"].append(dataset)
                ds_index += 1

        elif chart_type in ["pie", "doughnut"] or (chart_type in ["bar", "line"] and not date_col and dimension_cols):
            dim_col = dimension_cols[0]
            labels = []
            data_pts = []
            for row in query_results:
                labels.append(str(row.get(dim_col, "Unknown")))
                data_pts.append(row.get(metric_col, 0))
                
            data_payload["labels"] = labels
            dataset = create_or_update_dataset(metric_col, data_pts, 0)
            data_payload["datasets"].append(dataset)
            
        elif chart_type in ["line", "bar"] and date_col and not dimension_cols:
            labels = []
            data_pts = []
            for row in query_results:
                labels.append(str(row.get(date_col)))
                data_pts.append(row.get(metric_col, 0))
                
            data_payload["labels"] = labels
            dataset = create_or_update_dataset(metric_col, data_pts, 0)
            data_payload["datasets"].append(dataset)
            
        else:
            labels = []
            data_pts = []
            for row in query_results:
                labels.append(str(row.get(keys[0])))
                data_pts.append(row.get(keys[-1]))
            data_payload["labels"] = labels
            dataset = create_or_update_dataset(keys[-1], data_pts, 0)
            data_payload["datasets"].append(dataset)

    # Preserve any other root 'data' properties the LLM might have set
    existing_data["labels"] = data_payload["labels"]
    existing_data["datasets"] = data_payload["datasets"]
    chart_config["data"] = existing_data
    
    return chart_config
