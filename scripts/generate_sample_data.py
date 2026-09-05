"""Generates a small synthetic finance dataset (CSV + Excel) purely to
demo/test the auto-detecting ingestion pipeline. Not part of the core app."""
import os

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
DATA_DIR = "data/default"  # the "default" tenant's data folder
os.makedirs(DATA_DIR, exist_ok=True)

vendors = pd.DataFrame({
    "vendor_id": range(1, 9),
    "vendor_name": [
        "Acme Corp", "Globex Ltd", "Initech", "Umbrella Inc",
        "Soylent Co", "Stark Industries", "Wayne Enterprises", "Wonka Foods",
    ],
})

chart_of_accounts = pd.DataFrame({
    "account_id": range(1, 6),
    "account_name": ["Payroll", "Marketing", "Software", "Travel", "Office Supplies"],
    "category": ["Opex", "Opex", "Opex", "Opex", "Opex"],
})

dates = pd.date_range("2026-06-01", "2026-08-31", freq="D")
n = 400
transactions = pd.DataFrame({
    "transaction_id": range(1, n + 1),
    "date": rng.choice(dates, n),
    "vendor_id": rng.integers(1, 9, n),
    "account_id": rng.integers(1, 6, n),
    "amount": np.round(rng.normal(500, 150, n).clip(10), 2),
    "category": rng.choice(["Opex", "Capex"], n, p=[0.85, 0.15]),
    "description": ["Invoice payment"] * n,
})
# inject one clear outlier for anomaly testing
transactions.loc[0, "amount"] = 9800.00
transactions.loc[0, "vendor_id"] = 1

reconciliation_status = pd.DataFrame({
    "transaction_id": transactions["transaction_id"],
    "status": rng.choice(["reconciled", "unreconciled"], n, p=[0.75, 0.25]),
    "reconciled_date": pd.NaT,
})

vendor_payouts = pd.DataFrame({
    "payout_id": range(1, 61),
    "vendor_id": rng.integers(1, 9, 60),
    "date": rng.choice(dates, 60),
    "amount": np.round(rng.normal(2000, 600, 60).clip(50), 2),
    "status": rng.choice(["paid", "pending"], 60, p=[0.8, 0.2]),
})

transactions.to_csv(f"{DATA_DIR}/transactions.csv", index=False)
vendor_payouts.to_csv(f"{DATA_DIR}/vendor_payouts.csv", index=False)
reconciliation_status.to_csv(f"{DATA_DIR}/reconciliation_status.csv", index=False)

with pd.ExcelWriter(f"{DATA_DIR}/reference_data.xlsx") as writer:
    vendors.to_excel(writer, sheet_name="vendors", index=False)
    chart_of_accounts.to_excel(writer, sheet_name="chart_of_accounts", index=False)

print("Sample dataset generated in data/")
