#!/usr/bin/env python3
import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound, SSLError, EndpointConnectionError

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView, ListItem, Label, Static, Tree
from textual.widgets.tree import TreeNode
from textual.screen import Screen


class ProfileSelectScreen(Screen):

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select profile", classes="title")

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
    BINDINGS = [
        ("b", "back", "Back"),
        ("d", "delete", "Delete Bucket"),
    ]

    def __init__(self, session, profile_name):
        super().__init__()
        self.session = session
        self.profile_name = profile_name

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
        lv.clear()

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
        await self.app.push_screen(ObjectBrowserTreeScreen(self.session, bucket, self.profile_name))

    async def action_delete(self):
        """Delete the currently selected bucket"""
        lv = self.query_one("#buckets", ListView)
        item = getattr(lv, "highlighted_child", None)
        if not item:
            self.app.notify("No bucket selected", severity="warning")
            return

        bucket_name = item.name
        if not bucket_name:
            return

        await self.app.push_screen(
            ConfirmDeleteBucketScreen(self.session, bucket_name, self)
        )

    async def action_back(self):
        await self.app.pop_screen()


class ObjectBrowserTreeScreen(Screen):
    BINDINGS = [
        ("b", "back", "Back"),
        ("d", "delete", "Delete"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, session, bucket, profile_name):
        super().__init__()
        self.bucket = bucket
        self.session = session
        self.profile_name = profile_name
        self.s3 = session.client("s3")
        self.loaded_nodes = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Bucket: {self.bucket} (Profile: {self.profile_name})", classes="title")
        tree: Tree = Tree(f"📦 {self.bucket}", id="object-tree")
        tree.show_root = False
        yield tree
        yield Footer()

    def on_mount(self):
        tree = self.query_one("#object-tree", Tree)
        tree.root.expand()
        self.load_node_children(tree.root, "")

    def load_node_children(self, node: TreeNode, prefix: str):
        node_id = id(node)
        if node_id in self.loaded_nodes:
            return
        self.loaded_nodes.add(node_id)

        try:
            paginator = self.s3.get_paginator("list_objects_v2")

            prefixes_added = set()
            objects_added = set()

            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
                for p in page.get("CommonPrefixes", []):
                    prefix_name = p["Prefix"]
                    if prefix_name not in prefixes_added:
                        prefixes_added.add(prefix_name)
                        folder_name = prefix_name[len(prefix):].rstrip("/")
                        child = node.add(f"📁 {folder_name}", data={"type": "prefix", "key": prefix_name})
                        child.allow_expand = True

                for o in page.get("Contents", []):
                    key = o["Key"]
                    if key == prefix:
                        continue
                    if key not in objects_added:
                        objects_added.add(key)
                        file_name = key[len(prefix):]
                        size_mb = o.get("Size", 0) / (1024 * 1024)
                        label = f"📄 {file_name} ({size_mb:.2f} MB)"
                        node.add_leaf(label, data={"type": "object", "key": key})

            if not prefixes_added and not objects_added:
                node.add_leaf("(empty)", data={"type": "empty", "key": ""})

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            node.add_leaf(f"❌ Error: {error_code} - {error_msg}", data={"type": "error", "key": ""})
            self.app.notify(f"❌ Error listing objects: {error_msg}", severity="error")
        except Exception as e:
            node.add_leaf(f"❌ Error: {type(e).__name__}", data={"type": "error", "key": ""})
            self.app.notify(f"❌ Error listing objects: {e}", severity="error")

    def on_tree_node_expanded(self, event: Tree.NodeExpanded):
        node = event.node

        if node.data is None:
            return

        if node.data.get("type") == "prefix":
            prefix = node.data.get("key", "")
            self.load_node_children(node, prefix)

    def on_tree_node_selected(self, event: Tree.NodeSelected):
        node = event.node

        if node.data is None:
            return

        node_type = node.data.get("type")
        key = node.data.get("key", "")

        if node_type == "object":
            self.app.push_screen(ModalMessageScreen(
                f"Selected object:\n{key}\n\nPress 'd' to delete this object."
            ))
        elif node_type == "prefix":
            node.toggle()

    async def action_delete(self):
        """Delete the currently selected object or folder"""
        tree = self.query_one("#object-tree", Tree)
        node = tree.cursor_node

        if not node or not node.data:
            self.app.notify("No object selected", severity="warning")
            return

        node_type = node.data.get("type")

        if node_type == "empty" or node_type == "error":
            self.app.notify("Cannot delete this item", severity="warning")
            return

        key = node.data.get("key", "")
        if not key:
            return

        if node_type == "prefix":
            await self.app.push_screen(
                ConfirmDeleteFolderScreen(self.session, self.bucket, key, self, node)
            )
        else:
            await self.app.push_screen(
                ConfirmDeleteScreen(self.session, self.bucket, key, self, node)
            )

    def delete_node_and_refresh(self, node: TreeNode):
        parent = node.parent
        node.remove()

        if parent and len(list(parent.children)) == 0:
            parent.add_leaf("(empty)", data={"type": "empty", "key": ""})

    async def action_refresh(self):
        tree = self.query_one("#object-tree", Tree)
        node = tree.cursor_node

        if not node:
            return

        self.loaded_nodes.discard(id(node))
        node.remove_children()

        if node.data is None:
            self.load_node_children(node, "")
        elif node.data.get("type") == "prefix":
            prefix = node.data.get("key", "")
            self.load_node_children(node, prefix)

        self.app.notify("Refreshed")

    async def action_back(self):
        await self.app.pop_screen()


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


class ConfirmDeleteBucketScreen(Screen):
    BINDINGS = [("y", "yes", "Yes"), ("n", "cancel", "No"), ("d", "dry", "Dry Run")]

    def __init__(self, session, bucket_name, caller):
        super().__init__()
        self.session = session
        self.bucket_name = bucket_name
        self.caller = caller
        self.object_count = 0

    def compose(self) -> ComposeResult:
        yield Static(f"🗑️  DELETE ENTIRE BUCKET: {self.bucket_name}")
        yield Static("Counting objects...", id="bucket-count-status")
        yield Static("⚠️  WARNING: This will delete ALL objects in the bucket!", classes="hint")
        yield Static("(y: confirm / n: cancel / d: dry run)", classes="hint")

    async def on_mount(self):
        await self.count_objects()

    async def count_objects(self):
        status = self.query_one("#bucket-count-status", Static)
        try:
            s3 = self.session.client("s3")
            paginator = s3.get_paginator("list_objects_v2")

            count = 0
            for page in paginator.paginate(Bucket=self.bucket_name):
                count += len(page.get("Contents", []))

            self.object_count = count

            if count == 0:
                status.update(f"Bucket is empty - ready to delete")
            else:
                status.update(f"⚠️  Bucket contains {count} object(s) - will delete ALL")

        except ClientError as e:
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            status.update(f"❌ Error counting objects: {error_msg}")
            self.app.notify(f"Error: {error_msg}", severity="error")
        except Exception as e:
            status.update(f"❌ Error: {e}")
            self.app.notify(f"Error: {e}", severity="error")

    async def action_yes(self):
        try:
            s3 = self.session.client("s3")

            if self.object_count > 0:
                self.app.notify(f"Deleting {self.object_count} objects...", timeout=5)

                paginator = s3.get_paginator("list_objects_v2")
                deleted_count = 0

                for page in paginator.paginate(Bucket=self.bucket_name):
                    objects = page.get("Contents", [])
                    if not objects:
                        continue

                    batch_size = 1000
                    for i in range(0, len(objects), batch_size):
                        batch = objects[i:i + batch_size]
                        delete_dict = {
                            'Objects': [{'Key': obj['Key']} for obj in batch],
                            'Quiet': True
                        }
                        s3.delete_objects(Bucket=self.bucket_name, Delete=delete_dict)
                        deleted_count += len(batch)

                self.app.notify(f"✅ Deleted {deleted_count} objects")

            s3.delete_bucket(Bucket=self.bucket_name)
            self.app.notify(f"✅ Deleted bucket: {self.bucket_name}")

            await self.app.pop_screen()

            try:
                await self.caller.load_buckets()
            except Exception as e:
                self.app.notify(f"⚠️ Error refreshing bucket list: {e}", severity="warning")

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            self.app.notify(f"❌ Delete failed ({error_code}): {error_msg}", severity="error")
            await self.app.pop_screen()
        except Exception as e:
            self.app.notify(f"❌ Delete failed: {e}", severity="error")
            await self.app.pop_screen()

    async def action_dry(self):
        msg = f"[DRY RUN]\nWould delete bucket: {self.bucket_name}\n"
        if self.object_count > 0:
            msg += f"Including {self.object_count} object(s)"
        else:
            msg += "Bucket is empty"
        await self.app.push_screen(ModalMessageScreen(msg))

    async def action_cancel(self):
        await self.app.pop_screen()


class ConfirmDeleteScreen(Screen):
    BINDINGS = [("y", "yes", "Yes"), ("n", "cancel", "No"), ("d", "dry", "Dry Run")]

    def __init__(self, session, bucket, key, caller, node):
        super().__init__()
        self.session = session
        self.bucket = bucket
        self.key = key
        self.caller = caller
        self.node = node

    def compose(self) -> ComposeResult:
        yield Static(f"Delete {self.key} from {self.bucket}? (y/n/d)")

    async def action_yes(self):
        try:
            s3 = self.session.client("s3")
            s3.delete_object(Bucket=self.bucket, Key=self.key)
            self.app.notify(f"✅ Deleted: {self.key}")
            await self.app.pop_screen()
            try:
                self.caller.delete_node_and_refresh(self.node)
            except Exception as e:
                self.app.notify(f"⚠️ Error refreshing tree: {e}", severity="warning")
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


class ConfirmDeleteFolderScreen(Screen):
    BINDINGS = [("y", "yes", "Yes"), ("n", "cancel", "No"), ("d", "dry", "Dry Run")]

    def __init__(self, session, bucket, prefix, caller, node):
        super().__init__()
        self.session = session
        self.bucket = bucket
        self.prefix = prefix
        self.caller = caller
        self.node = node
        self.objects_to_delete = []

    def compose(self) -> ComposeResult:
        yield Static(f"🗑️  Delete folder: {self.prefix}")
        yield Static("Counting objects...", id="count-status")
        yield Static("(y: confirm / n: cancel / d: dry run)", classes="hint")

    async def on_mount(self):
        await self.count_objects()

    async def count_objects(self):
        status = self.query_one("#count-status", Static)
        try:
            s3 = self.session.client("s3")
            paginator = s3.get_paginator("list_objects_v2")

            count = 0
            self.objects_to_delete = []

            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                for obj in page.get("Contents", []):
                    self.objects_to_delete.append(obj["Key"])
                    count += 1

            if count == 0:
                status.update("⚠️  No objects found in this folder")
            else:
                status.update(f"⚠️  This will delete {count} object(s)")

        except ClientError as e:
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            status.update(f"❌ Error counting objects: {error_msg}")
            self.app.notify(f"Error: {error_msg}", severity="error")
        except Exception as e:
            status.update(f"❌ Error: {e}")
            self.app.notify(f"Error: {e}", severity="error")

    async def action_yes(self):
        if not self.objects_to_delete:
            self.app.notify("No objects to delete", severity="warning")
            await self.app.pop_screen()
            return

        try:
            s3 = self.session.client("s3")
            deleted_count = 0
            failed_count = 0

            batch_size = 1000
            for i in range(0, len(self.objects_to_delete), batch_size):
                batch = self.objects_to_delete[i:i + batch_size]
                delete_dict = {
                    'Objects': [{'Key': key} for key in batch],
                    'Quiet': True
                }

                try:
                    response = s3.delete_objects(Bucket=self.bucket, Delete=delete_dict)
                    deleted_count += len(batch)

                    errors = response.get('Errors', [])
                    if errors:
                        failed_count += len(errors)
                        for error in errors[:3]:
                            self.app.notify(
                                f"Failed to delete {error.get('Key')}: {error.get('Message')}",
                                severity="error"
                            )
                except ClientError as e:
                    failed_count += len(batch)
                    error_msg = e.response.get('Error', {}).get('Message', str(e))
                    self.app.notify(f"Batch delete failed: {error_msg}", severity="error")

            if failed_count == 0:
                self.app.notify(f"✅ Deleted folder with {deleted_count} object(s)")
            else:
                self.app.notify(
                    f"⚠️  Deleted {deleted_count} objects, {failed_count} failed",
                    severity="warning"
                )

            await self.app.pop_screen()
            try:
                self.caller.delete_node_and_refresh(self.node)
            except Exception as e:
                self.app.notify(f"⚠️ Error refreshing tree: {e}", severity="warning")

        except Exception as e:
            self.app.notify(f"❌ Delete failed: {e}", severity="error")
            await self.app.pop_screen()

    async def action_dry(self):
        if not self.objects_to_delete:
            await self.app.push_screen(ModalMessageScreen(f"[DRY RUN]\nNo objects found in:\n{self.prefix}"))
        else:
            preview = "\n".join(self.objects_to_delete[:20])
            if len(self.objects_to_delete) > 20:
                preview += f"\n... and {len(self.objects_to_delete) - 20} more"
            await self.app.push_screen(
                ModalMessageScreen(f"[DRY RUN]\nWould delete {len(self.objects_to_delete)} objects from:\n{self.prefix}\n\n{preview}")
            )

    async def action_cancel(self):
        await self.app.pop_screen()


class S3Browser(App):
    TITLE = "S3 Browser"
    CSS_PATH = None
    BINDINGS = [("q", "quit", "Quit")]

    def on_mount(self):
        self.push_screen(ProfileSelectScreen())


if __name__ == "__main__":
    S3Browser().run()
