"""Helpers specific for SnowAlert, dealing with authentication, e.g. to Snowflake DB.
"""
from base64 import b64decode
from typing import Optional
from os import environ

import boto3
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from requests import post
from requests.auth import HTTPBasicAuth

from .dbconfig import REGION


def load_pkb(p8_private_key: bytes, encrypted_password: Optional[bytes]) -> bytes:
    """Loads private key bytes out of p8-encoded private key, using password decrypted via KMS, e.g.:

      > pkp8 = open('rsa_key.p8').read().encode('ascii')
      > encrypted_pass = base64.b64decode(open('encrypted_password').read())
      > pkb = load_pkb(pkp8, encrypted_pass)
      > len(pkb) > 1000
      True

    """
    if not encrypted_password:
        password = None
    elif len(encrypted_password) < 100:  # then we treat it as an unencrypted password
        password = encrypted_password
    else:
        kms = boto3.client('kms', region_name=REGION)
        password = kms.decrypt(CiphertextBlob=b64decode(encrypted_password))['Plaintext']

    private_key = serialization.load_pem_private_key(
        p8_private_key,
        password=password,
        backend=default_backend()
    )
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )


def oauth_refresh(account: str, refresh_token: str) -> str:
    OAUTH_CLIENT_ID = environ.get(f'OAUTH_CLIENT_{account.upper()}', '')
    OAUTH_SECRET_ID = environ.get(f'OAUTH_SECRET_{account.upper()}', '')

    return post(
        f'https://{account}.snowflakecomputing.com/oauth/token-request',
        auth=HTTPBasicAuth(OAUTH_CLIENT_ID, OAUTH_SECRET_ID),
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        },
    ).json().get('access_token')
