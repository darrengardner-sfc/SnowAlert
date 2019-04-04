from os import environ
import uuid

from runners.helpers.dbconfig import DATABASE

ENV = environ.get('SA_ENV', 'unset')

# generated once per runtime
RUN_ID = uuid.uuid4().hex

# schema names
DATA_SCHEMA_NAME = environ.get('SA_DATA_SCHEMA_NAME', "data")
RULES_SCHEMA_NAME = environ.get('SA_RULES_SCHEMA_NAME', "rules")
RESULTS_SCHEMA_NAME = environ.get('SA_RESULTS_SCHEMA_NAME', "results")

# table names
RESULTS_ALERTS_TABLE_NAME = environ.get('SA_RESULTS_ALERTS_TABLE_NAME', "alerts")
RESULTS_VIOLATIONS_TABLE_NAME = environ.get('SA_RESULTS_VIOLATIONS_TABLE_NAME', "violations")
QUERY_METADATA_TABLE_NAME = environ.get('SA_QUERY_METADATA_TABLE_NAME', "query_metadata")
RUN_METADATA_TABLE_NAME = environ.get('SA_RUN_METADATA_TABLE_NAME', "run_metadata")

# schemas
DATA_SCHEMA = environ.get('SA_DATA_SCHEMA', f"{DATABASE}.{DATA_SCHEMA_NAME}")
RULES_SCHEMA = environ.get('SA_RULES_SCHEMA', f"{DATABASE}.{RULES_SCHEMA_NAME}")
RESULTS_SCHEMA = environ.get('SA_RESULTS_SCHEMA', f"{DATABASE}.{RESULTS_SCHEMA_NAME}")

# tables
ALERTS_TABLE = environ.get('SA_ALERTS_TABLE', f"{RESULTS_SCHEMA}.{RESULTS_ALERTS_TABLE_NAME}")
VIOLATIONS_TABLE = environ.get('SA_VIOLATIONS_TABLE', f"{RESULTS_SCHEMA}.{RESULTS_VIOLATIONS_TABLE_NAME}")
QUERY_METADATA_TABLE = environ.get('SA_QUERY_METADATA_TABLE', f"{RESULTS_SCHEMA}.{QUERY_METADATA_TABLE_NAME}")
RUN_METADATA_TABLE = environ.get('SA_METADATA_RUN_TABLE', f"{RESULTS_SCHEMA}.{RUN_METADATA_TABLE_NAME}")

# misc
ALERT_QUERY_POSTFIX = "ALERT_QUERY"
ALERT_SQUELCH_POSTFIX = "ALERT_SUPPRESSION"
VIOLATION_QUERY_POSTFIX = "VIOLATION_QUERY"
VIOLATION_SQUELCH_POSTFIX = "VIOLATION_SUPPRESSION"

# enabling sends metrics to cloudwatch
CLOUDWATCH_METRICS = environ.get('CLOUDWATCH_METRICS', False)

CONFIG_VARS = [
    ('ALERTS_TABLE', ALERTS_TABLE),
    ('VIOLATIONS_TABLE', VIOLATIONS_TABLE),
    ('QUERY_METADATA_TABLE', QUERY_METADATA_TABLE),
    ('RUN_METADATA_TABLE', RUN_METADATA_TABLE),

    ('DATA_SCHEMA', DATA_SCHEMA),
    ('RULES_SCHEMA', RULES_SCHEMA),
    ('RESULTS_SCHEMA', RESULTS_SCHEMA),
]
