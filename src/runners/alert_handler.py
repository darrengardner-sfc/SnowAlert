#!/usr/bin/env python

import json
import datetime
import uuid

from .config import CLOUDWATCH_METRICS
from .helpers import db, log
from .plugins import create_jira


def log_alerts(ctx, alerts):
    """We don't normally create alerts in this function, but we want to be able to push an alert to the table if
    something goes wrong.
    """
    if len(alerts):
        print("Recording alerts.")
        try:
            ctx.cursor().execute(
                f'''
                INSERT INTO results.alerts (alert_time, alert)
                SELECT PARSE_JSON(column1):ALERT_TIME,
                       PARSE_JSON(column1)
                FROM VALUES {", ".join(["(%s)"] * len(alerts))};
                ''',
                alerts
            )
        except Exception as e:
            log.error("Failed to log alert", e)

    else:
        print("No alerts to log.")


def log_failure(ctx, alert, e):
    alerts = [json.dumps({
        'ALERT_ID': uuid.uuid4().hex,
        'QUERY_ID': 'db9fa0d114d54b5ca1a195e34fb8752b',
        'QUERY_NAME': 'Alert Handler Failure',
        'ENVIRONMENT': 'SnowAlert',
        'SOURCES': ['Alerts Table'],
        'ACTOR': 'Alert Handler',
        'OBJECT': alert['ALERT_ID'],
        'ACTION': 'The Alert Handler failed to create a ticket',
        'TITLE': 'Alert Handler Failure',
        'EVENT_TIME': str(datetime.datetime.utcnow()),
        'ALERT_TIME': str(datetime.datetime.utcnow()),
        'DESCRIPTION': f"The alert with ID '{alert['ALERT_ID']}' failed to create with error: {e}",
        'DETECTOR': 'Alert Handler',
        'EVENT_DATA': str(alert),
        'SEVERITY': 'High'
    })]
    try:
        log_alerts(ctx, alerts)
        ctx.cursor().execute(f"DELETE FROM results.alerts where ALERT:ALERT_ID = '{alert['ALERT_ID']}';")
    except Exception as e:
        log.error("Failed to log alert creation failure", e)


GET_ALERTS_QUERY = f"""
SELECT *
FROM results.alerts
WHERE ticket IS NULL
  AND suppressed=FALSE
ORDER BY event_time ASC
LIMIT 100
"""


def get_new_alerts(ctx):
    results = db.fetch(GET_ALERTS_QUERY)
    return results


def main():
    ctx = db.connect()
    alerts = list(get_new_alerts(ctx))
    log.info(f'Found {len(alerts)} new alerts to handle.')

    for alert in alerts:
        alert_body = alert['ALERT']
        handlers = alert_body.get('HANDLERS', ['jira'])
        for handler in handlers:
            if handler == 'jira':
                r = create_jira.handle_alert(handler, alert)
                if r is not None:
                    log_failure(ctx, alert_body, r)

    try:
        if CLOUDWATCH_METRICS:
            log.metric('Run', 'SnowAlert', [{'Name': 'Component', 'Value': 'Alert Handler'}], 1)
    except Exception as e:
        log.error("Cloudwatch metric logging failed", e)


if __name__ == "__main__":
    import os
    if os.environ.get('JIRA_USER'):
        main()
