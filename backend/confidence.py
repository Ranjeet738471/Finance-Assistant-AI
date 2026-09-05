"""Bonus features: confidence signalling and simple anomaly callouts. Both
operate only on the already-computed result set, never on model output."""
import pandas as pd


def is_effectively_empty(df: pd.DataFrame) -> bool:
    """True if the query returned no rows, or returned rows whose only
    numeric values are all NULL (e.g. SUM() over a filter that matched
    nothing still returns one row with NULL)."""
    if df.empty:
        return True
    numeric_cols = df.select_dtypes(include="number").columns
    if len(numeric_cols) > 0 and df[numeric_cols].isna().all().all():
        return True
    return False


def score_confidence(df: pd.DataFrame) -> dict:
    """Heuristic confidence score based on completeness of the result set."""
    if df.empty:
        return {"level": "low", "reason": "No rows returned."}

    numeric_cols = df.select_dtypes(include="number").columns
    null_fraction = 0.0
    if len(numeric_cols) > 0:
        null_fraction = df[numeric_cols].isna().mean().mean()

    if null_fraction > 0.3:
        return {"level": "low", "reason": "Result contains many missing values."}
    if len(df) == 1 or null_fraction == 0.0:
        return {"level": "high", "reason": "Result is a single well-formed record or fully populated table."}
    return {"level": "medium", "reason": "Result set is partially populated."}


def detect_anomalies(df: pd.DataFrame, group_col: str | None = None, value_col: str | None = None) -> list[dict]:
    """Flags rows whose numeric value is unusually large/small compared to
    the rest of the result set, using a robust modified z-score (median +
    MAD) rather than mean/std - a single extreme outlier otherwise inflates
    the standard deviation and can hide itself. Auto-picks a grouping/value
    column pair if not provided."""
    if df.empty or len(df) < 3:
        return []

    if value_col is None:
        numeric_cols = list(df.select_dtypes(include="number").columns)
        if not numeric_cols:
            return []
        value_col = numeric_cols[0]

    if group_col is None:
        non_numeric = [c for c in df.columns if c != value_col]
        group_col = non_numeric[0] if non_numeric else None

    values = df[value_col].dropna()
    if len(values) < 3:
        return []

    median = values.median()
    mad = (values - median).abs().median()
    if mad == 0:
        return []

    anomalies = []
    for _, row in df.iterrows():
        val = row[value_col]
        if pd.isna(val):
            continue
        modified_z = 0.6745 * (val - median) / mad
        if abs(modified_z) >= 3.5:
            label = row[group_col] if group_col else "record"
            anomalies.append({
                "label": str(label),
                "value": float(val),
                "z_score": round(float(modified_z), 2),
                "direction": "unusually high" if modified_z > 0 else "unusually low",
            })
    return anomalies
