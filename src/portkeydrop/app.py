"""Main application window for Portkey Drop."""

from __future__ import annotations

import datetime
import logging
import os
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import wx

from portkeydrop import __version__
from portkeydrop.dialogs.properties import PropertiesDialog
from portkeydrop.dialogs.quick_connect import QuickConnectDialog
from portkeydrop.dialogs.settings import SettingsDialog
from portkeydrop.dialogs.import_connections import ImportConnectionsDialog
from portkeydrop.dialogs.site_manager import SiteManagerDialog
from portkeydrop.dialogs.transfer import (
    TransferDirection,
    TransferStatus,
    create_transfer_dialog,
    get_transfer_event_binder,
    load_queue,
    save_queue,
)
from portkeydrop.services.transfer_service import TransferService
from portkeydrop.local_files import (
    delete_local,
    list_local_dir,
    mkdir_local,
    parent_local,
    rename_local,
)
from portkeydrop.migration import (
    get_migration_candidates,
    has_migration_candidates,
    migrate_files,
)
from portkeydrop.portable import get_config_dir, is_portable_mode
from portkeydrop.protocols import ConnectionInfo, HostKeyPolicy, Protocol, RemoteFile, create_client
from portkeydrop.settings import (
    load_settings,
    resolve_startup_local_folder,
    save_settings,
    update_last_local_folder,
)
from portkeydrop.sites import Site, SiteManager
from portkeydrop.screen_reader import ScreenReaderAnnouncer
from portkeydrop.services.updater import (
    ChecksumVerificationError,
    UpdateService,
    apply_update,
    parse_nightly_date,
)
from portkeydrop.ui.dialogs.migration_dialog import MigrationDialog
from portkeydrop.ui.dialogs.update_dialog import UpdateAvailableDialog

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
ID_CHECK_UPDATES = wx.NewIdRef()
ID_IMPORT_CONNECTIONS = wx.NewIdRef()
ID_RETRY_LAST_FAILED = wx.NewIdRef()
ID_SWITCH_PANE_FOCUS = wx.NewIdRef()
ID_FOCUS_ADDRESS_BAR = wx.NewIdRef()
ID_TOGGLE_ACTIVITY_LOG = wx.NewIdRef()
ID_FOCUS_LOCAL_PANE = wx.NewIdRef()
ID_FOCUS_REMOTE_PANE = wx.NewIdRef()
ID_FOCUS_ACTIVITY_LOG_PANE = wx.NewIdRef()


class MainFrame(wx.Frame):
    """Main application window with dual-pane file browser."""

    def __init__(self) -> None:
        super().__init__(None, title="Portkey Drop", size=(1000, 600))

        self._client = None
        self._remote_home = "/"
        self._remote_files: list[RemoteFile] = []
        self._local_files: list[RemoteFile] = []
        self._settings = load_settings()
        self.version = __version__
        # Prefer _build_meta (baked in by PyInstaller CI build), fall back to env var
        try:
            from portkeydrop._build_meta import BUILD_TAG as _baked_build_tag  # type: ignore[import]

            self.build_tag = _baked_build_tag or os.environ.get("PORTKEYDROP_BUILD_TAG")
        except ImportError:
            self.build_tag = os.environ.get("PORTKEYDROP_BUILD_TAG")
        self._auto_update_check_timer: wx.Timer | None = None
        self._site_manager = SiteManager()
        self._transfer_service = TransferService(
            notify_window=self,
            max_workers=self._settings.transfer.concurrent_transfers,
        )
        self._transfer_state_by_id: dict[str, str] = {}
        self._last_failed_transfer: str | None = None
        self._announcer = ScreenReaderAnnouncer()
        self._restore_transfer_queue()
        self._remote_filter_text = ""
        self._local_filter_text = ""
        self._local_cwd = resolve_startup_local_folder(self._settings)
        self._persist_local_folder_setting()

        self._build_menu()
        self._build_toolbar()
        self._build_dual_pane()
        self._build_status_bar()
        self._bind_events()
        self._update_title()
        self._refresh_local_files()
        wx.CallAfter(self._set_initial_focus)
        self._start_auto_update_checks()
        wx.CallAfter(self._check_for_updates_on_startup)

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

        # Edit menu (for file operations)
        edit_menu = wx.Menu()
        edit_menu.Append(ID_DELETE, "De&lete\tDelete", "Delete selected file")
        edit_menu.Append(ID_RENAME, "&Rename\tF2", "Rename selected file")
        edit_menu.Append(ID_MKDIR, "&New Directory...\tCtrl+Shift+N", "Create new directory")
        edit_menu.AppendSeparator()
        edit_menu.Append(ID_PROPERTIES, "P&roperties...\tCtrl+I", "File properties")
        menubar.Append(edit_menu, "&Edit")

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
        view_menu.AppendSeparator()
        self._toggle_log_item = view_menu.Append(
            ID_TOGGLE_ACTIVITY_LOG,
            "Hide &Activity Log",
            "Toggle activity log panel visibility",
        )
        menubar.Append(view_menu, "&View")

        # Transfer menu
        transfer_menu = wx.Menu()
        transfer_menu.Append(
            ID_TRANSFER, "&Transfer\tCtrl+T", "Upload or download based on active pane"
        )
        transfer_menu.Append(ID_UPLOAD, "&Upload\tCtrl+U", "Upload selected local file(s)")
        transfer_menu.Append(ID_DOWNLOAD, "&Download\tCtrl+D", "Download selected remote file(s)")
        transfer_menu.AppendSeparator()
        self._retry_last_failed_item = transfer_menu.Append(
            ID_RETRY_LAST_FAILED,
            "&Retry Last Failed Transfer",
            "Retry the most recently failed transfer",
        )
        self._retry_last_failed_item.Enable(False)
        transfer_menu.AppendSeparator()
        transfer_menu.Append(
            ID_TRANSFER_QUEUE, "Transfer &Queue...\tCtrl+Shift+T", "Show transfer queue"
        )
        menubar.Append(transfer_menu, "&Transfer")

        # Sites menu
        sites_menu = wx.Menu()
        sites_menu.Append(ID_SITE_MANAGER, "&Site Manager...\tCtrl+S", "Manage saved sites")
        sites_menu.Append(ID_QUICK_CONNECT, "&Quick Connect...\tCtrl+N", "Quick connect to server")
        sites_menu.AppendSeparator()
        sites_menu.Append(
            ID_SAVE_CONNECTION, "Sa&ve Current Connection...", "Save active connection as a site"
        )
        sites_menu.AppendSeparator()
        sites_menu.Append(
            ID_IMPORT_CONNECTIONS,
            "&Import Sites...",
            "Import sites from other FTP/SFTP clients",
        )
        menubar.Append(sites_menu, "S&ites")

        # Help menu
        help_menu = wx.Menu()
        channel = self._get_update_channel()
        self._check_updates_item = help_menu.Append(
            ID_CHECK_UPDATES,
            f"Check for &Updates ({channel.title()})...",
            "Check for application updates",
        )
        help_menu.AppendSeparator()
        help_menu.Append(wx.ID_ABOUT, "&About", "About Portkey Drop")
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)

    def _build_toolbar(self) -> None:
        toolbar_panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        def _bind_label(lbl: wx.StaticText, ctrl: wx.Window) -> None:
            # Some wx builds (older wrappers/platform variants) do not expose SetLabelFor.
            if hasattr(lbl, "SetLabelFor"):
                lbl.SetLabelFor(ctrl)

        protocol_lbl = wx.StaticText(toolbar_panel, label="&Protocol:")
        self.tb_protocol = wx.Choice(toolbar_panel, choices=["sftp", "ftp", "ftps"])
        self.tb_protocol.SetSelection(0)
        _bind_label(protocol_lbl, self.tb_protocol)
        sizer.Add(protocol_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        sizer.Add(self.tb_protocol, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        host_lbl = wx.StaticText(toolbar_panel, label="&Host:")
        self.tb_host = wx.TextCtrl(toolbar_panel, size=(150, -1))
        _bind_label(host_lbl, self.tb_host)
        sizer.Add(host_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tb_host, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        port_lbl = wx.StaticText(toolbar_panel, label="P&ort:")
        self.tb_port = wx.TextCtrl(toolbar_panel, value="22", size=(50, -1))
        _bind_label(port_lbl, self.tb_port)
        sizer.Add(port_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tb_port, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        username_lbl = wx.StaticText(toolbar_panel, label="&Username:")
        self.tb_username = wx.TextCtrl(toolbar_panel, size=(100, -1))
        _bind_label(username_lbl, self.tb_username)
        sizer.Add(username_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tb_username, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        password_lbl = wx.StaticText(toolbar_panel, label="Pass&word:")
        self.tb_password = wx.TextCtrl(toolbar_panel, size=(100, -1), style=wx.TE_PASSWORD)
        _bind_label(password_lbl, self.tb_password)
        sizer.Add(password_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        sizer.Add(self.tb_password, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)

        self.tb_connect_btn = wx.Button(toolbar_panel, label="&Connect")
        sizer.Add(self.tb_connect_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)

        toolbar_panel.SetSizer(sizer)
        self._toolbar_panel = toolbar_panel

        # Update port on protocol change
        self.tb_protocol.Bind(wx.EVT_CHOICE, self._on_toolbar_protocol_change)

    def _build_dual_pane(self) -> None:
        pane_container = wx.Panel(self, style=wx.TAB_TRAVERSAL)

        # --- Local pane (left) ---
        local_panel = wx.Panel(pane_container)
        local_sizer = wx.BoxSizer(wx.VERTICAL)

        local_label = wx.StaticText(local_panel, label="Local:")
        local_sizer.Add(local_label, 0, wx.LEFT | wx.TOP, 4)

        self.local_path_bar = wx.TextCtrl(
            local_panel, value=self._local_cwd, style=wx.TE_PROCESS_ENTER
        )
        self.local_path_bar.SetName("Local Path")
        local_sizer.Add(self.local_path_bar, 0, wx.EXPAND | wx.ALL, 2)

        # StaticText immediately before the list so NVDA associates "Local files"
        # as the accessible name via HWND sibling order.
        local_list_label = wx.StaticText(local_panel, label="Local:")
        local_sizer.Add(local_list_label, 0, wx.LEFT, 4)

        self.local_file_list = wx.ListCtrl(local_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
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

        remote_label = wx.StaticText(remote_panel, label="Remote:")
        remote_sizer.Add(remote_label, 0, wx.LEFT | wx.TOP, 4)

        self.remote_path_bar = wx.TextCtrl(remote_panel, value="/", style=wx.TE_PROCESS_ENTER)
        self.remote_path_bar.SetName("Remote Path")
        remote_sizer.Add(self.remote_path_bar, 0, wx.EXPAND | wx.ALL, 2)

        # StaticText immediately before the list so NVDA associates "Remote files"
        # as the accessible name via HWND sibling order.
        remote_list_label = wx.StaticText(remote_panel, label="Remote:")
        remote_sizer.Add(remote_list_label, 0, wx.LEFT, 4)

        self.remote_file_list = wx.ListCtrl(remote_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.remote_file_list.InsertColumn(0, "Name", width=200)
        self.remote_file_list.InsertColumn(1, "Size", width=80)
        self.remote_file_list.InsertColumn(2, "Type", width=70)
        self.remote_file_list.InsertColumn(3, "Modified", width=130)
        self.remote_file_list.InsertColumn(4, "Permissions", width=100)
        remote_sizer.Add(self.remote_file_list, 1, wx.EXPAND)
        self.remote_panel = remote_panel
        remote_panel.SetSizer(remote_sizer)

        # --- Activity log pane (right column, sibling of local/remote) ---
        activity_panel = wx.Panel(pane_container)
        activity_sizer = wx.BoxSizer(wx.VERTICAL)

        self._activity_log_label = wx.StaticText(activity_panel, label="Activity Log:")
        activity_sizer.Add(self._activity_log_label, 0, wx.LEFT | wx.TOP, 4)

        self.activity_log = wx.TextCtrl(
            activity_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.activity_log.SetMinSize((-1, 150))
        activity_sizer.Add(self.activity_log, 1, wx.EXPAND | wx.ALL, 2)
        activity_panel.SetSizer(activity_sizer)
        self._activity_panel = activity_panel
        self._activity_log_visible = True

        # Three-column layout: local | remote | activity — natural tab order.
        h_sizer = wx.BoxSizer(wx.HORIZONTAL)
        h_sizer.Add(local_panel, 1, wx.EXPAND | wx.ALL, 2)
        h_sizer.Add(remote_panel, 1, wx.EXPAND | wx.ALL, 2)
        h_sizer.Add(activity_panel, 1, wx.EXPAND | wx.ALL, 2)

        pane_container.SetSizer(h_sizer)

        self._pane_container = pane_container

        # For backward compat: file_list points to remote
        self.file_list = self.remote_file_list

        # Main layout
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self._toolbar_panel, 0, wx.EXPAND)
        main_sizer.Add(pane_container, 1, wx.EXPAND | wx.ALL, 5)
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

    def _set_initial_focus(self) -> None:
        """Set startup focus to local files pane."""
        try:
            if self.local_file_list.GetItemCount() > 0:
                self.local_file_list.Select(0)
                self.local_file_list.Focus(0)
            self.local_file_list.SetFocus()
        except Exception:
            logger.debug("Failed to set initial focus", exc_info=True)

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
        self.Bind(wx.EVT_MENU, self._on_retry_last_failed, id=ID_RETRY_LAST_FAILED)
        self.Bind(wx.EVT_MENU, self._on_transfer_queue, id=ID_TRANSFER_QUEUE)
        self.Bind(wx.EVT_MENU, self._on_settings, id=ID_SETTINGS)
        self.Bind(wx.EVT_MENU, self._on_check_updates, id=ID_CHECK_UPDATES)
        self.Bind(wx.EVT_MENU, self._on_import_connections, id=ID_IMPORT_CONNECTIONS)
        self.Bind(wx.EVT_MENU, self._on_switch_pane_focus, id=ID_SWITCH_PANE_FOCUS)
        self.Bind(wx.EVT_MENU, self._on_focus_address_bar, id=ID_FOCUS_ADDRESS_BAR)
        self.Bind(wx.EVT_MENU, self._on_toggle_activity_log, id=ID_TOGGLE_ACTIVITY_LOG)
        self.Bind(wx.EVT_MENU, self._on_focus_local_pane, id=ID_FOCUS_LOCAL_PANE)
        self.Bind(wx.EVT_MENU, self._on_focus_remote_pane, id=ID_FOCUS_REMOTE_PANE)
        self.Bind(
            wx.EVT_MENU,
            self._on_focus_activity_log_pane,
            id=ID_FOCUS_ACTIVITY_LOG_PANE,
        )
        self.Bind(wx.EVT_MENU, self._on_about, id=wx.ID_ABOUT)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(get_transfer_event_binder(), self._on_transfer_update)

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

        # Activity log Shift+Tab to go back to remote file list

        # Path bar enter
        self.local_path_bar.Bind(wx.EVT_TEXT_ENTER, self._on_local_path_enter)
        self.remote_path_bar.Bind(wx.EVT_TEXT_ENTER, self._on_remote_path_enter)

        # Global accelerators for pane navigation and toolbar focus
        entries = [
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F6, ID_SWITCH_PANE_FOCUS),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("L"), ID_FOCUS_ADDRESS_BAR),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("1"), ID_FOCUS_LOCAL_PANE),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("2"), ID_FOCUS_REMOTE_PANE),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("3"), ID_FOCUS_ACTIVITY_LOG_PANE),
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

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
            host_key_policy=self._host_key_policy(),
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
            info.host_key_policy = self._host_key_policy()
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

    def _on_import_connections(self, event: wx.CommandEvent) -> None:
        dlg = ImportConnectionsDialog(self)
        result = dlg.ShowModal()
        selected_sites = dlg.selected_sites if result == wx.ID_OK else []
        dlg.Destroy()

        if not selected_sites:
            return

        duplicate_names: list[str] = []
        imported_count = 0

        existing = {
            (
                site.host.strip().lower(),
                self._effective_site_port(site.protocol, site.port),
                site.username.strip().lower(),
            )
            for site in self._site_manager.sites
        }

        for imported in selected_sites:
            key = (
                imported.host.strip().lower(),
                self._effective_site_port(imported.protocol, imported.port),
                imported.username.strip().lower(),
            )
            if key in existing:
                duplicate_names.append(imported.name or imported.host)
                continue

            site = Site(
                name=imported.name or imported.host,
                protocol=imported.protocol,
                host=imported.host,
                port=imported.port,
                username=imported.username,
                password=imported.password,
                key_path=imported.key_path,
                initial_dir=imported.initial_dir or "/",
                notes=imported.notes,
            )
            self._site_manager.add(site)
            existing.add(key)
            imported_count += 1

        message = f"Imported {imported_count} connection{'s' if imported_count != 1 else ''}."
        if duplicate_names:
            dup_preview = ", ".join(duplicate_names[:5])
            if len(duplicate_names) > 5:
                dup_preview += ", ..."
            message += (
                f"\nSkipped {len(duplicate_names)} duplicate"
                f"{'s' if len(duplicate_names) != 1 else ''}: {dup_preview}"
            )

        wx.MessageBox(message, "Import Sites", wx.OK | wx.ICON_INFORMATION, self)

    def _effective_site_port(self, protocol: str, port: int) -> int:
        if port > 0:
            return port
        defaults = {"sftp": 22, "ftp": 21, "ftps": 990}
        return defaults.get(protocol, 22)

    def _host_key_policy(self) -> HostKeyPolicy:
        """Map the verify_host_keys setting string to a HostKeyPolicy enum value."""
        mapping = {
            "ask": HostKeyPolicy.PROMPT,
            "always": HostKeyPolicy.AUTO_ADD,
            "never": HostKeyPolicy.STRICT,
        }
        setting = getattr(self._settings.connection, "verify_host_keys", "ask")
        return mapping.get(setting, HostKeyPolicy.PROMPT)

    def _do_connect(self, info: ConnectionInfo) -> None:
        if not info.host:
            wx.MessageBox("Please enter a host.", "Error", wx.OK | wx.ICON_ERROR, self)
            return
        if not info.username:
            wx.MessageBox("Please enter a username.", "Error", wx.OK | wx.ICON_ERROR, self)
            return
        if not info.password and info.protocol in {Protocol.FTP, Protocol.FTPS, Protocol.WEBDAV}:
            wx.MessageBox("Please enter a password.", "Error", wx.OK | wx.ICON_ERROR, self)
            return
        self._on_disconnect(None)
        self._update_status(f"Connecting to {info.host}…", "")

        def _connect_worker() -> None:
            try:
                client = create_client(info)
                client.connect()
                wx.CallAfter(self._on_connect_success, client)
            except Exception as exc:
                wx.CallAfter(self._on_connect_failure, exc)

        threading.Thread(target=_connect_worker, daemon=True).start()

    def _on_connect_success(self, client) -> None:
        """Called on the main thread when a background connection succeeds."""
        self._client = client
        self._remote_home = client.cwd
        self._update_status("Connected", client.cwd)
        self._update_title()
        protocol_type = (
            client._info.protocol.value
            if hasattr(client._info.protocol, "value")
            else str(client._info.protocol)
        )
        self.log_event(f"Connected to {client._info.host} via {protocol_type}")
        self._refresh_remote_files()
        self._toolbar_panel.Hide()
        self.GetSizer().Layout()
        self.local_file_list.SetFocus()

    def _on_connect_failure(self, exc: Exception) -> None:
        """Called on the main thread when a background connection fails."""
        self._client = None
        self._update_status("Disconnected", "")
        self.log_event(f"Connection failed: {exc}")
        wx.MessageBox(f"Connection failed: {exc}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _on_disconnect(self, event) -> None:
        was_connected = self._client is not None
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
        if was_connected:
            self.log_event("Disconnected from server")
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
            self._set_local_cwd(path)
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
            self._set_local_cwd(str(Path.home()))
            self._refresh_local_files()
            self._status(f"Home: {self._local_cwd}")
        elif self._client and self._client.connected:
            self._status("Going home...")
            wx.CallAfter(self._navigate_remote_home)

    def _navigate_remote_home(self) -> None:
        """Navigate to remote home in a non-blocking way."""
        try:
            self._client.chdir(self._remote_home)
            self._refresh_remote_files()
            self._status(f"Home: {self._client.cwd}")
        except Exception as e:
            wx.MessageBox(f"Failed to go home: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _on_refresh(self, event: wx.CommandEvent) -> None:
        if self._is_local_focused():
            self._refresh_local_files()
        else:
            self._refresh_remote_files()

    def _on_switch_pane_focus(self, event: wx.CommandEvent) -> None:
        focused = self.FindFocus()
        if self._activity_log_visible:
            if focused is self.local_file_list:
                self.remote_file_list.SetFocus()
            elif focused is self.remote_file_list:
                self.activity_log.SetFocus()
            else:
                self.local_file_list.SetFocus()
        else:
            if focused is self.local_file_list:
                self.remote_file_list.SetFocus()
            else:
                self.local_file_list.SetFocus()

    def _on_toggle_activity_log(self, event: wx.CommandEvent) -> None:
        if self._activity_log_visible:
            self._activity_panel.Hide()
            self._activity_log_visible = False
            self._toggle_log_item.SetItemLabel("Show &Activity Log")
            self._announce("Activity log hidden")
        else:
            self._activity_panel.Show()
            self._activity_log_visible = True
            self._toggle_log_item.SetItemLabel("Hide &Activity Log")
            self._announce("Activity log shown")
        self._pane_container.GetSizer().Layout()
        self.GetSizer().Layout()

    def _on_focus_local_pane(self, event: wx.CommandEvent) -> None:
        self.local_file_list.SetFocus()

    def _on_focus_remote_pane(self, event: wx.CommandEvent) -> None:
        self.remote_file_list.SetFocus()

    def _on_focus_activity_log_pane(self, event: wx.CommandEvent) -> None:
        if self._activity_log_visible:
            self.activity_log.SetFocus()
        else:
            self._announce("Activity log is hidden")

    def _on_focus_address_bar(self, event: wx.CommandEvent) -> None:
        if self._toolbar_panel.IsShown():
            self.tb_host.SetFocus()
            self._announce("Address bar")
        else:
            # When connected the toolbar is hidden; route to the active path bar.
            self.remote_path_bar.SetFocus()  # pragma: no cover
            self._announce("Remote path")  # pragma: no cover

    def _refresh_remote_files(self) -> None:
        if not self._client or not self._client.connected:
            return
        self._update_status("Loading...", self._client.cwd)
        client = self._client

        def _worker():
            try:
                files = client.list_dir()
                wx.CallAfter(self._on_remote_files_loaded, files, client.cwd)
            except Exception as e:
                wx.CallAfter(self._on_remote_files_error, e, client.cwd)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_remote_files_loaded(self, files: list[RemoteFile], cwd: str) -> None:
        restore_focus = self.FindFocus() is self.remote_file_list
        self._apply_sort(files)
        # Insert ".." entry at the top to navigate to parent
        if cwd != "/":
            parent_path = str(PurePosixPath(cwd).parent)
            parent_entry = RemoteFile(name="..", path=parent_path, is_dir=True)
            files.insert(0, parent_entry)
        self._remote_files = files
        self._populate_file_list(
            self.remote_file_list,
            self._get_visible_files(self._remote_files, self._remote_filter_text),
        )
        self._update_status("Connected", cwd)
        self.remote_path_bar.SetValue(cwd)
        self._update_title()
        # Select first item so screen readers announce the new directory
        if self.remote_file_list.GetItemCount() > 0:
            self.remote_file_list.Select(0)
            self.remote_file_list.Focus(0)
            if restore_focus:
                self.remote_file_list.SetFocus()
        count = len(self._get_visible_files(self._remote_files, self._remote_filter_text))
        if self._settings.display.announce_file_count:
            self._status(f"{cwd}: {count} items")

    def _on_remote_files_error(self, e: Exception, cwd: str) -> None:
        if isinstance(e, PermissionError):
            self._update_status("Connected", cwd)
            msg = "Permission denied: cannot list this directory."
        else:
            self._update_status("Connected", cwd)
            msg = str(e)
        wx.MessageBox(msg, "Error", wx.OK | wx.ICON_ERROR, self)

    def _refresh_local_files(self) -> None:
        restore_focus = self.FindFocus() is self.local_file_list
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
            # Select first item so screen readers announce the new directory
            if self.local_file_list.GetItemCount() > 0:
                self.local_file_list.Select(0)
                self.local_file_list.Focus(0)
                if restore_focus:
                    self.local_file_list.SetFocus()
            count = len(self._get_visible_files(self._local_files, self._local_filter_text))
            if self._settings.display.announce_file_count:
                self._status(f"{self._local_cwd}: {count} items")
        except Exception as e:
            wx.MessageBox(
                f"Failed to list local directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self
            )

    def _set_local_cwd(self, path: str) -> None:
        self._local_cwd = str(Path(path).expanduser().resolve())
        self._persist_local_folder_setting()

    def _persist_local_folder_setting(self) -> None:
        if update_last_local_folder(self._settings, self._local_cwd):
            save_settings(self._settings)

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
            logger.warning(
                "Remote item activated but no file selected (index: %s)", event.GetIndex()
            )
            return
        if not self._client:
            logger.warning("Remote item activated but no client")
            return
        logger.info(
            "Remote item activated: name=%r, is_dir=%s, path=%r",
            f.name,
            f.is_dir,
            f.path,
        )
        if f.is_dir:
            self._status(f"Opening {f.name}...")
            self._update_status("Loading...", f.path)
            client = self._client
            path = f.path

            def _chdir_worker():
                try:
                    client.chdir(path)
                    wx.CallAfter(self._refresh_remote_files)
                except Exception as e:
                    logger.exception("Failed to open remote directory %s", path)
                    wx.CallAfter(
                        wx.MessageBox,
                        f"Failed to open directory: {e}",
                        "Error",
                        wx.OK | wx.ICON_ERROR,
                    )

            threading.Thread(target=_chdir_worker, daemon=True).start()
        else:
            self._status(f"{f.name} detected as file, not directory")
            self._on_download(None)

    def _on_local_item_activated(self, event: wx.ListEvent) -> None:
        f = self._get_selected_local_file()
        if not f:
            return
        if f.is_dir:
            self._set_local_cwd(f.path)
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
        elif key == ord("V") and event.ControlDown():
            self._paste_upload()
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
        elif key == ord("V") and event.ControlDown():
            self._paste_local()
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
            self._status(f"Opening {f.name}...")
            self._client.chdir(f.path)
            self._refresh_remote_files()
        except Exception as e:
            wx.MessageBox(f"Failed to open directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

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
            self._set_local_cwd(new_path)
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
            self._transfer_service.submit_download(self._client, f.path, local_path, recursive=True)
            self._announce(f"Downloading folder {f.name} to {self._local_cwd}")
        else:
            self._transfer_service.submit_download(self._client, f.path, local_path, f.size)
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
            self._transfer_service.submit_upload(
                self._client, local_path, remote_path, recursive=True
            )
            self._announce(f"Uploading folder {filename}")
            self._update_status(f"Uploading folder {filename}...", self._client.cwd)
        else:
            total = os.path.getsize(local_path)
            self._transfer_service.submit_upload(self._client, local_path, remote_path, total)
            self._announce(f"Uploading {filename}")
            self._update_status(f"Uploading {filename}...", self._client.cwd)
        self._show_transfer_queue()

    def _get_clipboard_files(self) -> list[str]:
        """Get file paths from the system clipboard."""
        paths: list[str] = []
        data = wx.FileDataObject()
        if wx.TheClipboard.Open():
            try:
                if wx.TheClipboard.GetData(data):
                    paths = list(data.GetFilenames())
            finally:
                wx.TheClipboard.Close()
        return paths

    def _paste_upload(self) -> None:
        """Upload files from clipboard to the remote server."""
        if not self._client or not self._client.connected:
            self._announce("Not connected")
            return
        paths = self._get_clipboard_files()
        if not paths:
            self._announce("No files in clipboard")
            return
        count = 0
        for local_path in paths:
            p = Path(local_path)
            if not p.exists():
                continue
            filename = p.name
            remote_path = f"{self._client.cwd.rstrip('/')}/{filename}"
            if p.is_dir():
                self._transfer_service.submit_upload(
                    self._client, str(p), remote_path, recursive=True
                )
            else:
                total = os.path.getsize(str(p))
                self._transfer_service.submit_upload(self._client, str(p), remote_path, total)
            count += 1
        if count:
            self._announce(
                f"Added {count} item{'s' if count != 1 else ''} to transfer queue from clipboard"
            )
            self._show_transfer_queue()

    def _paste_local(self) -> None:
        """Copy files from clipboard to the current local directory."""
        import shutil

        paths = self._get_clipboard_files()
        if not paths:
            self._announce("No files in clipboard")
            return
        count = 0
        for src_path in paths:
            p = Path(src_path)
            if not p.exists():
                continue
            dest = Path(self._local_cwd) / p.name
            try:
                if p.is_dir():
                    shutil.copytree(str(p), str(dest))
                else:
                    shutil.copy2(str(p), str(dest))
                count += 1
            except Exception as e:
                logger.warning(f"Failed to paste {p.name}: {e}")
        if count:
            self._announce(f"Pasted {count} item{'s' if count != 1 else ''}")
            self._refresh_local_files()

    def _show_transfer_queue(self) -> None:
        """Show the transfer queue as a modeless dialog."""
        if hasattr(self, "_transfer_dlg") and self._transfer_dlg:
            try:
                self._transfer_dlg.Raise()
                return
            except Exception:
                pass
        self._transfer_dlg = create_transfer_dialog(
            self, self._transfer_service, log_callback=self.log_event
        )
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
                self._update_status(f"Deleting {f.name}...", self._client.cwd)
                if f.is_dir:
                    self._client.rmdir(f.path)
                else:
                    self._client.delete(f.path)
                self._announce(f"Deleted {f.name}")
                self._update_status("Delete complete.", self._client.cwd)
                self._refresh_remote_files()
            except Exception as e:
                self._update_status("Delete failed.", self._client.cwd)
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
                    self._update_status(f"Renaming {f.name}...", self._client.cwd)
                    self._client.rename(f.path, new_path)
                    self._announce(f"Renamed to {new_name}")
                    self._update_status("Rename complete.", self._client.cwd)
                    self._refresh_remote_files()
                except Exception as e:
                    self._update_status("Rename failed.", self._client.cwd)
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
                    self._update_status(f"Creating directory {name}...", self._client.cwd)
                    self._client.mkdir(path)
                    self._announce(f"Created directory {name}")
                    self._update_status("Directory created.", self._client.cwd)
                    self._refresh_remote_files()
                except Exception as e:
                    self._update_status("Create directory failed.", self._client.cwd)
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

    def _on_retry_last_failed(self, event: wx.CommandEvent) -> None:
        """Retry the most recently failed transfer."""
        if self._last_failed_transfer is None:
            return
        if not self._client or not self._client.connected:
            self._announce("Not connected")
            return
        original = None
        for j in self._transfer_service.jobs:
            if j.id == self._last_failed_transfer:
                original = j
                break
        if original is None or original.status != TransferStatus.FAILED:
            return
        new_job = self._transfer_service.retry(original.id, self._client)
        if new_job is not None:
            filename = PurePosixPath(original.source).name or os.path.basename(original.destination)
            direction_label = original.direction.value
            msg = f"Retrying {direction_label} of {filename}"
            self._announce(msg)
            current_path = self._client.cwd if self._client.connected else ""
            self._update_status(msg, current_path)
            self._retry_last_failed_item.Enable(False)
            self._last_failed_transfer = None
            self._show_transfer_queue()

    def _on_transfer_queue(self, event: wx.CommandEvent) -> None:
        self._show_transfer_queue()

    def _on_transfer_update(self, event) -> None:
        latest_status_message = None
        refresh_local_files = False
        refresh_remote_files = False
        for job in self._transfer_service.jobs:
            current_state = job.status.value
            previous_state = self._transfer_state_by_id.get(job.id)
            if current_state == previous_state:
                continue

            self._transfer_state_by_id[job.id] = current_state
            direction_label = "Upload" if job.direction == TransferDirection.UPLOAD else "Download"
            filename = os.path.basename(job.destination) or PurePosixPath(job.source).name

            if job.status == TransferStatus.PENDING:
                latest_status_message = f"{direction_label} queued."
            elif job.status == TransferStatus.IN_PROGRESS:
                latest_status_message = f"{direction_label} in progress..."
            elif job.status == TransferStatus.COMPLETE:
                latest_status_message = f"{direction_label} complete."
                self.log_event(f"{direction_label} complete: {filename}")
                if job.direction == TransferDirection.DOWNLOAD:
                    refresh_local_files = True
                else:
                    refresh_remote_files = True
            elif job.status == TransferStatus.FAILED:
                latest_status_message = f"{direction_label} failed."
                error_msg = job.error or "Unknown error"
                self.log_event(f"{direction_label} failed: {filename} — {error_msg}")
                self._announce(f"{direction_label} failed.")
                self._last_failed_transfer = job.id
                self._retry_last_failed_item.Enable(True)
            elif job.status == TransferStatus.CANCELLED:
                latest_status_message = f"{direction_label} cancelled."
                self.log_event(f"{direction_label} cancelled: {filename}")

        if refresh_local_files:
            self._refresh_local_files()
        if refresh_remote_files:
            self._refresh_remote_files()

        if latest_status_message:
            current_path = self._client.cwd if self._client and self._client.connected else ""
            self._update_status(latest_status_message, current_path)

    def _on_settings(self, event: wx.CommandEvent) -> None:
        dlg = SettingsDialog(
            self,
            self._settings,
            on_check_updates=self._on_check_updates_from_settings,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._settings = dlg.get_settings()
            update_last_local_folder(self._settings, self._local_cwd)
            save_settings(self._settings)
            self._transfer_service.set_max_workers(
                self._settings.transfer.concurrent_transfers,
            )
            self.update_check_updates_menu_label()
            self._start_auto_update_checks()
            self._populate_file_list(
                self.remote_file_list,
                self._get_visible_files(self._remote_files, self._remote_filter_text),
            )
            self._populate_file_list(
                self.local_file_list,
                self._get_visible_files(self._local_files, self._local_filter_text),
            )
        dlg.Destroy()

    def _on_check_updates_from_settings(self, channel: str, parent: wx.Window | None) -> None:
        """Manual update check callback wired into settings dialog."""
        self._on_check_updates(None, channel_override=channel, parent=parent)

    def _get_update_channel(self) -> str:
        """Get the configured update channel from settings."""
        try:
            return getattr(self._settings.app, "update_channel", "stable")
        except Exception:
            return "stable"

    def update_check_updates_menu_label(self) -> None:
        """Refresh check-for-updates menu text after settings changes."""
        if hasattr(self, "_check_updates_item"):
            channel = self._get_update_channel()
            self._check_updates_item.SetItemLabel(f"Check for &Updates ({channel.title()})...")

    def _start_auto_update_checks(self) -> None:
        """Start periodic update checks based on current settings."""
        try:
            auto_enabled = bool(getattr(self._settings.app, "auto_update_enabled", True))

            if self._auto_update_check_timer:
                self._auto_update_check_timer.Stop()
                self._auto_update_check_timer = None

            if not auto_enabled:
                logger.debug("Automatic update checks disabled")
                return

            interval_hours = max(
                1,
                int(getattr(self._settings.app, "update_check_interval_hours", 24)),
            )
            interval_ms = interval_hours * 60 * 60 * 1000
            self._auto_update_check_timer = wx.Timer(self)
            self._auto_update_check_timer.Bind(wx.EVT_TIMER, self._on_auto_update_check_timer)
            self._auto_update_check_timer.Start(interval_ms)
            logger.info("Automatic update checks scheduled every %s hour(s)", interval_hours)
        except Exception as exc:
            logger.warning("Failed to start automatic update checks: %s", exc)

    def _on_auto_update_check_timer(self, event) -> None:
        """Run automatic update check from timer ticks."""
        self._check_for_updates_on_startup()

    def _show_update_available_dialog(
        self,
        *,
        current_display_version: str,
        update_info,
        on_accept: Callable[[], None],
        parent: wx.Window | None = None,
    ) -> None:
        """Show update dialog with release notes and invoke callback on accept."""
        channel_label = "Nightly" if update_info.is_nightly else "Stable"
        dlg = UpdateAvailableDialog(
            parent=parent or self,
            current_version=current_display_version,
            new_version=update_info.version,
            channel_label=channel_label,
            release_notes=update_info.release_notes,
        )
        try:
            if dlg.ShowModal() == wx.ID_OK:
                on_accept()
        finally:
            dlg.Destroy()

    def _check_for_updates_on_startup(self) -> None:
        """Check for updates at startup when running frozen builds."""
        if not getattr(sys, "frozen", False):
            logger.debug("Running from source, skipping startup update check")
            return

        if not getattr(self._settings.app, "auto_update_enabled", True):
            logger.debug("Automatic update checks disabled")
            return

        channel = self._get_update_channel()
        current_version = getattr(self, "version", "0.0.0")
        build_tag = getattr(self, "build_tag", None)
        current_nightly_date = parse_nightly_date(build_tag) if build_tag else None

        if channel == "nightly" and not build_tag:
            logger.warning(
                "Skipping startup nightly check because build tag is unavailable; "
                "manual check still allowed."
            )
            return

        def do_check() -> None:
            try:
                service = UpdateService("PortkeyDrop")
                result = service.check_for_updates(
                    current_version=current_version,
                    current_nightly_date=current_nightly_date,
                    channel=channel,
                )
                if not result:
                    return

                update_info, release = result
                display_version = current_nightly_date if current_nightly_date else current_version

                def prompt() -> None:
                    self._show_update_available_dialog(
                        current_display_version=display_version,
                        update_info=update_info,
                        on_accept=lambda: self._download_and_apply_update(update_info, release),
                        parent=self,
                    )

                wx.CallAfter(prompt)
            except Exception as exc:
                logger.warning("Startup update check failed: %s", exc)

        threading.Thread(target=do_check, daemon=True).start()

    def _on_check_updates(
        self,
        event: wx.CommandEvent | None,
        *,
        channel_override: str | None = None,
        parent: wx.Window | None = None,
    ) -> None:
        """Manually check for updates from the Help menu."""
        if not getattr(sys, "frozen", False):
            wx.MessageBox(
                "Update checking is only available in installed builds.\n"
                "You're running from source - use git pull to update.",
                "Running from Source",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        channel = channel_override or self._get_update_channel()
        current_version = getattr(self, "version", "0.0.0")
        build_tag = getattr(self, "build_tag", None)
        current_nightly_date = parse_nightly_date(build_tag) if build_tag else None
        display_version = current_nightly_date if current_nightly_date else current_version

        if hasattr(wx, "BeginBusyCursor"):
            wx.BeginBusyCursor()

        def do_check() -> None:
            try:
                service = UpdateService("PortkeyDrop")
                result = service.check_for_updates(
                    current_version=current_version,
                    current_nightly_date=current_nightly_date,
                    channel=channel,
                )

                def finish_busy() -> None:
                    if hasattr(wx, "EndBusyCursor"):
                        wx.EndBusyCursor()

                wx.CallAfter(finish_busy)

                if result is None:
                    if current_nightly_date and channel == "stable":
                        msg = (
                            f"You're on nightly ({current_nightly_date}).\n"
                            "No newer stable release available."
                        )
                    elif current_nightly_date:
                        msg = f"You're on the latest nightly ({current_nightly_date})."
                    else:
                        msg = f"You're up to date ({display_version})."

                    wx.CallAfter(
                        wx.MessageBox,
                        msg,
                        "No Updates Available",
                        wx.OK | wx.ICON_INFORMATION,
                        self,
                    )
                    return

                update_info, release = result

                def prompt() -> None:
                    self._show_update_available_dialog(
                        current_display_version=display_version,
                        update_info=update_info,
                        on_accept=lambda: self._download_and_apply_update(update_info, release),
                        parent=parent or self,
                    )

                wx.CallAfter(prompt)

            except Exception as exc:
                if hasattr(wx, "EndBusyCursor"):
                    wx.CallAfter(wx.EndBusyCursor)
                wx.CallAfter(
                    wx.MessageBox,
                    f"Failed to check for updates:\n{exc}",
                    "Update Check Failed",
                    wx.OK | wx.ICON_ERROR,
                    self,
                )

        threading.Thread(target=do_check, daemon=True).start()

    def _download_and_apply_update(self, update_info, release: dict | None = None) -> None:
        """Download selected update and apply it after confirmation."""
        progress_dlg = None
        if hasattr(wx, "ProgressDialog"):
            progress_style = (
                getattr(wx, "PD_APP_MODAL", 0)
                | getattr(wx, "PD_AUTO_HIDE", 0)
                | getattr(wx, "PD_CAN_ABORT", 0)
            )
            progress_dlg = wx.ProgressDialog(
                "Downloading Update",
                f"Downloading {update_info.artifact_name}...",
                maximum=100,
                parent=self,
                style=progress_style,
            )

        def do_download() -> None:
            try:
                dest_dir = Path(tempfile.gettempdir())

                def progress_callback(downloaded: int, total: int) -> None:
                    if not progress_dlg or total <= 0:
                        return
                    percent = int((downloaded / total) * 100)
                    wx.CallAfter(
                        progress_dlg.Update,
                        percent,
                        f"Downloading... {downloaded // 1024} / {total // 1024} KB",
                    )

                service = UpdateService("PortkeyDrop")
                update_path = service.download_update(
                    update_info,
                    dest_dir=dest_dir,
                    progress_callback=progress_callback,
                    release=release,
                )

                if progress_dlg:
                    wx.CallAfter(progress_dlg.Destroy)

                def confirm_apply() -> None:
                    result_code = wx.MessageBox(
                        "Download complete. Portkey Drop will now restart to apply the update.\n\n"
                        "Continue?",
                        "Apply Update",
                        wx.YES_NO | wx.ICON_QUESTION,
                        self,
                    )
                    if result_code == wx.YES:
                        for win in wx.GetTopLevelWindows():
                            try:
                                win.Destroy()
                            except Exception:
                                pass
                        wx.SafeYield()
                        apply_update(update_path, portable=is_portable_mode())

                wx.CallAfter(confirm_apply)

            except ChecksumVerificationError as exc:
                logger.error("Update checksum verification failed: %s", exc)
                if progress_dlg:
                    wx.CallAfter(progress_dlg.Destroy)
                wx.CallAfter(
                    wx.MessageBox,
                    "Downloaded update failed checksum verification and was discarded.",
                    "Update Verification Failed",
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
            except Exception as exc:
                logger.error("Failed to download update: %s", exc)
                if progress_dlg:
                    wx.CallAfter(progress_dlg.Destroy)
                wx.CallAfter(
                    wx.MessageBox,
                    f"Failed to download update:\n{exc}",
                    "Download Error",
                    wx.OK | wx.ICON_ERROR,
                    self,
                )

        threading.Thread(target=do_download, daemon=True).start()

    def _restore_transfer_queue(self) -> None:
        """Load persisted transfer queue and announce restored items."""
        restored = load_queue(get_config_dir())
        if restored:
            self._transfer_service.restore_jobs(restored)
            count = len(restored)
            msg = f"Restored {count} pending transfer{'s' if count != 1 else ''} from last session"
            wx.CallAfter(self._announce, msg)

    def _on_close(self, event) -> None:
        """Save transfer queue and stop timers before closing the window."""
        save_queue(self._transfer_service, get_config_dir())
        if self._auto_update_check_timer:
            self._auto_update_check_timer.Stop()
        if event is not None and hasattr(event, "Skip"):
            event.Skip()

    def _on_about(self, event: wx.CommandEvent) -> None:
        info = wx.adv.AboutDialogInfo()
        info.SetName("Portkey Drop")
        info.SetVersion(self.version)
        info.SetDescription("Accessible file transfer client for screen reader users")
        wx.adv.AboutBox(info)

    def _status(self, message: str) -> None:
        """Update status bar text without forcing speech."""
        self.status_bar.SetStatusText(message, 0)

    def log_event(self, message: str) -> None:
        """Append a timestamped entry to the activity log and announce it."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}\n"
        self.activity_log.AppendText(entry)
        self._announce(message)

    def _announce(self, message: str) -> None:
        """Announce a message for screen readers via status bar + announcer wrapper."""
        self._status(message)
        logger.debug("Announcement requested: %s", message)
        self._announcer.announce(message)


class PortkeyDropApp(wx.App):
    """Main wxPython application."""

    def OnInit(self) -> bool:
        if is_portable_mode():
            portable_dir = get_config_dir()
            standard_dir = Path.home() / ".portkeydrop"
            is_fresh_portable_dir = (
                not (portable_dir / "sites.json").exists()
                or not (portable_dir / "known_hosts").exists()
            )
            if is_fresh_portable_dir and has_migration_candidates(portable_dir, standard_dir):
                candidates = get_migration_candidates(standard_dir)
                dialog = MigrationDialog(None, candidates)
                try:
                    if dialog.ShowModal() == wx.ID_OK:
                        selected_files = dialog.get_selected_filenames()
                        migrate_files(selected_files, standard_dir, portable_dir)
                finally:
                    dialog.Destroy()

            keyring_migration_marker = portable_dir / ".keyring_migrated"
            if not keyring_migration_marker.exists():
                site_manager = SiteManager(config_dir=portable_dir)
                if site_manager.should_offer_keyring_to_vault_migration():
                    prompt_message = (
                        "Portable mode stores saved passwords in a local encrypted vault "
                        "(vault.enc).\n\n"
                        "Import passwords from your system keyring into the portable vault?"
                    )
                    result = wx.MessageBox(
                        prompt_message,
                        "Import Passwords to Portable Vault",
                        wx.YES_NO | wx.ICON_INFORMATION,
                    )
                    if result == wx.YES:
                        site_manager.migrate_keyring_passwords_to_vault()
                    keyring_migration_marker.parent.mkdir(parents=True, exist_ok=True)
                    keyring_migration_marker.touch(exist_ok=True)

        frame = MainFrame()
        frame.Show()
        self.SetTopWindow(frame)
        return True
