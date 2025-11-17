#!/usr/bin/env python3
import os
import boto3
import configparser

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView, ListItem, Label, Static
from textual.screen import Screen

AWS_DIR = os.path.join(os.getcwd(), ".aws")
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.path.join(AWS_DIR, "credentials")
os.environ["AWS_CONFIG_FILE"] = os.path.join(AWS_DIR, "config")


# -------------------------------
# Helpers
# -------------------------------

def load_endpoints():
    session = boto3.session.Session()
    profiles = session.available_profiles
    cfg = configparser.ConfigParser()
    cfg.read(os.environ["AWS_CONFIG_FILE"])

    endpoints = {}
    for profile in profiles:
        section_name = "profile " + profile if profile != "default" else "default"
        if cfg.has_option(section_name, "endpoint_url"):
            endpoints[profile] = cfg.get(section_name, "endpoint_url")
    return endpoints


# -------------------------------
# Screens
# -------------------------------

class ProfileSelectScreen(Screen):

    def __init__(self, endpoints):
        super().__init__()
        self.endpoints = endpoints

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select AWS/R2 profile", classes="title")

        session = boto3.session.Session()
        profiles = session.available_profiles or []

        yield ListView(
            *(ListItem(Label(profile), name=profile) for profile in profiles),
            id="profiles"
        )

        yield Footer()

    async def on_list_view_selected(self, event: ListView.Selected):
        profile = event.item.name
        endpoint = self.endpoints.get(profile)
        session = boto3.session.Session(profile_name=profile)
        await self.app.push_screen(BucketSelectScreen(session, endpoint))


class BucketSelectScreen(Screen):
    BINDINGS = [("b", "back", "Back")]

    def __init__(self, session, endpoint):
        super().__init__()
        self.session = session
        self.endpoint = endpoint
        self.session = session

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select Bucket", classes="title")

        s3 = self.session.client("s3", endpoint_url=self.endpoint)
        buckets = s3.list_buckets().get("Buckets", [])

        yield ListView(
            *(ListItem(Label(b["Name"]), name=b["Name"]) for b in buckets),
            id="buckets"
        )

        yield Footer()

    async def on_list_view_selected(self, event: ListView.Selected):
        bucket = event.item.name
        await self.app.push_screen(ObjectBrowserScreen(self.session, self.endpoint, bucket))

    async def action_back(self):
        await self.app.pop_screen()


class ObjectBrowserScreen(Screen):
    BINDINGS = [
        ("b", "back", "Back"),
        ("d", "delete", "Delete"),
    ]

    def __init__(self, session, endpoint, bucket):
        super().__init__()
        self.bucket = bucket
        self.session = session
        self.endpoint = endpoint
        self.prefix = ""

    def compose(self) -> ComposeResult:
        yield Header()
        self.title_static = Static(f"Bucket: {self.bucket}/{self.prefix}", classes="title")
        yield self.title_static
        yield ListView(id="objects")
        yield Footer()

    def on_mount(self):
        self.refresh_objects()

    def refresh_objects(self):
        self.title_static.update(f"Bucket: {self.bucket}/{self.prefix}")

        s3 = self.session.client("s3", endpoint_url=self.endpoint)
        paginator = s3.get_paginator("list_objects_v2")

        items = [ListItem(Label("../"), name="../")]
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix, Delimiter="/"):
            for p in page.get("CommonPrefixes", []):
                items.append(ListItem(Label(p["Prefix"]), name=p["Prefix"]))
            for o in page.get("Contents", []):
                items.append(ListItem(Label(o["Key"]), name=o["Key"]))

        lv = self.query_one("#objects", ListView)
        lv.clear()
        for item in items:
            lv.append(item)

    async def on_list_view_selected(self, event: ListView.Selected):
        choice = event.item.name
        if not choice:
            return

        if choice == "../":
            if not self.prefix:
                return
            parts = self.prefix.rstrip("/").split("/")
            self.prefix = "/".join(parts[:-1]) + ("/" if len(parts) > 1 else "")
            self.refresh_objects()
            return

        if choice.endswith("/"):
            self.prefix = choice
            self.refresh_objects()
            return

        await self.app.push_screen(ModalMessageScreen(f"Selected object:\n{choice}"))

    async def action_delete(self):
        lv = self.query_one("#objects", ListView)
        item = getattr(lv, "highlighted_child", None)
        if not item:
            return
        key = item.name
        await self.app.push_screen(
            ConfirmDeleteScreen(self.session, self.endpoint, self.bucket, key, self)
        )

    async def action_back(self):
        if not self.prefix:
            await self.app.pop_screen()
        else:
            parts = self.prefix.rstrip("/").split("/")
            self.prefix = "/".join(parts[:-1]) + ("/" if len(parts) > 1 else "")
            self.refresh_objects()

class ModalMessageScreen(Screen):
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        yield Static(self.text)
        yield Static("Press ESC to close.", classes="hint")

    async def action_close(self):
        await self.app.pop_screen()


class ConfirmDeleteScreen(Screen):
    BINDINGS = [("y", "yes", "Yes"), ("n", "cancel", "No"), ("d", "dry", "Dry Run")]

    def __init__(self, session, endpoint, bucket, key, caller):
        super().__init__()
        self.session = session
        self.endpoint = endpoint
        self.bucket = bucket
        self.key = key
        self.caller = caller

    def compose(self) -> ComposeResult:
        yield Static(f"Delete {self.key} from {self.bucket}? (y/n/d)")

    async def action_yes(self):
        s3 = self.session.client("s3", endpoint_url=self.endpoint)
        s3.delete_object(Bucket=self.bucket, Key=self.key)
        await self.app.pop_screen()
        try:
            self.caller.refresh_objects()
        except Exception:
            pass

    async def action_dry(self):
        await self.app.push_screen(ModalMessageScreen(f"[DRY RUN]\nWould delete:\n{self.key}"))

    async def action_cancel(self):
        await self.app.pop_screen()


# -------------------------------
# Main App
# -------------------------------

class R2Browser(App):
    TITLE = "R2 / AWS S3 Browser"
    CSS_PATH = None
    BINDINGS = [("q", "quit", "Quit")]

    def on_mount(self):
        endpoints = load_endpoints()
        self.push_screen(ProfileSelectScreen(endpoints))


if __name__ == "__main__":
    R2Browser().run()
