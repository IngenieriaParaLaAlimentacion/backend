from sqlalchemy import DateTime

from app.config.log_masking.core import is_sensitive_key, normalize_key
from app.config.log_masking.rules import NAME_KEYS
from app.models import Base
from tests.unit.core.helpers import NON_SENSITIVE_COLUMNS


def test_every_schema_column_is_masked_or_allowed():
    unclassified = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if not (
            column.primary_key
            or column.foreign_keys
            or isinstance(column.type, DateTime)
            or is_sensitive_key(normalize_key(column.name))
            or normalize_key(column.name) in NAME_KEYS
            or normalize_key(column.name) in NON_SENSITIVE_COLUMNS
        )
    }
    assert not unclassified
