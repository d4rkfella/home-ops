#!/usr/bin/env python3
"""
Rotate the Issuing CA in Vault using the Reissuance primitive
(same key material, new certificate signed by intermediate)
Stores temp files in /tmp and cleans them up afterwards.
"""

import hvac
import sys
import os
import getpass
from datetime import datetime

ISS_MOUNT = "pki_iss"
INT_MOUNT = "pki_int"
COMMON_NAME = "DarkfellaNET Issuing CA v1.1.1"
TTL = "8760h"

TMP_DIR = "/tmp"
CSR_FILE = os.path.join(TMP_DIR, "issuing_ca_reissue.csr")
SIGNED_FILE = os.path.join(TMP_DIR, "issuing_ca_reissue_signed.pem")

VAULT_ADDR = os.getenv("VAULT_ADDR") or input("Vault URL (e.g., https://vault.example.com:8200): ").strip()
client = hvac.Client(url=VAULT_ADDR)

VAULT_TOKEN = os.getenv("VAULT_TOKEN")
if not VAULT_TOKEN:
    print("Vault token not found, logging in with username/password.")
    username = input("Vault username: ").strip()
    password = getpass.getpass("Vault password: ").strip()
    try:
        login_resp = client.auth.userpass.login(username=username, password=password)
        VAULT_TOKEN = login_resp['auth']['client_token']
        client.token = VAULT_TOKEN
        print("✅ Logged in successfully. Vault token acquired.")
    except hvac.exceptions.InvalidRequest as e:
        print(f"❌ Vault login failed: {e}")
        sys.exit(1)
else:
    client.token = VAULT_TOKEN

if not client.is_authenticated():
    print("❌ Authentication to Vault failed.")
    sys.exit(1)

print(f"🔐 Connected to Vault at {VAULT_ADDR}")

try:
    old_issuers = client.list(f"{ISS_MOUNT}/issuers")['data']['keys']
except Exception:
    old_issuers = []

try:
    print("📄 Generating CSR using existing key material...")
    generate_resp = client.write(
        f"{ISS_MOUNT}/issuers/generate/intermediate/existing",
        common_name=COMMON_NAME,
        country="Bulgaria",
        locality="Sofia",
        organization="DarkfellaNET",
        ttl=TTL,
        format="pem_bundle",
    )
    csr = generate_resp['data']['csr']
    with open(CSR_FILE, "w") as f:
        f.write(csr)
    print(f"✅ CSR written to {CSR_FILE}")

    print("🖊️ Signing CSR with intermediate CA...")
    sign_resp = client.write(
        f"{INT_MOUNT}/root/sign-intermediate",
        csr=csr,
        country="Bulgaria",
        locality="Sofia",
        organization="DarkfellaNET",
        format="pem_bundle",
        ttl=TTL,
        common_name=COMMON_NAME,
    )
    signed_cert = sign_resp['data']['certificate']
    with open(SIGNED_FILE, "w") as f:
        f.write(signed_cert)
    print(f"✅ Signed certificate saved to {SIGNED_FILE}")

    print(f"📦 Importing signed certificate back into {ISS_MOUNT}...")
    client.write(f"{ISS_MOUNT}/intermediate/set-signed", certificate=signed_cert)

    issuers = client.list(f"{ISS_MOUNT}/issuers")['data']['keys']
    new_issuers = [i for i in issuers if i not in old_issuers]
    if not new_issuers:
        print("⚠️ Could not determine new issuer ID. Using last issuer in list.")
        new_issuer_id = issuers[-1]
    else:
        new_issuer_id = new_issuers[0]

    client.write(f"{ISS_MOUNT}/config/issuers", default=new_issuer_id)
    print(f"✅ New issuer {new_issuer_id} set as default")

    issuer_info = client.read(f"{ISS_MOUNT}/issuer/{new_issuer_id}")
    if issuer_info and "data" in issuer_info:
        data = issuer_info['data']
        print("\n📜 New Issuing CA info:")
        print(f"   Subject: {data.get('subject')}")
        print(f"   Serial: {data.get('serial_number')}")
        if data.get('not_after'):
            expires = datetime.fromisoformat(data['not_after'].replace("Z", "+00:00"))
            print(f"   Expires: {expires}")
    else:
        print("\n⚠️ Could not read info for the new issuer")

finally:
    for tmp_file in [CSR_FILE, SIGNED_FILE]:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
            print(f"🧹 Cleaned up temporary file: {tmp_file}")

print("\n🎉 Done! Issuing CA successfully reissued and set as default.")
