#!/usr/bin/env python3
import boto3
import subprocess
import sys
import os
import configparser

AWS_DIR = os.path.join(os.getcwd(), ".aws")
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.path.join(AWS_DIR, "credentials")
os.environ["AWS_CONFIG_FILE"] = os.path.join(AWS_DIR, "config")


def run_fzf(options, prompt="> ", expect=None):
    """Run fzf with optional keybinds, return (key, selection)."""
    if not options:
        return None, None
    cmd = ["fzf", "--prompt", prompt]
    if expect:
        cmd.append(f"--expect={expect}")
    result = subprocess.run(
        cmd, input="\n".join(options), text=True, capture_output=True
    )
    if result.returncode != 0 or not result.stdout:
        return None, None
    lines = result.stdout.strip().split("\n")
    key = lines[0] if len(lines) > 1 else ""
    selection = lines[-1]
    return key, selection


def load_endpoints():
    """Parse .aws/config for endpoint_url entries (for Cloudflare R2)."""
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
    _, profile = run_fzf(profiles, "Select AWS/R2 profile> ")
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
    print(f"⚠️  Are you sure you want to delete object '{key}' in bucket '{bucket}'?")
    _, choice = run_fzf(["Yes (delete)", "Dry-run", "Cancel"], "Delete object> ")
    if choice == "Yes (delete)":
        s3 = session.client("s3", endpoint_url=endpoint)
        s3.delete_object(Bucket=bucket, Key=key)
        print(f"✅ Deleted object '{key}' from '{bucket}'")
    elif choice == "Dry-run":
        print(f"📝 Would delete object '{key}' (dry-run).")
    else:
        print("❌ Cancelled.")
    input("Press Enter to continue...")


def delete_prefix(session, bucket, prefix, endpoint=None):
    print(f"⚠️  Are you sure you want to delete ALL objects under prefix '{prefix}' in '{bucket}'?")
    _, choice = run_fzf(["Yes (delete)", "Dry-run", "Cancel"], "Delete prefix> ")
    s3 = session.client("s3", endpoint_url=endpoint)

    if choice == "Yes (delete)":
        s3_resource = boto3.resource("s3", endpoint_url=endpoint, region_name=session.region_name)
        bucket_resource = s3_resource.Bucket(bucket)
        bucket_resource.objects.filter(Prefix=prefix).delete()
        print(f"✅ Deleted all objects under '{prefix}' in '{bucket}'")
    elif choice == "Dry-run":
        paginator = s3.get_paginator("list_objects_v2")
        print(f"📝 Objects that would be deleted (dry-run):")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                print("   " + obj["Key"])
    else:
        print("❌ Cancelled.")
    input("Press Enter to continue...")


def delete_bucket(session, bucket, endpoint=None):
    print(f"⚠️  Are you sure you want to delete bucket '{bucket}' and ALL contents?")
    _, choice = run_fzf(["Yes (delete)", "Dry-run", "Cancel"], "Delete bucket> ")
    s3 = session.client("s3", endpoint_url=endpoint)

    if choice == "Yes (delete)":
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
        s3.delete_bucket(Bucket=bucket)
        print(f"✅ Deleted bucket '{bucket}'")
    elif choice == "Dry-run":
        print(f"📝 Would delete bucket '{bucket}' and all contents (dry-run).")
    else:
        print("❌ Cancelled.")
    input("Press Enter to continue...")


def browse_objects(session, bucket, endpoint=None):
    prefix = ""
    while True:
        items = list_objects(session, bucket, prefix, endpoint)
        options = ["../"] + items
        key, selected = run_fzf(options, f"Bucket '{bucket}/{prefix}' > ", expect="ctrl-d")

        if not selected:
            break

        if selected == "../":
            prefix = "/".join(prefix.split("/")[:-2]) + "/" if prefix else ""
            continue

        if key == "ctrl-d":  # delete with confirmation
            if selected.endswith("/"):
                delete_prefix(session, bucket, selected, endpoint)
            else:
                delete_object(session, bucket, selected, endpoint)
        else:  # plain enter
            if selected.endswith("/"):
                prefix = selected
            else:
                print(f"📄 Selected object: {selected}")
                input("Press Enter to continue...")


def bucket_menu(session, buckets, endpoint=None):
    while True:
        key, selected = run_fzf(["<-- Back"] + buckets, "Bucket> ", expect="ctrl-d")

        if not selected or selected == "<-- Back":
            break

        if key == "ctrl-d":
            delete_bucket(session, selected, endpoint)
            buckets = list_buckets(session, endpoint)
        else:
            browse_objects(session, selected, endpoint)


def main():
    endpoints = load_endpoints()

    while True:
        profile = select_profile()
        if not profile:
            break

        session = boto3.session.Session(profile_name=profile)
        endpoint = endpoints.get(profile)

        try:
            buckets = list_buckets(session, endpoint)
        except Exception as e:
            print(f"❌ Error listing buckets: {e}")
            input("Press Enter to continue...")
            continue

        if not buckets:
            print("No buckets found.")
            input("Press Enter to continue...")
            continue

        bucket_menu(session, buckets, endpoint)


if __name__ == "__main__":
    main()
