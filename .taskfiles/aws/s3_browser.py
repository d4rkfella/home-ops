#!/usr/bin/env python3
import boto3
import subprocess
import sys
import os
import configparser

AWS_DIR = os.path.join(os.getcwd(), ".aws")
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.path.join(AWS_DIR, "credentials")
os.environ["AWS_CONFIG_FILE"] = os.path.join(AWS_DIR, "config")

def run_fzf(options, prompt="> "):
    """Run fzf with a list of options, return selection."""
    if not options:
        return None
    try:
        result = subprocess.run(
            ["fzf", "--prompt", prompt],
            input="\n".join(options),
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip() if result.stdout else None
    except subprocess.CalledProcessError:
        return None

def load_endpoints():
    """Parse .aws/config for endpoint_url entries (for R2)."""
    endpoints = {}
    cfg = configparser.ConfigParser()
    cfg.read(os.environ["AWS_CONFIG_FILE"])
    for section in cfg.sections():
        name = section.replace("profile ", "")
        if cfg.has_option(section, "endpoint_url"):
            endpoints[name] = cfg.get(section, "endpoint_url")
    return endpoints

def select_profile():
    session = boto3.session.Session()
    profiles = session.available_profiles
    if not profiles:
        print("❌ No AWS/R2 profiles found in .aws/")
        sys.exit(1)

    profiles.append("<-- Exit")
    profile = run_fzf(profiles, "Select AWS/R2 profile> ")
    if not profile or profile == "<-- Exit":
        return None
    return profile

def list_buckets(session, endpoint=None):
    s3 = session.client("s3", endpoint_url=endpoint)
    resp = s3.list_buckets()
    return [b["Name"] for b in resp["Buckets"]]

def list_objects(session, bucket, prefix="", endpoint=None):
    s3 = session.client("s3", endpoint_url=endpoint)
    paginator = s3.get_paginator("list_objects_v2")
    kwargs = {"Bucket": bucket, "Prefix": prefix, "Delimiter": "/"}
    items = []
    for page in paginator.paginate(**kwargs):
        items.extend([p["Prefix"] for p in page.get("CommonPrefixes", [])])
        items.extend([o["Key"] for o in page.get("Contents", [])])
    return [i for i in items if i != prefix]

def delete_object(session, bucket, key, endpoint=None):
    s3 = session.client("s3", endpoint_url=endpoint)
    s3.delete_object(Bucket=bucket, Key=key)
    print(f"✅ Deleted object '{key}' from '{bucket}'")
    input("Press Enter to continue...")

def delete_bucket(session, bucket, endpoint=None):
    s3 = session.client("s3", endpoint_url=endpoint)
    print(f"⚠️  Are you sure you want to delete bucket '{bucket}' and all contents?")
    choice = run_fzf(["Yes (delete)", "Dry-run", "Cancel"], "Delete bucket> ")
    if choice == "Yes (delete)":
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
        s3.delete_bucket(Bucket=bucket)
        print(f"✅ Deleted bucket '{bucket}'")
    elif choice == "Dry-run":
        print(f"📝 Would delete bucket '{bucket}' and all contents (dry-run).")
    input("Press Enter to continue...")

def browse_objects(session, bucket, endpoint=None):
    prefix = ""
    while True:
        items = list_objects(session, bucket, prefix, endpoint)
        options = ["../"] + items
        selected = run_fzf(options, f"Bucket '{bucket}/{prefix}' > ")
        if not selected:
            break
        if selected == "../":
            prefix = "/".join(prefix.split("/")[:-2]) + "/" if prefix else ""
            continue
        if selected.endswith("/"):
            prefix = selected
        else:
            action = run_fzf(["Delete object", "Back"], f"Object '{selected}' > ")
            if action == "Delete object":
                delete_object(session, bucket, selected, endpoint)

def main():
    endpoints = load_endpoints()

    while True:
        profile = select_profile()
        if not profile:
            break

        session = boto3.session.Session(profile_name=profile)
        endpoint = endpoints.get(profile)

        while True:
            try:
                buckets = list_buckets(session, endpoint)
            except Exception as e:
                print(f"❌ Error listing buckets: {e}")
                input("Press Enter to continue...")
                break

            if not buckets:
                print("No buckets found.")
                input("Press Enter to continue...")
                break

            bucket = run_fzf(["<-- Back"] + buckets, "Bucket> ")
            if not bucket or bucket == "<-- Back":
                break

            action = run_fzf(["Browse objects", "Delete bucket", "Back"], f"Bucket '{bucket}' > ")
            if action == "Browse objects":
                browse_objects(session, bucket, endpoint)
            elif action == "Delete bucket":
                delete_bucket(session, bucket, endpoint)
            else:
                continue

if __name__ == "__main__":
    main()
