#!/usr/bin/env python3
import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound, SSLError, EndpointConnectionError

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView, ListItem, Label, Static
from textual.screen import Screen


class ProfileSelectScreen(Screen):

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select AWS/R2 profile", classes="title")

        try:
            session = boto3.session.Session()
            profiles = session.available_profiles

            yield ListView(
                *(ListItem(Label(profile), name=profile) for profile in profiles),
                id="profiles"
            )
        except Exception as e:
            self.app.notify(f"{e}", severity="error")

        yield Footer()

    async def on_list_view_selected(self, event: ListView.Selected):
        profile = event.item.name
        try:
            session = boto3.session.Session(profile_name=profile)
            await self.app.push_screen(BucketSelectScreen(session, profile))
        except ProfileNotFound:
            self.app.notify(f"Profile '{profile}' not found in config", severity="error")
        except NoCredentialsError:
            self.app.notify(f"No credentials found for profile '{profile}'", severity="error")
        except Exception as e:
            self.app.notify(f"Error loading profile: {e}", severity="error")


class BucketSelectScreen(Screen):
    BINDINGS = [("b", "back", "Back")]

    def __init__(self, session, profile_name):
        super().__init__()
        self.session = session
        self.profile_name = profile_name
        self.buckets_loaded = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Select Bucket (Profile: {self.profile_name})", classes="title")
        yield ListView(id="buckets")
        yield Footer()

    async def on_mount(self):
        """Load buckets asynchronously after mount to avoid blocking"""
        await self.load_buckets()

    async def load_buckets(self):
        lv = self.query_one("#buckets", ListView)

        try:
            s3 = self.session.client("s3")
            buckets = s3.list_buckets().get("Buckets", [])

            if not buckets:
                self.app.notify(f"No buckets found in profile '{self.profile_name}'")
            else:
                for b in buckets:
                    lv.append(ListItem(Label(b["Name"]), name=b["Name"]))
                self.app.notify(f"Loaded {len(buckets)} buckets")

        except SSLError as e:
            self.app.notify(f"{e}", severity="error")
            self.dismiss()
        except EndpointConnectionError as e:
            self.app.notify(f"{e}", severity="error")
            self.dismiss()
        except NoCredentialsError as e:
            self.app.notify(f"{e}", severity="error")
            self.dismiss()
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            self.app.notify(f"({error_code}): {error_msg}", severity="error")
            self.dismiss()
        except Exception as e:
            self.app.notify(f"{e}", severity="error")
            self.dismiss()

    async def on_list_view_selected(self, event: ListView.Selected):
        bucket = event.item.name
        await self.app.push_screen(ObjectBrowserScreen(self.session, bucket, self.profile_name))

    async def action_back(self):
        await self.app.pop_screen()


class ObjectBrowserScreen(Screen):
    BINDINGS = [
        ("b", "back", "Back"),
        ("d", "delete", "Delete"),
    ]

    def __init__(self, session, bucket, profile_name):
        super().__init__()
        self.bucket = bucket
        self.session = session
        self.profile_name = profile_name
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

        lv = self.query_one("#objects", ListView)
        lv.clear()

        try:
            s3 = self.session.client("s3")
            paginator = s3.get_paginator("list_objects_v2")

            items = [ListItem(Label("../"), name="../")]
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix, Delimiter="/"):
                for p in page.get("CommonPrefixes", []):
                    items.append(ListItem(Label(p["Prefix"]), name=p["Prefix"]))
                for o in page.get("Contents", []):
                    items.append(ListItem(Label(o["Key"]), name=o["Key"]))

            for item in items:
                lv.append(item)

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            lv.append(ListItem(Label(f"❌ Error: {error_code} - {error_msg}")))
            self.app.notify(f"❌ Error listing objects: {error_msg}", severity="error")
        except Exception as e:
            lv.append(ListItem(Label(f"❌ Error: {type(e).__name__}")))
            self.app.notify(f"❌ Error listing objects: {e}", severity="error")

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
        if key == "../" or not key:
            return
        await self.app.push_screen(
            ConfirmDeleteScreen(self.session, self.bucket, key, self)
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

    def __init__(self, session, bucket, key, caller):
        super().__init__()
        self.session = session
        self.bucket = bucket
        self.key = key
        self.caller = caller

    def compose(self) -> ComposeResult:
        yield Static(f"Delete {self.key} from {self.bucket}? (y/n/d)")

    async def action_yes(self):
        try:
            s3 = self.session.client("s3")
            s3.delete_object(Bucket=self.bucket, Key=self.key)
            self.app.notify(f"✅ Deleted: {self.key}")
            await self.app.pop_screen()
            try:
                self.caller.refresh_objects()
            except Exception as e:
                self.app.notify(f"⚠️ Error refreshing list: {e}", severity="warning")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            self.app.notify(f"❌ Delete failed ({error_code}): {error_msg}", severity="error")
            await self.app.pop_screen()
        except Exception as e:
            self.app.notify(f"❌ Delete failed: {e}", severity="error")
            await self.app.pop_screen()

    async def action_dry(self):
        await self.app.push_screen(ModalMessageScreen(f"[DRY RUN]\nWould delete:\n{self.key}"))

    async def action_cancel(self):
        await self.app.pop_screen()


class R2Browser(App):
    TITLE = "R2 / AWS S3 Browser"
    CSS_PATH = None
    BINDINGS = [("q", "quit", "Quit")]

    def on_mount(self):
        self.push_screen(ProfileSelectScreen())


if __name__ == "__main__":
    R2Browser().run()
