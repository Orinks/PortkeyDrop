"""Main application window for Portkey Drop."""

from __future__ import annotations

import logging
import os
from pathlib import Path, PurePosixPath

import wx

from portkeydrop.dialogs.properties import PropertiesDialog
from portkeydrop.dialogs.quick_connect import QuickConnectDialog
from portkeydrop.dialogs.settings import SettingsDialog
from portkeydrop.dialogs.site_manager import SiteManagerDialog
from portkeydrop.dialogs.transfer import (
    TransferManager,
    create_transfer_dialog,
)
from portkeydrop.local_files import (
    delete_local,
    list_local_dir,
    mkdir_local,
    parent_local,
    rename_local,
)
from portkeydrop.protocols import ConnectionInfo, Protocol, RemoteFile, create_client
from portkeydrop.settings import load_settings, save_settings
from portkeydrop.sites import Site, SiteManager

logger = logging.getLogger(__name__)

# Menu IDs
ID_CONNECT = wx.NewIdRef()
ID_DISCONNECT = wx.NewIdRef()
ID_SITE_MANAGER = wx.NewIdRef()
ID_QUICK_CONNECT = wx.NewIdRef()
ID_UPLOAD = wx.NewIdRef()
ID_DOWNLOAD = wx.NewIdRef()
ID_REFRESH = wx.NewIdRef()
ID_SHOW_HIDDEN = wx.NewIdRef()
ID_SORT_NAME = wx.NewIdRef()
ID_SORT_SIZE = wx.NewIdRef()
ID_SORT_TYPE = wx.NewIdRef()
ID_SORT_MODIFIED = wx.NewIdRef()
ID_PROPERTIES = wx.NewIdRef()
ID_TRANSFER_QUEUE = wx.NewIdRef()
ID_TRANSFER = wx.NewIdRef()
ID_DELETE = wx.NewIdRef()
ID_RENAME = wx.NewIdRef()
ID_MKDIR = wx.NewIdRef()
ID_PARENT_DIR = wx.NewIdRef()
ID_HOME_DIR = wx.NewIdRef()
ID_FILTER = wx.NewIdRef()
ID_SAVE_CONNECTION = wx.NewIdRef()
ID_SETTINGS = wx.NewIdRef()


class MainFrame(wx.Frame):
    """Main application window with dual-pane file browser."""

    def __init__(self) -> None:
        super().__init__(None, title="Portkey Drop", size=(1000, 600))
        self.SetName("Portkey Drop Main Window")

        self._client = None
        self._remote_home = "/"
        self._remote_files: list[RemoteFile] = []
        self._local_files: list[RemoteFile] = []
        self._settings = load_settings()
        self._site_manager = SiteManager()
        self._transfer_manager = TransferManager(notify_window=self)
        self._remote_filter_text = ""
        self._local_filter_text = ""
        self._local_cwd = str(Path.home())

        self._build_menu()
        self._build_toolbar()
        self._build_dual_pane()
        self._build_status_bar()
        self._bind_events()
        self._update_title()
        self._refresh_local_files()

    def _build_menu(self) -> None:
        menubar = wx.MenuBar()

        # File menu
        file_menu = wx.Menu()
        file_menu.Append(ID_CONNECT, "&Connect\tCtrl+Enter", "Connect to server")
        file_menu.Append(ID_DISCONNECT, "&Disconnect\tCtrl+Q", "Disconnect from server")
        file_menu.AppendSeparator()
        file_menu.Append(ID_SETTINGS, "Se&ttings...", "Application settings")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4", "Exit application")
        menubar.Append(file_menu, "&File")

        # Sites menu
        sites_menu = wx.Menu()
        sites_menu.Append(ID_SITE_MANAGER, "&Site Manager...\tCtrl+S", "Manage saved sites")
        sites_menu.Append(ID_QUICK_CONNECT, "&Quick Connect...\tCtrl+N", "Quick connect to server")
        sites_menu.AppendSeparator()
        sites_menu.Append(
            ID_SAVE_CONNECTION, "Sa&ve Current Connection...", "Save active connection as a site"
        )
        menubar.Append(sites_menu, "S&ites")

        # Transfer menu
        transfer_menu = wx.Menu()
        transfer_menu.Append(
            ID_TRANSFER, "&Transfer\tCtrl+T", "Upload or download based on active pane"
        )
        transfer_menu.Append(ID_UPLOAD, "&Upload\tCtrl+U", "Upload selected local file(s)")
        transfer_menu.Append(ID_DOWNLOAD, "&Download\tCtrl+D", "Download selected remote file(s)")
        transfer_menu.AppendSeparator()
        transfer_menu.Append(
            ID_TRANSFER_QUEUE, "Transfer &Queue...\tCtrl+Shift+T", "Show transfer queue"
        )
        menubar.Append(transfer_menu, "&Transfer")

        # View menu
        view_menu = wx.Menu()
        view_menu.Append(ID_REFRESH, "&Refresh\tCtrl+R", "Refresh file list")
        view_menu.Append(ID_HOME_DIR, "&Home Directory\tCtrl+H", "Go to home directory")
        view_menu.AppendCheckItem(ID_SHOW_HIDDEN, "Show &Hidden Files", "Toggle hidden files")
        view_menu.Check(ID_SHOW_HIDDEN, self._settings.display.show_hidden_files)
        view_menu.AppendSeparator()
        sort_menu = wx.Menu()
        sort_menu.AppendRadioItem(ID_SORT_NAME, "By &Name")
        sort_menu.AppendRadioItem(ID_SORT_SIZE, "By &Size")
        sort_menu.AppendRadioItem(ID_SORT_TYPE, "By &Type")
        sort_menu.AppendRadioItem(ID_SORT_MODIFIED, "By &Modified")
        view_menu.AppendSubMenu(sort_menu, "&Sort By")
        view_menu.AppendSeparator()
        view_menu.Append(ID_FILTER, "&Filter...\tCtrl+F", "Filter file list")
        menubar.Append(view_menu, "&View")

        # Edit menu (for file operations)
        edit_menu = wx.Menu()
        edit_menu.Append(ID_DELETE, "De&lete\tDelete", "Delete selected file")
        edit_menu.Append(ID_RENAME, "&Rename\tF2", "Rename selected file")
        edit_menu.Append(ID_MKDIR, "&New Directory...\tCtrl+Shift+N", "Create new directory")
        edit_menu.AppendSeparator()
        edit_menu.Append(ID_PROPERTIES, "P&roperties...\tCtrl+I", "File properties")
        menubar.Append(edit_menu, "&Edit")

        # Help menu
        help_menu = wx.Menu()
        help_menu.Append(wx.ID_ABOUT, "&About", "About Portkey Drop")
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)

    def _build_toolbar(self) -> None:
        toolbar_panel = wx.Panel(self)
        toolbar_panel.SetName("Quick Connect Toolbar")
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        lbl = wx.StaticText(toolbar_panel, label="Protocol:")
        self.tb_protocol = wx.Choice(toolbar_panel, choices=["sftp", "ftp", "ftps"])
        self.tb_protocol.SetSelection(0)
        self.tb_protocol.SetName("Protocol")
        sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        sizer.Add(self.tb_protocol, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        lbl = wx.StaticText(toolbar_panel, label="Host:")
        self.tb_host = wx.TextCtrl(toolbar_panel, size=(150, -1))
        self.tb_host.SetName("Host")
        sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tb_host, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        lbl = wx.StaticText(toolbar_panel, label="Port:")
        self.tb_port = wx.TextCtrl(toolbar_panel, value="22", size=(50, -1))
        self.tb_port.SetName("Port")
        sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tb_port, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        lbl = wx.StaticText(toolbar_panel, label="User:")
        self.tb_username = wx.TextCtrl(toolbar_panel, size=(100, -1))
        self.tb_username.SetName("Username")
        sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tb_username, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        lbl = wx.StaticText(toolbar_panel, label="Password:")
        self.tb_password = wx.TextCtrl(toolbar_panel, size=(100, -1), style=wx.TE_PASSWORD)
        self.tb_password.SetName("Password")
        sizer.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tb_password, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        self.tb_connect_btn = wx.Button(toolbar_panel, label="&Connect")
        self.tb_connect_btn.SetName("Connect")
        sizer.Add(self.tb_connect_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)

        toolbar_panel.SetSizer(sizer)
        self._toolbar_panel = toolbar_panel

        # Update port on protocol change
        self.tb_protocol.Bind(wx.EVT_CHOICE, self._on_toolbar_protocol_change)

    def _build_dual_pane(self) -> None:
        pane_container = wx.Panel(self)

        # --- Local pane (left) ---
        local_panel = wx.Panel(pane_container)
        local_sizer = wx.BoxSizer(wx.VERTICAL)

        local_label = wx.StaticText(local_panel, label="Local Files")
        local_sizer.Add(local_label, 0, wx.LEFT | wx.TOP, 4)

        self.local_path_bar = wx.TextCtrl(
            local_panel, value=self._local_cwd, style=wx.TE_PROCESS_ENTER
        )
        self.local_path_bar.SetName("Local Path")
        local_sizer.Add(self.local_path_bar, 0, wx.EXPAND | wx.ALL, 2)

        self.local_file_list = wx.ListCtrl(local_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.local_file_list.SetName("Local Files")
        self.local_file_list.InsertColumn(0, "Name", width=200)
        self.local_file_list.InsertColumn(1, "Size", width=80)
        self.local_file_list.InsertColumn(2, "Type", width=70)
        self.local_file_list.InsertColumn(3, "Modified", width=130)
        self.local_file_list.InsertColumn(4, "Permissions", width=100)
        local_sizer.Add(self.local_file_list, 1, wx.EXPAND)
        local_panel.SetSizer(local_sizer)

        # --- Remote pane (right) ---
        remote_panel = wx.Panel(pane_container)
        remote_sizer = wx.BoxSizer(wx.VERTICAL)

        remote_label = wx.StaticText(remote_panel, label="Remote Files")
        remote_sizer.Add(remote_label, 0, wx.LEFT | wx.TOP, 4)

        self.remote_path_bar = wx.TextCtrl(remote_panel, value="/", style=wx.TE_PROCESS_ENTER)
        self.remote_path_bar.SetName("Remote Path")
        remote_sizer.Add(self.remote_path_bar, 0, wx.EXPAND | wx.ALL, 2)

        self.remote_file_list = wx.ListCtrl(remote_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.remote_file_list.SetName("Remote Files")
        self.remote_file_list.InsertColumn(0, "Name", width=200)
        self.remote_file_list.InsertColumn(1, "Size", width=80)
        self.remote_file_list.InsertColumn(2, "Type", width=70)
        self.remote_file_list.InsertColumn(3, "Modified", width=130)
        self.remote_file_list.InsertColumn(4, "Permissions", width=100)
        remote_sizer.Add(self.remote_file_list, 1, wx.EXPAND)
        remote_panel.SetSizer(remote_sizer)

        # Side-by-side layout
        h_sizer = wx.BoxSizer(wx.HORIZONTAL)
        h_sizer.Add(local_panel, 1, wx.EXPAND | wx.ALL, 2)
        h_sizer.Add(remote_panel, 1, wx.EXPAND | wx.ALL, 2)
        pane_container.SetSizer(h_sizer)

        self._pane_container = pane_container

        # For backward compat: file_list points to remote
        self.file_list = self.remote_file_list

        # Main layout
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self._toolbar_panel, 0, wx.EXPAND)
        main_sizer.Add(pane_container, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

    def _build_status_bar(self) -> None:
        self.status_bar = self.CreateStatusBar(2)
        self.status_bar.SetStatusWidths([-1, -2])
        self._update_status("Disconnected", "")

    def _update_status(self, state: str, path: str) -> None:
        self.status_bar.SetStatusText(state, 0)
        self.status_bar.SetStatusText(path, 1)

    def _update_title(self) -> None:
        if self._client and self._client.connected:
            self.SetTitle(f"Portkey Drop - {self._client.cwd}")
        else:
            self.SetTitle("Portkey Drop")

    def _is_local_focused(self) -> bool:
        """Return True if the local pane currently has focus."""
        focused = self.FindFocus()
        return focused is self.local_file_list

    def _is_remote_focused(self) -> bool:
        """Return True if the remote pane currently has focus."""
        focused = self.FindFocus()
        return focused is self.remote_file_list

    def _get_focused_file_list(self) -> wx.ListCtrl | None:
        """Return whichever file list has focus, or None."""
        focused = self.FindFocus()
        if focused is self.local_file_list:
            return self.local_file_list
        if focused is self.remote_file_list:
            return self.remote_file_list
        return None

    def _bind_events(self) -> None:
        # Menu events
        self.Bind(wx.EVT_MENU, self._on_connect_toolbar, id=ID_CONNECT)
        self.Bind(wx.EVT_MENU, self._on_disconnect, id=ID_DISCONNECT)
        self.Bind(wx.EVT_MENU, self._on_exit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self._on_site_manager, id=ID_SITE_MANAGER)
        self.Bind(wx.EVT_MENU, self._on_quick_connect, id=ID_QUICK_CONNECT)
        self.Bind(wx.EVT_MENU, self._on_save_connection, id=ID_SAVE_CONNECTION)
        self.Bind(wx.EVT_MENU, self._on_transfer, id=ID_TRANSFER)
        self.Bind(wx.EVT_MENU, self._on_upload, id=ID_UPLOAD)
        self.Bind(wx.EVT_MENU, self._on_download, id=ID_DOWNLOAD)
        self.Bind(wx.EVT_MENU, self._on_refresh, id=ID_REFRESH)
        self.Bind(wx.EVT_MENU, self._on_home_dir, id=ID_HOME_DIR)
        self.Bind(wx.EVT_MENU, self._on_toggle_hidden, id=ID_SHOW_HIDDEN)
        self.Bind(wx.EVT_MENU, lambda e: self._sort_by("name"), id=ID_SORT_NAME)
        self.Bind(wx.EVT_MENU, lambda e: self._sort_by("size"), id=ID_SORT_SIZE)
        self.Bind(wx.EVT_MENU, lambda e: self._sort_by("type"), id=ID_SORT_TYPE)
        self.Bind(wx.EVT_MENU, lambda e: self._sort_by("modified"), id=ID_SORT_MODIFIED)
        self.Bind(wx.EVT_MENU, self._on_filter, id=ID_FILTER)
        self.Bind(wx.EVT_MENU, self._on_delete, id=ID_DELETE)
        self.Bind(wx.EVT_MENU, self._on_rename, id=ID_RENAME)
        self.Bind(wx.EVT_MENU, self._on_mkdir, id=ID_MKDIR)
        self.Bind(wx.EVT_MENU, self._on_properties, id=ID_PROPERTIES)
        self.Bind(wx.EVT_MENU, self._on_transfer_queue, id=ID_TRANSFER_QUEUE)
        self.Bind(wx.EVT_MENU, self._on_settings, id=ID_SETTINGS)
        self.Bind(wx.EVT_MENU, self._on_about, id=wx.ID_ABOUT)

        # Toolbar connect button
        self.tb_connect_btn.Bind(wx.EVT_BUTTON, self._on_connect_toolbar)

        # File list events - remote
        self.remote_file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_remote_item_activated)
        self.remote_file_list.Bind(wx.EVT_KEY_DOWN, self._on_remote_file_list_key)
        self.remote_file_list.Bind(wx.EVT_CONTEXT_MENU, self._on_remote_context_menu)

        # File list events - local
        self.local_file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_local_item_activated)
        self.local_file_list.Bind(wx.EVT_KEY_DOWN, self._on_local_file_list_key)
        self.local_file_list.Bind(wx.EVT_CONTEXT_MENU, self._on_local_context_menu)

        # Path bar enter
        self.local_path_bar.Bind(wx.EVT_TEXT_ENTER, self._on_local_path_enter)
        self.remote_path_bar.Bind(wx.EVT_TEXT_ENTER, self._on_remote_path_enter)

    def _on_toolbar_protocol_change(self, event: wx.CommandEvent) -> None:
        proto = self.tb_protocol.GetStringSelection()
        defaults = {"sftp": "22", "ftp": "21", "ftps": "990"}
        self.tb_port.SetValue(defaults.get(proto, "22"))

    # --- Connection ---

    def _on_connect_toolbar(self, event: wx.CommandEvent) -> None:
        proto_map = {"sftp": Protocol.SFTP, "ftp": Protocol.FTP, "ftps": Protocol.FTPS}
        proto_str = self.tb_protocol.GetStringSelection()
        port_str = self.tb_port.GetValue().strip()
        info = ConnectionInfo(
            protocol=proto_map.get(proto_str, Protocol.SFTP),
            host=self.tb_host.GetValue().strip(),
            port=int(port_str) if port_str else 0,
            username=self.tb_username.GetValue().strip(),
            password=self.tb_password.GetValue(),
        )
        self._do_connect(info)

    def _on_quick_connect(self, event: wx.CommandEvent) -> None:
        dlg = QuickConnectDialog(self)
        info = None
        if dlg.ShowModal() == wx.ID_OK:
            info = dlg.get_connection_info()
        dlg.Destroy()
        if info:
            self._do_connect(info)

    def _on_site_manager(self, event: wx.CommandEvent) -> None:
        dlg = SiteManagerDialog(self, self._site_manager)
        result = dlg.ShowModal()
        info = None
        if result == wx.ID_OK and dlg.connect_requested and dlg.selected_site:
            info = dlg.selected_site.to_connection_info()
        dlg.Destroy()
        if info:
            self._do_connect(info)

    def _on_save_connection(self, event: wx.CommandEvent) -> None:
        if not self._client or not self._client.connected:
            wx.MessageBox(
                "Not connected. Connect to a server first.",
                "Save Connection",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        # Build site from toolbar fields
        proto_str = self.tb_protocol.GetStringSelection()
        host = self.tb_host.GetValue().strip()
        port_str = self.tb_port.GetValue().strip()
        username = self.tb_username.GetValue().strip()
        password = self.tb_password.GetValue()
        default_name = f"{username}@{host}" if username else host
        dlg = wx.TextEntryDialog(self, "Site name:", "Save Connection", default_name)
        dlg.SetName("Save Connection")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip() or default_name
            site = Site(
                name=name,
                protocol=proto_str,
                host=host,
                port=int(port_str) if port_str else 0,
                username=username,
                password=password,
                initial_dir=self._client.cwd,
            )
            self._site_manager.add(site)
            self._announce(f"Site '{name}' saved")
        dlg.Destroy()

    def _do_connect(self, info: ConnectionInfo) -> None:
        if not info.host:
            wx.MessageBox("Please enter a host.", "Error", wx.OK | wx.ICON_ERROR, self)
            return
        if not info.username:
            wx.MessageBox("Please enter a username.", "Error", wx.OK | wx.ICON_ERROR, self)
            return
        if not info.password:
            wx.MessageBox(
                "Please enter a password.", "Error", wx.OK | wx.ICON_ERROR, self
            )
            return
        self._on_disconnect(None)
        try:
            self._client = create_client(info)
            self._client.connect()
            self._remote_home = self._client.cwd
            self._update_status("Connected", self._client.cwd)
            self._update_title()
            self._announce(f"Connected to {info.host}")
            self._refresh_remote_files()
            self._toolbar_panel.Hide()
            self.GetSizer().Layout()
            self.local_file_list.SetFocus()
        except Exception as e:
            wx.MessageBox(f"Connection failed: {e}", "Error", wx.OK | wx.ICON_ERROR, self)
            self._client = None

    def _on_disconnect(self, event) -> None:
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._remote_files = []
        self.remote_file_list.DeleteAllItems()
        self.remote_path_bar.SetValue("/")
        self._update_status("Disconnected", "")
        self._update_title()
        if not self._toolbar_panel.IsShown():
            self._toolbar_panel.Show()
            self.GetSizer().Layout()
            self.tb_host.SetFocus()

    def _on_exit(self, event: wx.CommandEvent) -> None:
        self.Close()

    # --- Path bar events ---

    def _on_local_path_enter(self, event: wx.CommandEvent) -> None:
        path = self.local_path_bar.GetValue().strip()
        if path and Path(path).is_dir():
            self._local_cwd = str(Path(path).resolve())
            self._refresh_local_files()
        else:
            wx.MessageBox("Invalid directory path.", "Error", wx.OK | wx.ICON_ERROR, self)

    def _on_remote_path_enter(self, event: wx.CommandEvent) -> None:
        if not self._client or not self._client.connected:
            return
        path = self.remote_path_bar.GetValue().strip()
        if path:
            try:
                self._client.chdir(path)
                self._refresh_remote_files()
            except Exception as e:
                wx.MessageBox(f"Failed to navigate: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    # --- Refresh ---

    def _on_home_dir(self, event: wx.CommandEvent) -> None:
        """Navigate to home directory in the focused pane."""
        if self._is_local_focused() or not self._client:
            self._local_cwd = str(Path.home())
            self._refresh_local_files()
            self._announce(f"Home: {self._local_cwd}")
        elif self._client and self._client.connected:
            self._announce("Going home...")
            wx.CallAfter(self._navigate_remote_home)

    def _navigate_remote_home(self) -> None:
        """Navigate to remote home in a non-blocking way."""
        try:
            self._client.chdir(self._remote_home)
            self._refresh_remote_files()
            self._announce(f"Home: {self._client.cwd}")
        except Exception as e:
            wx.MessageBox(
                f"Failed to go home: {e}", "Error", wx.OK | wx.ICON_ERROR, self
            )

    def _on_refresh(self, event: wx.CommandEvent) -> None:
        if self._is_local_focused():
            self._refresh_local_files()
        else:
            self._refresh_remote_files()

    def _refresh_remote_files(self) -> None:
        if not self._client or not self._client.connected:
            return
        try:
            self._update_status("Loading...", self._client.cwd)
            wx.Yield()
            self._remote_files = self._client.list_dir()
            self._apply_sort(self._remote_files)
            # Insert ".." entry at the top to navigate to parent
            if self._client.cwd != "/":
                parent_path = str(PurePosixPath(self._client.cwd).parent)
                parent_entry = RemoteFile(name="..", path=parent_path, is_dir=True)
                self._remote_files.insert(0, parent_entry)
            self._populate_file_list(
                self.remote_file_list,
                self._get_visible_files(self._remote_files, self._remote_filter_text),
            )
            self._update_status("Connected", self._client.cwd)
            self.remote_path_bar.SetValue(self._client.cwd)
            self._update_title()
            count = len(self._get_visible_files(self._remote_files, self._remote_filter_text))
            if self._settings.display.announce_file_count:
                self._announce(f"{self._client.cwd}: {count} items")
        except Exception as e:
            self._update_status("Connected", self._client.cwd)
            wx.MessageBox(f"Failed to list directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _refresh_local_files(self) -> None:
        try:
            self._local_files = list_local_dir(self._local_cwd)
            self._apply_sort(self._local_files)
            # Insert ".." entry at the top to navigate to parent
            parent_path = str(Path(self._local_cwd).parent)
            if parent_path != self._local_cwd:
                parent_entry = RemoteFile(name="..", path=parent_path, is_dir=True)
                self._local_files.insert(0, parent_entry)
            self._populate_file_list(
                self.local_file_list,
                self._get_visible_files(self._local_files, self._local_filter_text),
            )
            self.local_path_bar.SetValue(self._local_cwd)
            count = len(self._get_visible_files(self._local_files, self._local_filter_text))
            if self._settings.display.announce_file_count:
                self._announce(f"{self._local_cwd}: {count} items")
        except Exception as e:
            wx.MessageBox(
                f"Failed to list local directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self
            )

    # Keep _refresh_files for backward compat (calls remote refresh)
    def _refresh_files(self) -> None:
        self._refresh_remote_files()

    def _get_visible_files(self, files: list[RemoteFile], filter_text: str) -> list[RemoteFile]:
        if not self._settings.display.show_hidden_files:
            files = [f for f in files if f.name == ".." or not f.name.startswith(".")]
        if filter_text:
            pattern = filter_text.lower()
            files = [f for f in files if pattern in f.name.lower()]
        return files

    def _apply_sort(self, files: list[RemoteFile]) -> None:
        key_map = {
            "name": lambda f: (not f.is_dir, f.name.lower()),
            "size": lambda f: (not f.is_dir, f.size),
            "type": lambda f: (not f.is_dir, "dir" if f.is_dir else Path(f.name).suffix.lower()),
            "modified": lambda f: (not f.is_dir, f.modified or ""),
        }
        key_fn = key_map.get(self._settings.display.sort_by, key_map["name"])
        files.sort(key=key_fn, reverse=not self._settings.display.sort_ascending)

    def _populate_file_list(self, list_ctrl: wx.ListCtrl, files: list[RemoteFile]) -> None:
        list_ctrl.DeleteAllItems()
        for f in files:
            idx = list_ctrl.InsertItem(list_ctrl.GetItemCount(), f.name)
            list_ctrl.SetItem(idx, 1, f.display_size)
            list_ctrl.SetItem(idx, 2, "Directory" if f.is_dir else "File")
            list_ctrl.SetItem(idx, 3, f.display_modified)
            list_ctrl.SetItem(idx, 4, f.permissions)

    def _on_toggle_hidden(self, event: wx.CommandEvent) -> None:
        self._settings.display.show_hidden_files = event.IsChecked()
        self._populate_file_list(
            self.remote_file_list,
            self._get_visible_files(self._remote_files, self._remote_filter_text),
        )
        self._populate_file_list(
            self.local_file_list,
            self._get_visible_files(self._local_files, self._local_filter_text),
        )

    def _sort_by(self, field: str) -> None:
        self._settings.display.sort_by = field
        self._apply_sort(self._remote_files)
        self._apply_sort(self._local_files)
        self._populate_file_list(
            self.remote_file_list,
            self._get_visible_files(self._remote_files, self._remote_filter_text),
        )
        self._populate_file_list(
            self.local_file_list,
            self._get_visible_files(self._local_files, self._local_filter_text),
        )

    def _on_filter(self, event: wx.CommandEvent) -> None:
        if self._is_local_focused():
            dlg = wx.TextEntryDialog(self, "Filter local files:", "Filter", self._local_filter_text)
            dlg.SetName("Filter Files")
            if dlg.ShowModal() == wx.ID_OK:
                self._local_filter_text = dlg.GetValue()
                self._populate_file_list(
                    self.local_file_list,
                    self._get_visible_files(self._local_files, self._local_filter_text),
                )
            dlg.Destroy()
        else:
            dlg = wx.TextEntryDialog(
                self, "Filter remote files:", "Filter", self._remote_filter_text
            )
            dlg.SetName("Filter Files")
            if dlg.ShowModal() == wx.ID_OK:
                self._remote_filter_text = dlg.GetValue()
                self._populate_file_list(
                    self.remote_file_list,
                    self._get_visible_files(self._remote_files, self._remote_filter_text),
                )
            dlg.Destroy()

    # --- Selection helpers ---

    def _get_selected_file_from_list(
        self, list_ctrl: wx.ListCtrl, files: list[RemoteFile], filter_text: str
    ) -> RemoteFile | None:
        idx = list_ctrl.GetFirstSelected()
        if idx == wx.NOT_FOUND:
            return None
        visible = self._get_visible_files(files, filter_text)
        if 0 <= idx < len(visible):
            return visible[idx]
        return None

    def _get_selected_remote_file(self) -> RemoteFile | None:
        return self._get_selected_file_from_list(
            self.remote_file_list, self._remote_files, self._remote_filter_text
        )

    def _get_selected_local_file(self) -> RemoteFile | None:
        return self._get_selected_file_from_list(
            self.local_file_list, self._local_files, self._local_filter_text
        )

    # Keep old name for compat
    def _get_selected_file(self) -> RemoteFile | None:
        return self._get_selected_remote_file()

    # --- Item activation ---

    def _on_remote_item_activated(self, event: wx.ListEvent) -> None:
        f = self._get_selected_remote_file()
        if not f:
            logger.warning("Remote item activated but no file selected (index: %s)", event.GetIndex())
            return
        if not self._client:
            logger.warning("Remote item activated but no client")
            return
        logger.info(
            "Remote item activated: name=%r, is_dir=%s, path=%r",
            f.name, f.is_dir, f.path,
        )
        if f.is_dir:
            try:
                self._announce(f"Opening {f.name}...")
                self._client.chdir(f.path)
                self._refresh_remote_files()
            except Exception as e:
                logger.exception("Failed to open remote directory %s", f.path)
                wx.MessageBox(
                    f"Failed to open directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self
                )
        else:
            self._announce(f"{f.name} detected as file, not directory")
            self._on_download(None)

    def _on_local_item_activated(self, event: wx.ListEvent) -> None:
        f = self._get_selected_local_file()
        if not f:
            return
        if f.is_dir:
            self._local_cwd = f.path
            self._refresh_local_files()
        else:
            # Activate file on local = upload if connected
            if self._client and self._client.connected:
                self._on_upload(None)

    # Keep old name for compat
    def _on_item_activated(self, event: wx.ListEvent) -> None:
        self._on_remote_item_activated(event)

    # --- Keyboard handling ---

    def _on_remote_file_list_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_BACK:
            self._go_remote_parent_dir()
        elif key == wx.WXK_DELETE:
            self._on_delete(None)
        elif key == wx.WXK_F2:
            self._on_rename(None)
        else:
            event.Skip()

    def _on_local_file_list_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_BACK:
            self._go_local_parent_dir()
        elif key == wx.WXK_DELETE:
            self._on_delete(None)
        elif key == wx.WXK_F2:
            self._on_rename(None)
        else:
            event.Skip()

    # Keep old name for compat
    def _on_file_list_key(self, event: wx.KeyEvent) -> None:
        self._on_remote_file_list_key(event)

    def _open_selected_remote_dir(self) -> None:
        """Open the selected remote directory."""
        f = self._get_selected_remote_file()
        if not f or not f.is_dir or not self._client:
            return
        try:
            self._announce(f"Opening {f.name}...")
            self._client.chdir(f.path)
            self._refresh_remote_files()
        except Exception as e:
            wx.MessageBox(
                f"Failed to open directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self
            )

    def _on_remote_context_menu(self, event: wx.ContextMenuEvent) -> None:
        """Show context menu for the remote file list."""
        menu = wx.Menu()
        f = self._get_selected_remote_file()

        item = menu.Append(wx.ID_ANY, "&Download\tCtrl+D")
        self.Bind(wx.EVT_MENU, self._on_download, item)
        if not f or (f.name == ".."):
            item.Enable(False)

        item = menu.Append(wx.ID_ANY, "&Transfer\tCtrl+T")
        self.Bind(wx.EVT_MENU, self._on_transfer, item)
        if not f or (f.name == ".."):
            item.Enable(False)

        menu.AppendSeparator()

        item = menu.Append(wx.ID_ANY, "&Open Folder")
        self.Bind(wx.EVT_MENU, lambda e: self._open_selected_remote_dir(), item)
        if not f or not f.is_dir:
            item.Enable(False)

        item = menu.Append(wx.ID_ANY, "&Home Directory\tCtrl+H")
        self.Bind(wx.EVT_MENU, self._on_home_dir, item)

        menu.AppendSeparator()

        item = menu.Append(wx.ID_ANY, "Re&name\tF2")
        self.Bind(wx.EVT_MENU, self._on_rename, item)
        if not f or f.name == "..":
            item.Enable(False)

        item = menu.Append(wx.ID_ANY, "De&lete\tDelete")
        self.Bind(wx.EVT_MENU, self._on_delete, item)
        if not f or f.name == "..":
            item.Enable(False)

        item = menu.Append(wx.ID_ANY, "&New Directory\tCtrl+Shift+N")
        self.Bind(wx.EVT_MENU, self._on_mkdir, item)

        menu.AppendSeparator()

        item = menu.Append(wx.ID_ANY, "&Refresh\tCtrl+R")
        self.Bind(wx.EVT_MENU, self._on_refresh, item)

        item = menu.Append(wx.ID_ANY, "P&roperties\tCtrl+I")
        self.Bind(wx.EVT_MENU, self._on_properties, item)
        if not f or f.name == "..":
            item.Enable(False)

        self.PopupMenu(menu)
        menu.Destroy()

    def _on_local_context_menu(self, event: wx.ContextMenuEvent) -> None:
        """Show context menu for the local file list."""
        menu = wx.Menu()
        f = self._get_selected_local_file()
        connected = self._client and self._client.connected

        item = menu.Append(wx.ID_ANY, "&Upload\tCtrl+U")
        self.Bind(wx.EVT_MENU, self._on_upload, item)
        if not f or f.name == ".." or not connected:
            item.Enable(False)

        item = menu.Append(wx.ID_ANY, "&Transfer\tCtrl+T")
        self.Bind(wx.EVT_MENU, self._on_transfer, item)
        if not f or f.name == ".." or not connected:
            item.Enable(False)

        menu.AppendSeparator()

        item = menu.Append(wx.ID_ANY, "&Home Directory\tCtrl+H")
        self.Bind(wx.EVT_MENU, self._on_home_dir, item)

        menu.AppendSeparator()

        item = menu.Append(wx.ID_ANY, "Re&name\tF2")
        self.Bind(wx.EVT_MENU, self._on_rename, item)
        if not f or f.name == "..":
            item.Enable(False)

        item = menu.Append(wx.ID_ANY, "De&lete\tDelete")
        self.Bind(wx.EVT_MENU, self._on_delete, item)
        if not f or f.name == "..":
            item.Enable(False)

        item = menu.Append(wx.ID_ANY, "&New Directory\tCtrl+Shift+N")
        self.Bind(wx.EVT_MENU, self._on_mkdir, item)

        menu.AppendSeparator()

        item = menu.Append(wx.ID_ANY, "&Refresh\tCtrl+R")
        self.Bind(wx.EVT_MENU, self._on_refresh, item)

        item = menu.Append(wx.ID_ANY, "P&roperties\tCtrl+I")
        self.Bind(wx.EVT_MENU, self._on_properties, item)
        if not f or f.name == "..":
            item.Enable(False)

        self.PopupMenu(menu)
        menu.Destroy()

    def _go_remote_parent_dir(self) -> None:
        if not self._client or not self._client.connected:
            return
        try:
            self._client.parent_dir()
            self._refresh_remote_files()
        except Exception as e:
            wx.MessageBox(f"Failed to go to parent: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _go_local_parent_dir(self) -> None:
        new_path = str(parent_local(self._local_cwd))
        if new_path != self._local_cwd:
            self._local_cwd = new_path
            self._refresh_local_files()

    # Keep old name for compat
    def _go_parent_dir(self) -> None:
        self._go_remote_parent_dir()

    # --- Transfer operations ---

    def _on_transfer(self, event) -> None:
        """Context-aware transfer: upload from local pane, download from remote pane."""
        if self._is_local_focused():
            self._on_upload(None)
        else:
            self._on_download(None)

    def _on_download(self, event) -> None:
        f = self._get_selected_remote_file()
        if not f or not self._client:
            return
        local_path = os.path.join(self._local_cwd, f.name)
        if f.is_dir:
            if f.name == "..":
                return
            self._transfer_manager.add_recursive_download(self._client, f.path, local_path)
            self._announce(f"Downloading folder {f.name} to {self._local_cwd}")
        else:
            self._transfer_manager.add_download(self._client, f.path, local_path, f.size)
            self._announce(f"Downloading {f.name} to {self._local_cwd}")
        self._show_transfer_queue()

    def _on_upload(self, event) -> None:
        if not self._client or not self._client.connected:
            return
        f = self._get_selected_local_file()
        if not f:
            return
        local_path = f.path
        filename = f.name
        remote_path = f"{self._client.cwd.rstrip('/')}/{filename}"
        if f.is_dir:
            if f.name == "..":
                return
            self._transfer_manager.add_recursive_upload(self._client, local_path, remote_path)
            self._announce(f"Uploading folder {filename}")
        else:
            total = os.path.getsize(local_path)
            self._transfer_manager.add_upload(self._client, local_path, remote_path, total)
            self._announce(f"Uploading {filename}")
        self._show_transfer_queue()

    def _show_transfer_queue(self) -> None:
        """Show the transfer queue as a modeless dialog."""
        if hasattr(self, "_transfer_dlg") and self._transfer_dlg:
            try:
                self._transfer_dlg.Raise()
                return
            except Exception:
                pass
        self._transfer_dlg = create_transfer_dialog(self, self._transfer_manager)
        self._transfer_dlg.Show()

    # --- File operations (context-aware) ---

    def _on_delete(self, event) -> None:
        if self._is_local_focused():
            self._delete_local()
        else:
            self._delete_remote()

    def _delete_remote(self) -> None:
        f = self._get_selected_remote_file()
        if not f or not self._client:
            return
        result = wx.MessageBox(
            f"Delete {f.name}?", "Confirm Delete", wx.YES_NO | wx.ICON_WARNING, self
        )
        if result == wx.YES:
            try:
                if f.is_dir:
                    self._client.rmdir(f.path)
                else:
                    self._client.delete(f.path)
                self._announce(f"Deleted {f.name}")
                self._refresh_remote_files()
            except Exception as e:
                wx.MessageBox(f"Delete failed: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _delete_local(self) -> None:
        f = self._get_selected_local_file()
        if not f:
            return
        result = wx.MessageBox(
            f"Delete {f.name}?", "Confirm Delete", wx.YES_NO | wx.ICON_WARNING, self
        )
        if result == wx.YES:
            try:
                delete_local(f.path)
                self._announce(f"Deleted {f.name}")
                self._refresh_local_files()
            except Exception as e:
                wx.MessageBox(f"Delete failed: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _on_rename(self, event) -> None:
        if self._is_local_focused():
            self._rename_local()
        else:
            self._rename_remote()

    def _rename_remote(self) -> None:
        f = self._get_selected_remote_file()
        if not f or not self._client:
            return
        dlg = wx.TextEntryDialog(self, "New name:", "Rename", f.name)
        dlg.SetName("Rename File")
        if dlg.ShowModal() == wx.ID_OK:
            new_name = dlg.GetValue().strip()
            if new_name and new_name != f.name:
                parent = str(PurePosixPath(f.path).parent)
                new_path = f"{parent.rstrip('/')}/{new_name}"
                try:
                    self._client.rename(f.path, new_path)
                    self._announce(f"Renamed to {new_name}")
                    self._refresh_remote_files()
                except Exception as e:
                    wx.MessageBox(f"Rename failed: {e}", "Error", wx.OK | wx.ICON_ERROR, self)
        dlg.Destroy()

    def _rename_local(self) -> None:
        f = self._get_selected_local_file()
        if not f:
            return
        dlg = wx.TextEntryDialog(self, "New name:", "Rename", f.name)
        dlg.SetName("Rename File")
        if dlg.ShowModal() == wx.ID_OK:
            new_name = dlg.GetValue().strip()
            if new_name and new_name != f.name:
                try:
                    rename_local(f.path, new_name)
                    self._announce(f"Renamed to {new_name}")
                    self._refresh_local_files()
                except Exception as e:
                    wx.MessageBox(f"Rename failed: {e}", "Error", wx.OK | wx.ICON_ERROR, self)
        dlg.Destroy()

    def _on_mkdir(self, event: wx.CommandEvent) -> None:
        if self._is_local_focused():
            self._mkdir_local()
        else:
            self._mkdir_remote()

    def _mkdir_remote(self) -> None:
        if not self._client or not self._client.connected:
            return
        dlg = wx.TextEntryDialog(self, "Directory name:", "New Directory")
        dlg.SetName("New Directory")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                path = f"{self._client.cwd.rstrip('/')}/{name}"
                try:
                    self._client.mkdir(path)
                    self._announce(f"Created directory {name}")
                    self._refresh_remote_files()
                except Exception as e:
                    wx.MessageBox(
                        f"Failed to create directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self
                    )
        dlg.Destroy()

    def _mkdir_local(self) -> None:
        dlg = wx.TextEntryDialog(self, "Directory name:", "New Directory")
        dlg.SetName("New Directory")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                try:
                    mkdir_local(self._local_cwd, name)
                    self._announce(f"Created directory {name}")
                    self._refresh_local_files()
                except Exception as e:
                    wx.MessageBox(
                        f"Failed to create directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self
                    )
        dlg.Destroy()

    def _on_properties(self, event: wx.CommandEvent) -> None:
        if self._is_local_focused():
            f = self._get_selected_local_file()
        else:
            f = self._get_selected_remote_file()
        if not f:
            return
        dlg = PropertiesDialog(self, f)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_transfer_queue(self, event: wx.CommandEvent) -> None:
        self._show_transfer_queue()

    def _on_transfer_update(self, event) -> None:
        pass

    def _on_settings(self, event: wx.CommandEvent) -> None:
        dlg = SettingsDialog(self, self._settings)
        if dlg.ShowModal() == wx.ID_OK:
            self._settings = dlg.get_settings()
            save_settings(self._settings)
            self._populate_file_list(
                self.remote_file_list,
                self._get_visible_files(self._remote_files, self._remote_filter_text),
            )
            self._populate_file_list(
                self.local_file_list,
                self._get_visible_files(self._local_files, self._local_filter_text),
            )
        dlg.Destroy()

    def _on_about(self, event: wx.CommandEvent) -> None:
        info = wx.adv.AboutDialogInfo()
        info.SetName("Portkey Drop")
        info.SetVersion("0.1.0")
        info.SetDescription("Accessible file transfer client for screen reader users")
        wx.adv.AboutBox(info)

    def _announce(self, message: str) -> None:
        """Announce a message for screen readers via status bar."""
        self.status_bar.SetStatusText(message, 0)
        try:
            import prismatoid

            prismatoid.speak(message)
        except Exception:
            pass


class PortkeyDropApp(wx.App):
    """Main wxPython application."""

    def OnInit(self) -> bool:
        frame = MainFrame()
        frame.Show()
        self.SetTopWindow(frame)
        return True
