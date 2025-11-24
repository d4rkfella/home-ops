#!/usr/bin/env python3
import datetime
from typing import Any, cast
import boto3
import os
from botocore.exceptions import NoCredentialsError, ProfileNotFound

from textual.app import App, ComposeResult
from textual.events import Paste
from textual.containers import Horizontal, Vertical, Container
from mypy_boto3_s3.client import S3Client
from mypy_boto3_s3.type_defs import DeleteTypeDef
from textual.widgets import Header, Footer, ListView, ListItem, Label, Static, Tree, Markdown, TextArea, ProgressBar, DirectoryTree
from textual.widgets.tree import TreeNode
from textual.color import Gradient
from textual.screen import Screen, ModalScreen
from textual import work


class S3Browser(App):
    TITLE = "S3 Browser"
    CSS_PATH = None
    BINDINGS = [("q", "quit", "Quit")]

    s3: S3Client | None

    def on_mount(self):
        self.s3 = None
        self.push_screen(ProfileSelectScreen())


class FilePreviewScreen(ModalScreen):
    app: "S3Browser" # type: ignore[assignment]
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, bucket, key):
        super().__init__()
        self.bucket = bucket
        self.key = key

    def compose(self) -> ComposeResult:
        yield Header()
        yield TextArea("Loading content...", id="code-view", read_only=True)
        yield Footer()

    def on_mount(self):
        self.title = f"Preview: {self.key}"
        self.load_content()

    @work(thread=True)
    def load_content(self):
        s3 = self.app.s3
        assert s3 is not None
        text_area = self.query_one("#code-view", TextArea)
        try:
            response = s3.get_object(Bucket=self.bucket, Key=self.key, Range='bytes=0-15000')
            content = response['Body'].read().decode('utf-8', errors='replace')
            self.app.call_from_thread(self.update_text_area, content)
        except Exception as e:
            self.app.call_from_thread(text_area.load_text, f"Error loading content: {e}")

    def update_text_area(self, content):
        text_area = self.query_one("#code-view", TextArea)
        text_area.load_text(content)
        ext = self.key.split('.')[-1].lower() if '.' in self.key else ""
        lang_map = {
            "py": "python", "js": "javascript", "json": "json",
            "md": "markdown", "sql": "sql", "css": "css", "html": "html",
            "yml": "yaml", "yaml": "yaml", "sh": "bash", "rs": "rust", "go": "go"
        }
        text_area.language = lang_map.get(ext, None)

    async def action_close(self):
        await self.app.pop_screen()


class DownloadScreen(ModalScreen):
    app: "S3Browser" # type: ignore[assignment]
    DOWNLOAD_GRADIENT = Gradient(
        (0.0, "#A00000"),
        (0.33, "#FF7300"),
        (0.66, "#4caf50"),
        (1.0, "#8bc34a"),
        quality=50,
    )

    def __init__(self, bucket, key):
        super().__init__()
        self.bucket = bucket
        self.key = key

    def compose(self) -> ComposeResult:
        yield Static(f"\n  📥 Downloading: {self.key}\n", classes="title")
        yield ProgressBar(total=100, show_eta=True, id="pbar", gradient=self.DOWNLOAD_GRADIENT)
        yield Static("\n  Please wait...", classes="hint")

    def on_mount(self):
        self.download_file()

    @work(thread=True)
    def download_file(self):
        s3 = self.app.s3
        assert s3 is not None
        pbar = self.query_one("#pbar", ProgressBar)
        try:
            meta = s3.head_object(Bucket=self.bucket, Key=self.key)
            total_bytes = meta['ContentLength']
            self.app.call_from_thread(pbar.update, total=total_bytes)

            def progress_callback(chunk):
                self.app.call_from_thread(pbar.advance, chunk)

            filename = os.path.basename(self.key)
            s3.download_file(
                self.bucket,
                self.key,
                filename,
                Callback=progress_callback
            )
            self.app.notify(f"Saved to {os.path.abspath(filename)}")
            self.app.call_from_thread(self.dismiss)
        except Exception as e:
            self.app.notify(f"Download failed: {e}", severity="error")
            self.app.call_from_thread(self.dismiss)


class ProfileSelectScreen(Screen):
    app: "S3Browser" # type: ignore[assignment]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select AWS Profile", classes="title")
        try:
            session = boto3.session.Session()
            profiles = session.available_profiles
            if not profiles:
                yield Static("No profiles found in ~/.aws/credentials or ~/.aws/config")
            else:
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
            self.app.s3 = session.client("s3")
            await self.app.push_screen(BucketSelectScreen(profile))
        except ProfileNotFound:
            self.app.notify(f"Profile '{profile}' not found in config", severity="error")
        except NoCredentialsError:
            self.app.notify(f"No credentials found for profile '{profile}'", severity="error")
        except Exception as e:
            self.app.notify(f"Error loading profile: {e}", severity="error")


class BucketSelectScreen(Screen):
    app: "S3Browser" # type: ignore[assignment]

    BINDINGS = [("b", "back", "Back"), ("d", "delete", "Delete Bucket")]

    def __init__(self, profile_name):
        super().__init__()
        self.profile_name = profile_name

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Select Bucket (Profile: {self.profile_name})", classes="title")
        yield ListView(id="buckets")
        yield Footer()

    def on_mount(self):
        self.load_buckets()

    @work(thread=True)
    def load_buckets(self):
        try:
            s3 = self.app.s3
            assert s3 is not None
            buckets = s3.list_buckets().get("Buckets", [])
            self.app.call_from_thread(self.update_bucket_list, buckets)
        except Exception as e:
            self.app.notify(f"Error loading buckets: {e}", severity="error")

    def update_bucket_list(self, buckets):
        lv = self.query_one("#buckets", ListView)
        lv.clear()
        if not buckets:
            self.app.notify(f"No buckets found in profile '{self.profile_name}'")
        else:
            for b in buckets:
                lv.append(ListItem(Label(b["Name"]), name=b["Name"]))

    @work(thread=True)
    def delete_bucket(self, bucket_name: str):
        try:
            s3 = self.app.s3
            assert s3 is not None
            paginator = s3.get_paginator("list_objects_v2")
            object_keys = []
            for page in paginator.paginate(Bucket=bucket_name):
                for obj in page.get("Contents", []):
                    key = obj.get("Key")
                    assert key is not None
                    object_keys.append(key)

            if object_keys:
                self.app.call_from_thread(self.app.notify, f"Deleting {len(object_keys)} objects in {bucket_name}...", timeout=5)
                batch_size = 1000
                for i in range(0, len(object_keys), batch_size):
                    delete_dict: DeleteTypeDef = {
                        "Objects": [{"Key": key} for key in object_keys[i:i + batch_size]],
                        "Quiet": True,
                    }
                    s3.delete_objects(Bucket=bucket_name, Delete=delete_dict)

            s3.delete_bucket(Bucket=bucket_name)
            self.app.call_from_thread(self.app.notify, f"✅ Deleted bucket: {bucket_name}")
            self.app.call_from_thread(self.load_buckets)
        except Exception as e:
            self.app.call_from_thread(self.app.notify, f"❌ Delete failed: {e}", severity="error")

    async def on_list_view_selected(self, event: ListView.Selected):
        bucket = event.item.name
        await self.app.push_screen(ObjectBrowserTreeScreen(bucket, self.profile_name))

    @work
    async def action_delete(self):
        lv = self.query_one("#buckets", ListView)
        item = getattr(lv, "highlighted_child", None)
        if not item:
            self.app.notify("No bucket selected", severity="warning")
            return

        bucket_name = item.name
        result = await self.app.push_screen_wait(ConfirmDeleteScreen(bucket=bucket_name, bucket_delete=True))
        if result is True:
            self.delete_bucket(bucket_name)

    async def action_back(self):
        await self.app.pop_screen()


class ObjectBrowserTreeScreen(Screen):
    app: "S3Browser" # type: ignore[assignment]

    BINDINGS = [
        ("b", "back", "Back"),
        ("d", "delete", "Delete"),
        ("w", "download", "Download"),
        ("r", "refresh", "Refresh"),
        ("p", "preview", "Quick Look"),
        ("s", "share", "Share Link"),
        ("u", "upload", "Upload"),
    ]

    CSS = """
    #tree-container { width: 2fr; height: 100%; border-right: solid $primary; }
    #info-dock { width: 1fr; height: 100%; padding: 1; background: $surface-darken-1; }
    #info-title { text-align: center; text-style: bold; border-bottom: solid $secondary; padding-bottom: 1; }
    """

    def __init__(self, bucket, profile_name, **kwargs):
        super().__init__(**kwargs)
        self.bucket = bucket
        self.profile_name = profile_name
        self.loaded_nodes = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                Static(f"Bucket: {self.bucket} (Profile: {self.profile_name})", classes="title"),
                Tree(f"📦 {self.bucket}", id="object-tree"),
                id="tree-container"
            ),
            Vertical(
                Static("Select an object", id="info-title"),
                Markdown("", id="info-details"),
                id="info-dock"
            )
        )
        yield Footer()

    def on_mount(self):
        tree = self.query_one("#object-tree", Tree)
        tree.show_root = False
        self.load_node_worker(tree.root, "")

    @work(thread=True)
    def load_node_worker(self, node: TreeNode, prefix: str) -> None:
        s3 = self.app.s3
        assert s3 is not None

        paginator = s3.get_paginator("list_objects_v2")
        items_to_add: list[dict] = []
        is_empty = True

        try:
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
                for p in page.get("CommonPrefixes", []):
                    folder_prefix = p.get("Prefix")
                    assert folder_prefix is not None
                    is_empty = False
                    items_to_add.append({"type": "prefix", "key": folder_prefix})

                for o in page.get("Contents", []):
                    key = o.get("Key")
                    assert key is not None
                    is_empty = False
                    items_to_add.append({"type": "object", "key": key, "object_reference": o})

            self.app.call_from_thread(
                self.populate_node, node, prefix, items_to_add, is_empty
            )

        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"Error listing objects: {e}", severity="error"
            )


    def populate_node(self, node: TreeNode, prefix: str, items: list[dict], is_empty: bool):
        if is_empty and not node.children:
            node.add_leaf("(empty)", data={"type": "empty", "key": ""})
            return

        for item in items:
            key = item["key"]
            if item["type"] == "prefix":
                node.add(f"📁 {key[len(prefix):].rstrip('/')}", data=item)
            else:
                node.add_leaf(f"📄 {key[len(prefix):]}", data=item)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded):
        node = event.node
        if node.data and node.data.get("type") == "prefix":
            if id(node) not in self.loaded_nodes:
                self.loaded_nodes.add(id(node))
                self.load_node_worker(node, node.data["key"])

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted):
        node = event.node
        if not node.data:
            return
        key = node.data["key"]
        self.query_one("#info-title", Static).update(key)
        info_details = self.query_one("#info-details", Markdown)
        if node.data.get("type") == "object":
            metadata = node.data["object_reference"]
            self.display_metadata(metadata)
        elif node.data.get("type") == "prefix":
            info_details.update("\nExpand to see contents.")
        else:
            info_details.update("")

    def display_metadata(self, obj: dict[str, Any]) -> None:
        def format_value(v: Any) -> str:
            if isinstance(v, int):
                return (
                    f"{v/(1024**2):.2f} MB"
                    if v >= 1024**2 else
                    f"{v/1024:.2f} KB"
                    if v >= 1024 else
                    f"{v} B"
                )
            if isinstance(v, datetime.datetime):
                return v.isoformat()
            if isinstance(v, bytes):
                try:
                    return v.decode("utf-8", errors="replace")
                except Exception:
                    return repr(v)
            if isinstance(v, list):
                return ", ".join(format_value(x) for x in v)
            if isinstance(v, dict):
                lines = []
                for kk, vv in v.items():
                    if vv not in (None, {}, [], ""):
                        lines.append(f"    {kk}: {format_value(vv)}")
                return "\n".join(lines)
            return str(v)

        markdown_lines: list[str] = []

        for k, v in obj.items():
            if k == "Key":
                continue
            if v in (None, {}, [], ""):
                continue

            if k == "ETag" and isinstance(v, str):
                val = v.strip('"')
            else:
                val = v

            formatted = format_value(val)
            if "\n" in formatted:
                markdown_lines.append(f"**{k}:**\n{formatted}")
            else:
                markdown_lines.append(f"**{k}:** {formatted}")

        markdown = "  \n".join(markdown_lines) if markdown_lines else "_No metadata available_"
        self.query_one("#info-details", Markdown).update(markdown)

    async def action_preview(self):
        node = self.query_one("#object-tree", Tree).cursor_node
        if node and node.data and node.data.get("type") == "object":
            await self.app.push_screen(FilePreviewScreen(self.bucket, node.data['key']))

    async def action_download(self):
        node = self.query_one("#object-tree", Tree).cursor_node
        if node and node.data and node.data.get("type") == "object":
            await self.app.push_screen(DownloadScreen(self.bucket, node.data['key']))

    @work
    async def action_upload(self):
        if not (local_path := await self.app.push_screen_wait(FileSelectionScreen())):
            return
        self._upload(local_path)

    @work(thread=True)
    def _upload(self, local_path):
        bucket = self.bucket
        s3 = self.app.s3
        assert s3 is not None

        tree = self.query_one("#object-tree", Tree)
        node = tree.cursor_node
        prefix = ""

        if node and node.data and node.data.get("type") == "prefix":
            prefix = node.data["key"]

        try:
            if os.path.isfile(local_path):
                filename = os.path.basename(local_path)
                key = f"{prefix}{filename}"
                s3.upload_file(local_path, bucket, key)
            else:
                base = os.path.basename(local_path)

                for root, _, files in os.walk(local_path):
                    for filename in files:
                        full = os.path.join(root, filename)
                        relative = os.path.relpath(full, local_path)
                        key = f"{prefix}{base}/{relative}"

                        s3.upload_file(full, bucket, key)

            self.app.call_from_thread(self.app.notify, "Upload complete.")
            self.app.call_from_thread(self.action_refresh)

        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"Upload failed: {e}", severity="error"
            )

    async def action_share(self):
        node = self.query_one("#object-tree", Tree).cursor_node
        if node and node.data and node.data.get("type") == "object":
            s3 = self.app.s3
            assert s3 is not None
            try:
                url = s3.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket, 'Key': node.data['key']},
                    ExpiresIn=3600
                )
                await self.app.push_screen(ModalMessageScreen(f"Generated URL (Valid 1h):\n\n{url}"))
            except Exception as e:
                self.app.notify(f"Error generating link: {e}", severity="error")

    @work
    async def action_delete(self):
        tree = self.query_one("#object-tree", Tree)
        node = tree.cursor_node
        if not node or not node.data or node.data.get("type") in ["empty", "error"]:
            return

        node_type = node.data.get("type")
        key = node.data.get("key", "")

        if node_type == "object":
            screen = ConfirmDeleteScreen(bucket=self.bucket, key=key)
        elif node_type == "prefix":
            screen = ConfirmDeleteScreen(bucket=self.bucket, prefix=key)
        else:
            return

        confirmed = await self.app.push_screen_wait(screen)
        if confirmed:
            self.delete_object(key, node_type, node)

    @work(thread=True)
    def delete_object(self, key: str, node_type: str, node: TreeNode):
        s3 = self.app.s3
        assert s3 is not None
        try:
            if node_type == "prefix":
                objects_to_delete = []
                paginator = s3.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=self.bucket, Prefix=key):
                    for obj in page.get("Contents", []):
                        obj_key = obj.get("Key")
                        assert obj_key is not None
                        objects_to_delete.append(obj_key)
                if objects_to_delete:
                    batch_size = 1000
                    for i in range(0, len(objects_to_delete), batch_size):
                        delete_dict: DeleteTypeDef = {
                            "Objects": [{"Key": key} for key in objects_to_delete[i:i + batch_size]],
                            "Quiet": True,
                        }
                        s3.delete_objects(Bucket=self.bucket, Delete=delete_dict)
                    msg = f"✅ Deleted folder: {key} ({len(objects_to_delete)} objects)"
            else:
                s3.delete_object(Bucket=self.bucket, Key=key)
                msg = f"✅ Deleted object: {key}"
            self.app.call_from_thread(self.app.notify, msg)
            self.app.call_from_thread(self.delete_node_and_refresh, node)
        except Exception as e:
            self.app.call_from_thread(self.app.notify, f"❌ Delete failed: {e}", severity="error")

    def delete_node_and_refresh(self, node: TreeNode):
        parent = node.parent
        node.remove()
        if parent and parent.data and parent.data.get("type") == "prefix" and len(list(parent.children)) == 0:
            parent.add_leaf("(empty)", data={"type": "empty", "key": ""})

    async def action_refresh(self):
        tree = self.query_one("#object-tree", Tree)
        node_to_reload = tree.root
        self.loaded_nodes.discard(id(node_to_reload))
        node_to_reload.remove_children()
        self.load_node_worker(node_to_reload, "")
        self.app.notify(f"Refreshed: {self.bucket}")

    async def action_back(self):
        await self.app.pop_screen()

class FileSelectionScreen(ModalScreen):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("s", "select", "Select"),
    ]

    def __init__(self) -> None:
        super().__init__()

    def compose(self):
        yield Header()
        yield Footer()
        with Container():
            yield Label("Select a file to upload", id="title", classes="p-2 text-bold")
            yield DirectoryTree(os.path.abspath(os.sep), id="file-tree")

    def action_cancel(self):
        self.dismiss(None)

    def action_select(self):
        tree = self.query_one("#file-tree", DirectoryTree)
        node = tree.cursor_node
        if not node or not node.data:
            return

        path = node.data.path
        self.dismiss(path)

class ModalMessageScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        yield Static(self.text, classes="modal_text")
        yield Static("\nPress ESC to close.", classes="hint")

    async def action_close(self):
        await self.app.pop_screen()


class ConfirmDeleteScreen(ModalScreen[bool]):
    app: "S3Browser"  # type: ignore[assignment]

    CSS = """
    ConfirmDeleteScreen {
        width: 50%;
        height: 50%;
        align: center middle;
    }
    Markdown {
        width: auto;
    }
    """

    BINDINGS = [
        ("y", "yes", "Yes (Delete)"),
        ("n", "cancel", "No (Cancel)"),
        ("d", "dry", "Dry Run")
    ]

    def __init__(self, bucket: str, key: str | None = None, prefix: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.bucket = bucket
        self.prefix = prefix
        self.key = key
        self.objects_to_delete: list[str] = []

    def compose(self) -> ComposeResult:
        yield Markdown(None)

    def on_mount(self):
        self.update_markdown()

    @work(thread=True)
    def update_markdown(self):
        markdown_widget = self.query_one(Markdown)
        try:
            s3 = self.app.s3
            assert s3 is not None
            paginator = s3.get_paginator("list_objects_v2")
            self.objects_to_delete = []

            if self.prefix:
                for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                    self.objects_to_delete.extend(
                        cast(str, obj.get("Key")) for obj in page.get("Contents", [])
                    )
                count_msg = "No objects found." if not self.objects_to_delete else f"{len(self.objects_to_delete)} object(s) will be deleted."

            if self.key:
                markdown_text = (
                    f"# ⚠️ Delete Object\n\n"
                    f"**Bucket:** `{self.bucket}`  \n"
                    f"**Object:** `{self.key}`\n\n"
                    "This action will permanently delete the object.\n\n"
                    "---\n\n"
                    "Press **y** to confirm, **n** to cancel."
                )
            elif self.prefix != "":
                markdown_text = (
                    f"# ⚠️ Delete Objects\n\n"
                    f"**Bucket:** `{self.bucket}`  \n"
                    f"**Prefix:** `{self.prefix}`\n\n"
                    f"{count_msg}\n\n"
                    f"This action will permanently delete all objects located under `{self.prefix}`.\n\n"
                    "---\n\n"
                    "Press **y** to confirm, **n** to cancel, or **d** for dry run."
                )
            elif self.bucket_delete:
                markdown_text = (
                    f"# ⚠️ Delete Bucket\n\n"
                    f"**Bucket:** `{self.bucket}`\n\n"
                    f"{count_msg}\n\n"
                    "This action will permanently delete the bucket and all its contents.\n\n"
                    "---\n\n"
                    "Press **y** to confirm, **n** to cancel, or **d** for dry run."
                )

            self.app.call_from_thread(markdown_widget.update, markdown_text)

        except Exception as e:
            self.app.call_from_thread(self.app.notify, f"Error counting objects: {e}", severity="error")
            self.app.call_from_thread(markdown_widget.update, f"Error: {e}")

    async def action_yes(self):
        self.dismiss(True)

    async def action_dry(self):
        preview = "\n".join(self.objects_to_delete)
        await self.app.push_screen(ModalMessageScreen(f"[DRY RUN]\nWould delete {len(self.objects_to_delete)} objects:\n{preview}"))
        self.dismiss(False)

    async def action_cancel(self):
        self.dismiss(False)

if __name__ == "__main__":
    S3Browser().run()
