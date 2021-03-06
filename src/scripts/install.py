#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""Script which installs the Snowflake database, warehouse, and everything
else you need to get started with SnowAlert.

Usage:

  ./install.py [--admin-role ADMIN_ROLE]

Note that if you run with ADMIN_ROLE other than ACCOUNTADMIN, the installer
assumes that your account admin has already created a user, role, database,
and warehouse for SnowAlert to use. The role will be the SnowAlert admin role,
and will be used by those managing the rules, separate from the SNOWALERT role
which will be used by the runners.
"""

from base64 import b64encode
from configparser import ConfigParser
import fire
from getpass import getpass
import os
import re
from typing import List, Optional, Tuple
from urllib.parse import urlsplit
from uuid import uuid4

import boto3

from runners.config import ALERT_QUERY_POSTFIX, ALERT_SQUELCH_POSTFIX
from runners.config import VIOLATION_QUERY_POSTFIX
from runners.config import DATABASE, DATA_SCHEMA, RULES_SCHEMA, RESULTS_SCHEMA

from runners.helpers import log
from runners.helpers.dbconfig import USER, ROLE, WAREHOUSE
from runners.helpers.dbconnect import snowflake_connect


def read_queries(file, dyn_vars={}):
    vars = {
        'uuid': uuid4().hex,
        'DATABASE': DATABASE,
        'DATA_SCHEMA': DATA_SCHEMA,
        'RULES_SCHEMA': RULES_SCHEMA,
        'ALERT_QUERY_POSTFIX': ALERT_QUERY_POSTFIX,
        'ALERT_SQUELCH_POSTFIX': ALERT_SQUELCH_POSTFIX,
        'VIOLATION_QUERY_POSTFIX': VIOLATION_QUERY_POSTFIX,
    }
    vars.update(dyn_vars)  # Roll in any dynamic (runtime) vars
    pwd = os.path.dirname(os.path.realpath(__file__))
    tmpl = open(f'{pwd}/installer-queries/{file}.sql.fmt').read()
    return [t + ';' for t in tmpl.format(**vars).split(';') if t.strip()]


GRANT_PRIVILEGES_QUERIES = [
    f'GRANT ALL PRIVILEGES ON ALL SCHEMAS IN DATABASE {DATABASE} TO ROLE {ROLE}',
    f'GRANT ALL PRIVILEGES ON ALL VIEWS IN SCHEMA {DATA_SCHEMA} TO ROLE {ROLE}',
    f'GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA {DATA_SCHEMA} TO ROLE {ROLE}',
    f'GRANT OWNERSHIP ON ALL VIEWS IN SCHEMA {RULES_SCHEMA} TO ROLE {ROLE}',
    f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {DATA_SCHEMA} TO ROLE {ROLE}',
    f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {RESULTS_SCHEMA} TO ROLE {ROLE}',
]

WAREHOUSE_QUERIES = [
    f"""
      CREATE WAREHOUSE IF NOT EXISTS {WAREHOUSE}
        WAREHOUSE_SIZE=XSMALL
        WAREHOUSE_TYPE=STANDARD
        AUTO_SUSPEND=60
        AUTO_RESUME=TRUE
        INITIALLY_SUSPENDED=TRUE
    """,
]
DATABASE_QUERIES = [
    f'CREATE DATABASE IF NOT EXISTS {DATABASE}',
]
GRANT_PRIV_TO_ROLE = [
    f'GRANT ALL PRIVILEGES ON DATABASE {DATABASE} TO ROLE {ROLE}',
    f'GRANT ALL PRIVILEGES ON WAREHOUSE {WAREHOUSE} TO ROLE {ROLE}',
]

CREATE_SCHEMAS_QUERIES = [
    f"CREATE SCHEMA IF NOT EXISTS data",
    f"CREATE SCHEMA IF NOT EXISTS rules",
    f"CREATE SCHEMA IF NOT EXISTS results",
    f"DROP SCHEMA IF EXISTS public",
]

CREATE_TABLES_QUERIES = [
    f"""
      CREATE TABLE IF NOT EXISTS results.alerts(
        alert VARIANT
        , alert_time TIMESTAMP_LTZ(9)
        , event_time TIMESTAMP_LTZ(9)
        , ticket STRING
        , correlation_id STRING
        , suppressed BOOLEAN
        , suppression_rule STRING DEFAULT NULL
        , counter INTEGER DEFAULT 1
      );
    """,
    f"""
      CREATE TABLE IF NOT EXISTS results.violations(
        result VARIANT
        , id STRING
        , alert_time TIMESTAMP_LTZ(9)
        , ticket STRING
        , suppressed BOOLEAN
        , suppression_rule STRING DEFAULT NULL
      );
    """,
    f"""
      CREATE TABLE IF NOT EXISTS results.query_metadata(
          event_time TIMESTAMP_LTZ
          , v VARIANT
          );
      """,
    f"""
      CREATE TABLE IF NOT EXISTS results.run_metadata(
          event_time TIMESTAMP_LTZ
          , v VARIANT
          );
      """
]


def parse_snowflake_url(url):
    account = None
    region = None
    res = urlsplit(url)
    path = res.netloc or res.path

    c = path.split('.')

    if len(c) == 1:
        account = c[0]
    else:
        if path.endswith("snowflakecomputing.com"):
            account = c[0]
            region = c[1] if len(c) == 4 else 'us-west-2'

    return account, region


def login(config_account):
    config = ConfigParser()
    config_section = f'connections.{config_account}' if config_account else 'connections'
    if config.read(os.path.expanduser('~/.snowsql/config')) and config_section in config:
        account = config[config_section].get('accountname')
        username = config[config_section].get('username')
        password = config[config_section].get('password')
        region = config[config_section].get('region')
    else:
        account = None
        username = None
        password = None
        region = None

    print("Starting installer for SnowAlert.")

    if not account:
        while 1:
            url = input("Snowflake account where SnowAlert can store data, rules, and results (URL or account name): ")
            account, region = parse_snowflake_url(url)
            if not account:
                print("That's not a valid URL for a snowflake account. Please check for typos and try again.")
            else:
                break
    else:
        print(f"Loaded from ~/.snowcli/config: account '{account}'")

    print("Next, authenticate installer --")
    if not username:
        username = input("Snowflake username: ")
    else:
        print(f"Loaded from ~/.snowcli/config: username '{username}'")

    if not password:
        password = getpass("Password [leave blank for SSO for authentication]: ")
    else:
        print(f"Loaded from ~/.snowcli/config: password {'*' * len(password)}")

    if not region:
        region = input("Region of your Snowflake account [blank for us-west-2]: ")

    connect_kwargs = {'user': username, 'account': account}
    if password == '':
        connect_kwargs['authenticator'] = 'externalbrowser'
    else:
        connect_kwargs['password'] = password
    if region != '':
        connect_kwargs['region'] = region

    def attempt(message="doing", todo=None):
        print(f"{message}", end="..", flush=True)
        try:
            if type(todo) is str:
                retval = ctx.cursor().execute(todo).fetchall()
                print('.', end='', flush=True)
            if type(todo) is list:
                retval = [ctx.cursor().execute(query) for query in todo if (True, print('.', end='', flush=True))]
            elif callable(todo):
                retval = todo()
        except Exception as e:
            log.fatal("failed", e)
        print(" ✓")
        return retval

    ctx = attempt("Authenticating to Snowflake", lambda: snowflake_connect(**connect_kwargs))

    return ctx, account, region or "us-west-2", attempt


def load_aws_config() -> Tuple[str, str]:
    parser = ConfigParser()
    if parser.read(os.path.expanduser('~/.aws/config')) and 'default' in parser:
        c = parser['default']
        aws_key = c.get('aws_access_key_id')
        secret = c.get('aws_secret_access_key')
    else:
        return '', ''

    return aws_key, secret


def setup_warehouse_and_db(do_attempt):
    do_attempt("Creating and setting default warehouse", WAREHOUSE_QUERIES)
    do_attempt("Creating and using database", DATABASE_QUERIES)


def setup_schemas_and_tables(do_attempt, database):
    do_attempt(f"Use database {database}", f'USE DATABASE {database}')
    do_attempt("Creating schemas", CREATE_SCHEMAS_QUERIES)
    do_attempt("Creating alerts & violations tables", CREATE_TABLES_QUERIES)
    do_attempt("Creating standard UDTFs", read_queries('create-udtfs'))
    do_attempt("Creating standard data views", read_queries('data-views'))


def setup_user_and_role(do_attempt):
    defaults = f"login_name='{USER}' password='' default_role={ROLE} default_warehouse='{WAREHOUSE}'"
    do_attempt("Creating role and user", [
        f"CREATE ROLE IF NOT EXISTS {ROLE}",
        f"CREATE USER IF NOT EXISTS {USER} {defaults}",
        f"ALTER USER IF EXISTS {USER} SET {defaults}",  # in case user was manually created
    ])
    do_attempt("Granting role to user", f"GRANT ROLE {ROLE} TO USER {USER}")
    do_attempt("Granting privileges to role", GRANT_PRIV_TO_ROLE)


def setup_samples(do_attempt):
    share_row_array = do_attempt("Retrieving sample data share(s)", "SHOW TERSE SHARES LIKE '%SAMPLE_DATA'")
    if len(share_row_array) == 0:
      print(f"Unable to locate sample data share. Sample data cannot be loaded!")
      return
    share_db_names = [ share_row[3] for share_row in share_row_array ]  # Database name is 4th attribute in row
    for share_db_name in ('SNOWFLAKE_SAMPLE_DATA', 'SF_SAMPLE_DATA', 'SAMPLE_DATA'):  # Prioritize potential tie-breaks
      if share_db_name in share_db_names:
        break
    if not share_db_name:
      share_db_name = share_db_names[0]  # If not an expected sample data db name, just pick first one
    print(f"Using SAMPLE DATA share with name {share_db_name}")
    dyn_vars = {"SNOWFLAKE_SAMPLE_DATA":share_db_name}
    do_attempt("Creating data view", read_queries('sample-data-queries', dyn_vars))
    do_attempt("Creating sample alert", read_queries('sample-alert-queries', dyn_vars))
    do_attempt("Creating sample violation", read_queries('sample-violation-queries', dyn_vars))

def jira_integration(setup_jira=None):
    while setup_jira is None:
        uinput = input("Would you like to integrate Jira with SnowAlert (y/N)? ").lower()
        setup_jira = True if uinput.startswith('y') else False if uinput.startswith('n') else None

    if setup_jira:
        jira_url = input("Please enter the URL for the Jira integration: ")
        if jira_url[:8] != "https://":
            jira_url = "https://" + jira_url
        jira_user = input("Please enter the username for the SnowAlert user in Jira: ")
        jira_password = getpass("Please enter the password for the SnowAlert user in Jira: ")
        print("Please enter the project tag for the alerts...")
        print("Note that this should be the text that will prepend the ticket id; if the project is SnowAlert")
        print("and the tickets will be SA-XXXX, then you should enter 'SA' for this prompt.")
        jira_project = input("Please enter the project tag for the alerts from SnowAlert: ")
        return jira_user, jira_password, jira_url, jira_project
    else:
        return "", "", "", ""


def genrsa(passwd: Optional[str] = None) -> Tuple[bytes, bytes]:
    from cryptography.hazmat.primitives import serialization as cs  # crypto serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend as crypto_default_backend

    key = rsa.generate_private_key(
        backend=crypto_default_backend(),
        public_exponent=65537,
        key_size=2048
    )
    return (
        key.private_bytes(
            cs.Encoding.PEM,
            cs.PrivateFormat.PKCS8,
            encryption_algorithm=cs.BestAvailableEncryption(passwd.encode('utf-8')) if passwd else cs.NoEncryption()
        ),
        key.public_key().public_bytes(
            cs.Encoding.PEM,
            cs.PublicFormat.SubjectPublicKeyInfo
        )
    )


def setup_authentication(jira_password, region, pk_passwd=None):
    print("The access key for SnowAlert's Snowflake account can have a passphrase, if you wish.")

    if pk_passwd is None:
        pk_passwd = getpass("RSA key passphrase [blank for none, '.' for random]: ")

    if pk_passwd == '.':
        pk_passwd = b64encode(os.urandom(18)).decode('utf-8')
        print("Generated random passphrase.")

    private_key, public_key = genrsa(pk_passwd)

    if pk_passwd:
        print("\nAdditionally, you may use Amazon Web Services for encryption and audit.")
        kms = boto3.client('kms', region_name=region)
        while True:
            try:
                pk_passwd, jira_password = do_kms_encrypt(kms, pk_passwd, jira_password)
                break

            except KeyboardInterrupt:
                log.fatal("User ended installation")

            except Exception as e:
                print(f"error {e!r}, trying.")

    rsa_public_key = re.sub(r'---.*---\n', '', public_key.decode('utf-8'))

    return private_key, pk_passwd, jira_password, rsa_public_key


def gen_envs(jira_user, jira_project, jira_url, jira_password, account, region, private_key, pk_passwd,
             aws_key, aws_secret, **x):
    vars = [
        f'SNOWFLAKE_ACCOUNT={account}',
        f'SA_USER={USER}',
        f'SA_ROLE={ROLE}',
        f'SA_DATABASE={DATABASE}',
        f'SA_WAREHOUSE={WAREHOUSE}',
        f'REGION={region or "us-west-2"}',

        f'PRIVATE_KEY={b64encode(private_key).decode("utf-8")}',
        f'PRIVATE_KEY_PASSWORD={pk_passwd}',
    ]

    if jira_url:
        vars += [
            f'JIRA_URL={jira_url}',
            f'JIRA_PROJECT={jira_project}',
            f'JIRA_USER={jira_user}',
            f'JIRA_PASSWORD={jira_password}',
        ]

    if aws_key:
        vars += [
            f'AWS_ACCESS_KEY_ID={aws_key}' if aws_key else '',
            f'AWS_SECRET_ACCESS_KEY={aws_secret}' if aws_secret else '',
        ]

    return '\n'.join(vars)


def do_kms_encrypt(kms, *args: str) -> List[str]:
    key = input("Enter IAM KMS KeyId or 'alias/{KeyAlias}' [blank for none, '.' for random]: ")

    if not key:
        return list(args)

    if key == '.':
        result = kms.create_key()
        key = result['KeyMetadata']['KeyId']

    return [
        b64encode(kms.encrypt(KeyId=key, Plaintext=s).get('CiphertextBlob')).decode('utf-8') if s else ""
        for s in args
    ]


def main(admin_role="accountadmin", samples=True, pk_passwd=None, jira=None, config_account=None):
    ctx, account, region, do_attempt = login(config_account)

    do_attempt(f"Use role {admin_role}", f"USE ROLE {admin_role}")
    if admin_role == "accountadmin":
        setup_warehouse_and_db(do_attempt)
        setup_user_and_role(do_attempt)

    setup_schemas_and_tables(do_attempt, DATABASE)

    if samples:
        setup_samples(do_attempt)

    do_attempt("Granting privileges to role", GRANT_PRIVILEGES_QUERIES)

    jira_user, jira_password, jira_url, jira_project = jira_integration(jira)

    print(f"\n--- DB setup complete! Now, let's prep the runners... ---\n")

    private_key, pk_passwd, jira_password, rsa_public_key = setup_authentication(jira_password, region, pk_passwd)

    if admin_role == "accountadmin":
        do_attempt("Setting auth key on snowalert user", f"ALTER USER {USER} SET rsa_public_key='{rsa_public_key}'")

    aws_key, aws_secret = load_aws_config()

    print(
        f"\n--- ...all done! Next, run... ---\n"
        f"\ncat <<END_OF_FILE > snowalert-{account}.envs\n{gen_envs(**locals())}\nEND_OF_FILE\n"
        f"\n### ...and then... ###\n"
        f"\ndocker run --env-file snowalert-{account}.envs snowsec/snowalert ./run all\n"
        f"\n--- ...the end. ---\n"
    )


if __name__ == '__main__':
    fire.Fire(main)
