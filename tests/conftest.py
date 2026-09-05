"""Shared pytest fixtures: builds an isolated, ephemeral tenant database so
the test suite never depends on manually-generated sample data being
present."""
import gc
import shutil

import pandas as pd
import pytest

from backend import config, db_builder
from backend.schema_introspect import invalidate_engine

TEST_TENANT = "pytest_tenant"


@pytest.fixture(scope="session", autouse=True)
def test_tenant_db():
    data_dir = config.tenant_data_dir(TEST_TENANT)
    pd.DataFrame({
        "transaction_id": [1, 2, 3],
        "vendor_id": [1, 2, 1],
        "amount": [100.0, 200.0, 300.0],
    }).to_csv(data_dir / "transactions.csv", index=False)
    pd.DataFrame({
        "vendor_id": [1, 2, 3],
        "amount": [500.0, 600.0, 9000.0],
    }).to_csv(data_dir / "vendor_payouts.csv", index=False)

    db_builder.build_database(TEST_TENANT, force=True)
    yield TEST_TENANT

    invalidate_engine(TEST_TENANT)
    gc.collect()  # Windows can hold the sqlite file handle until GC runs
    shutil.rmtree(data_dir, ignore_errors=True)
    try:
        config.tenant_db_path(TEST_TENANT).unlink(missing_ok=True)
        config.tenant_manifest_path(TEST_TENANT).unlink(missing_ok=True)
    except PermissionError:
        pass  # best-effort cleanup only; a lingering handle isn't a test failure
