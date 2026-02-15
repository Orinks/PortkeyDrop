"""Main application window for AccessiTransfer."""

from __future__ import annotations

import logging
import os
from pathlib import Path, PurePosixPath

import wx

from accessitransfer.dialogs.properties import PropertiesDialog
from accessitransfer.dialogs.quick_connect import QuickConnectDialog
from accessitransfer.dialogs.settings import SettingsDialog
from accessitransfer.dialogs.site_manager import SiteManagerDialog
from accessitransfer.dialogs.transfer import (
    TransferManager,
    create_transfer_dialog,
)
from accessitransfer.protocols import ConnectionInfo, Protocol, RemoteFile, create_client
from accessitransfer.settings import load_settings, save_settings
from accessitransfer.sites import SiteManager

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
ID_DELETE = wx.NewIdRef()
ID_RENAME = wx.NewIdRef()
ID_MKDIR = wx.NewIdRef()
ID_PARENT_DIR = wx.NewIdRef()
ID_FILTER = wx.NewIdRef()
ID_SETTINGS = wx.NewIdRef()


class MainFrame(wx.Frame):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__(None, title="AccessiTransfer", size=(800, 600))
        self.SetName("AccessiTransfer Main Window")

        self._client = None
        self._files: list[RemoteFile] = []
        self._settings = load_settings()
        self._site_manager = SiteManager()
        self._transfer_manager = TransferManager(notify_window=self)
        self._filter_text = ""

        self._build_menu()
        self._build_toolbar()
        self._build_file_list()
        self._build_status_bar()
        self._bind_events()
        self._update_title()

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
        menubar.Append(sites_menu, "S&ites")

        # Transfer menu
        transfer_menu = wx.Menu()
        transfer_menu.Append(ID_UPLOAD, "&Upload...\tCtrl+U", "Upload file")
        transfer_menu.Append(ID_DOWNLOAD, "&Download\tCtrl+D", "Download selected file")
        transfer_menu.AppendSeparator()
        transfer_menu.Append(ID_TRANSFER_QUEUE, "&Transfer Queue...\tCtrl+T", "Show transfer queue")
        menubar.Append(transfer_menu, "&Transfer")

        # View menu
        view_menu = wx.Menu()
        view_menu.Append(ID_REFRESH, "&Refresh\tCtrl+R", "Refresh file list")
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
        help_menu.Append(wx.ID_ABOUT, "&About", "About AccessiTransfer")
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

    def _build_file_list(self) -> None:
        self.file_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.file_list.SetName("Remote Files")
        self.file_list.InsertColumn(0, "Name", width=250)
        self.file_list.InsertColumn(1, "Size", width=100)
        self.file_list.InsertColumn(2, "Type", width=80)
        self.file_list.InsertColumn(3, "Modified", width=150)
        self.file_list.InsertColumn(4, "Permissions", width=120)

        # Layout
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self._toolbar_panel, 0, wx.EXPAND)
        main_sizer.Add(self.file_list, 1, wx.EXPAND)
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
            self.SetTitle(f"AccessiTransfer - {self._client.cwd}")
        else:
            self.SetTitle("AccessiTransfer")

    def _bind_events(self) -> None:
        # Menu events
        self.Bind(wx.EVT_MENU, self._on_connect_toolbar, id=ID_CONNECT)
        self.Bind(wx.EVT_MENU, self._on_disconnect, id=ID_DISCONNECT)
        self.Bind(wx.EVT_MENU, self._on_exit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self._on_site_manager, id=ID_SITE_MANAGER)
        self.Bind(wx.EVT_MENU, self._on_quick_connect, id=ID_QUICK_CONNECT)
        self.Bind(wx.EVT_MENU, self._on_upload, id=ID_UPLOAD)
        self.Bind(wx.EVT_MENU, self._on_download, id=ID_DOWNLOAD)
        self.Bind(wx.EVT_MENU, self._on_refresh, id=ID_REFRESH)
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

        # File list events
        self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_item_activated)

        # Keyboard shortcuts for file list
        self.file_list.Bind(wx.EVT_KEY_DOWN, self._on_file_list_key)

        # Transfer updates (no specific event binding needed)

    def _on_toolbar_protocol_change(self, event: wx.CommandEvent) -> None:
        proto = self.tb_protocol.GetStringSelection()
        defaults = {"sftp": "22", "ftp": "21", "ftps": "990"}
        self.tb_port.SetValue(defaults.get(proto, "22"))

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
        if dlg.ShowModal() == wx.ID_OK:
            info = dlg.get_connection_info()
            self._do_connect(info)
        dlg.Destroy()

    def _on_site_manager(self, event: wx.CommandEvent) -> None:
        dlg = SiteManagerDialog(self, self._site_manager)
        result = dlg.ShowModal()
        if result == wx.ID_OK and dlg.connect_requested and dlg.selected_site:
            info = dlg.selected_site.to_connection_info()
            self._do_connect(info)
        dlg.Destroy()

    def _do_connect(self, info: ConnectionInfo) -> None:
        if not info.host:
            wx.MessageBox("Please enter a host.", "Error", wx.OK | wx.ICON_ERROR, self)
            return
        self._on_disconnect(None)
        try:
            self._client = create_client(info)
            self._client.connect()
            self._update_status("Connected", self._client.cwd)
            self._update_title()
            self._announce(f"Connected to {info.host}")
            self._refresh_files()
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
        self._files = []
        self.file_list.DeleteAllItems()
        self._update_status("Disconnected", "")
        self._update_title()

    def _on_exit(self, event: wx.CommandEvent) -> None:
        self.Close()

    def _on_refresh(self, event: wx.CommandEvent) -> None:
        self._refresh_files()

    def _refresh_files(self) -> None:
        if not self._client or not self._client.connected:
            return
        try:
            self._files = self._client.list_dir()
            self._apply_sort()
            self._populate_file_list()
            self._update_status("Connected", self._client.cwd)
            self._update_title()
            count = len(self._get_visible_files())
            if self._settings.display.announce_file_count:
                self._announce(f"{self._client.cwd}: {count} items")
        except Exception as e:
            wx.MessageBox(f"Failed to list directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _get_visible_files(self) -> list[RemoteFile]:
        files = self._files
        if not self._settings.display.show_hidden_files:
            files = [f for f in files if not f.name.startswith(".")]
        if self._filter_text:
            pattern = self._filter_text.lower()
            files = [f for f in files if pattern in f.name.lower()]
        return files

    def _apply_sort(self) -> None:
        key_map = {
            "name": lambda f: (not f.is_dir, f.name.lower()),
            "size": lambda f: (not f.is_dir, f.size),
            "type": lambda f: (not f.is_dir, "dir" if f.is_dir else Path(f.name).suffix.lower()),
            "modified": lambda f: (not f.is_dir, f.modified or ""),
        }
        key_fn = key_map.get(self._settings.display.sort_by, key_map["name"])
        self._files.sort(key=key_fn, reverse=not self._settings.display.sort_ascending)

    def _populate_file_list(self) -> None:
        self.file_list.DeleteAllItems()
        for f in self._get_visible_files():
            idx = self.file_list.InsertItem(self.file_list.GetItemCount(), f.name)
            self.file_list.SetItem(idx, 1, f.display_size)
            self.file_list.SetItem(idx, 2, "Directory" if f.is_dir else "File")
            self.file_list.SetItem(idx, 3, f.display_modified)
            self.file_list.SetItem(idx, 4, f.permissions)

    def _on_toggle_hidden(self, event: wx.CommandEvent) -> None:
        self._settings.display.show_hidden_files = event.IsChecked()
        self._populate_file_list()

    def _sort_by(self, field: str) -> None:
        self._settings.display.sort_by = field
        self._apply_sort()
        self._populate_file_list()

    def _on_filter(self, event: wx.CommandEvent) -> None:
        dlg = wx.TextEntryDialog(self, "Filter files:", "Filter", self._filter_text)
        dlg.SetName("Filter Files")
        if dlg.ShowModal() == wx.ID_OK:
            self._filter_text = dlg.GetValue()
            self._populate_file_list()
        dlg.Destroy()

    def _get_selected_file(self) -> RemoteFile | None:
        idx = self.file_list.GetFirstSelected()
        if idx == wx.NOT_FOUND:
            return None
        visible = self._get_visible_files()
        if 0 <= idx < len(visible):
            return visible[idx]
        return None

    def _on_item_activated(self, event: wx.ListEvent) -> None:
        f = self._get_selected_file()
        if not f or not self._client:
            return
        if f.is_dir:
            try:
                self._client.chdir(f.path)
                self._refresh_files()
            except Exception as e:
                wx.MessageBox(
                    f"Failed to open directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self
                )
        else:
            self._on_download(None)

    def _on_file_list_key(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_BACK:
            self._go_parent_dir()
        elif key == wx.WXK_DELETE:
            self._on_delete(None)
        elif key == wx.WXK_F2:
            self._on_rename(None)
        else:
            event.Skip()

    def _go_parent_dir(self) -> None:
        if not self._client or not self._client.connected:
            return
        try:
            self._client.parent_dir()
            self._refresh_files()
        except Exception as e:
            wx.MessageBox(f"Failed to go to parent: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _on_download(self, event) -> None:
        f = self._get_selected_file()
        if not f or f.is_dir or not self._client:
            return
        default_dir = self._settings.transfer.default_download_dir
        with wx.FileDialog(
            self,
            "Save As",
            defaultDir=default_dir,
            defaultFile=f.name,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                local_path = dlg.GetPath()
                self._transfer_manager.add_download(self._client, f.path, local_path, f.size)
                self._announce(f"Downloading {f.name}")

    def _on_upload(self, event: wx.CommandEvent) -> None:
        if not self._client or not self._client.connected:
            return
        with wx.FileDialog(
            self,
            "Select File to Upload",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                local_path = dlg.GetPath()
                filename = os.path.basename(local_path)
                remote_path = f"{self._client.cwd.rstrip('/')}/{filename}"
                total = os.path.getsize(local_path)
                self._transfer_manager.add_upload(self._client, local_path, remote_path, total)
                self._announce(f"Uploading {filename}")

    def _on_delete(self, event) -> None:
        f = self._get_selected_file()
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
                self._refresh_files()
            except Exception as e:
                wx.MessageBox(f"Delete failed: {e}", "Error", wx.OK | wx.ICON_ERROR, self)

    def _on_rename(self, event) -> None:
        f = self._get_selected_file()
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
                    self._refresh_files()
                except Exception as e:
                    wx.MessageBox(f"Rename failed: {e}", "Error", wx.OK | wx.ICON_ERROR, self)
        dlg.Destroy()

    def _on_mkdir(self, event: wx.CommandEvent) -> None:
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
                    self._refresh_files()
                except Exception as e:
                    wx.MessageBox(
                        f"Failed to create directory: {e}", "Error", wx.OK | wx.ICON_ERROR, self
                    )
        dlg.Destroy()

    def _on_properties(self, event: wx.CommandEvent) -> None:
        f = self._get_selected_file()
        if not f:
            return
        dlg = PropertiesDialog(self, f)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_transfer_queue(self, event: wx.CommandEvent) -> None:
        dlg = create_transfer_dialog(self, self._transfer_manager)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_transfer_update(self, event) -> None:
        # Could update status bar with transfer info
        pass

    def _on_settings(self, event: wx.CommandEvent) -> None:
        dlg = SettingsDialog(self, self._settings)
        if dlg.ShowModal() == wx.ID_OK:
            self._settings = dlg.get_settings()
            save_settings(self._settings)
            self._populate_file_list()
        dlg.Destroy()

    def _on_about(self, event: wx.CommandEvent) -> None:
        info = wx.adv.AboutDialogInfo()
        info.SetName("AccessiTransfer")
        info.SetVersion("0.1.0")
        info.SetDescription("Accessible file transfer client for screen reader users")
        wx.adv.AboutBox(info)

    def _announce(self, message: str) -> None:
        """Announce a message for screen readers via status bar."""
        self.status_bar.SetStatusText(message, 0)
        # Try prismatoid for direct speech if available
        try:
            import prismatoid

            prismatoid.speak(message)
        except Exception:
            pass


class AccessiTransferApp(wx.App):
    """Main wxPython application."""

    def OnInit(self) -> bool:
        frame = MainFrame()
        frame.Show()
        self.SetTopWindow(frame)
        return True
