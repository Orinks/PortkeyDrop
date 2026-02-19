"""Site Manager dialog for Portkey Drop."""

from __future__ import annotations

import wx

from portkeydrop.sites import Site, SiteManager


class SiteManagerDialog(wx.Dialog):
    """Dialog for managing saved connection sites."""

    def __init__(self, parent: wx.Window | None, site_manager: SiteManager) -> None:
        super().__init__(
            parent,
            title="Site Manager",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(600, 450),
        )
        self._site_manager = site_manager
        self._selected_site: Site | None = None
        self._connect_requested = False
        self._build_ui()
        self._refresh_site_list()
        self.SetName("Site Manager Dialog")

    def _build_ui(self) -> None:
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        left_sizer = wx.BoxSizer(wx.VERTICAL)
        saved_sites_label = wx.StaticText(self, label="&Saved Sites:")
        left_sizer.Add(saved_sites_label, 0, wx.ALL, 4)

        self.site_list = wx.ListBox(self)
        self.site_list.SetName("Saved Sites")
        if hasattr(saved_sites_label, "SetLabelFor"):
            saved_sites_label.SetLabelFor(self.site_list)
        left_sizer.Add(self.site_list, 1, wx.EXPAND | wx.ALL, 4)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_btn = wx.Button(self, label="&Add")
        self.add_btn.SetName("Add Site")
        self.remove_btn = wx.Button(self, label="&Remove")
        self.remove_btn.SetName("Remove Site")
        self.connect_btn = wx.Button(self, label="Co&nnect")
        self.connect_btn.SetName("Connect Site")
        btn_sizer.Add(self.add_btn, 0, wx.RIGHT, 4)
        btn_sizer.Add(self.remove_btn, 0, wx.RIGHT, 4)
        btn_sizer.Add(self.connect_btn, 0)
        left_sizer.Add(btn_sizer, 0, wx.ALL, 4)

        main_sizer.Add(left_sizer, 1, wx.EXPAND | wx.ALL, 4)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=6)
        grid.AddGrowableCol(1, 1)

        fields = [
            ("Na&me:", "name_text", wx.TextCtrl, {}),
            ("P&rotocol:", "protocol_choice", wx.Choice, {"choices": ["sftp", "ftp", "ftps"]}),
            ("&Host:", "host_text", wx.TextCtrl, {}),
            ("Po&rt:", "port_text", wx.TextCtrl, {}),
            ("&Username:", "username_text", wx.TextCtrl, {}),
            ("Pass&word:", "password_text", wx.TextCtrl, {"style": wx.TE_PASSWORD}),
            ("&Key Path:", "key_path_text", wx.TextCtrl, {}),
            ("&Initial Dir:", "initial_dir_text", wx.TextCtrl, {}),
        ]

        for label_text, attr_name, ctrl_class, kwargs in fields:
            lbl = wx.StaticText(self, label=label_text)
            ctrl = ctrl_class(self, **kwargs)
            ctrl_name = label_text.replace("&", "").rstrip(":")
            ctrl.SetName(ctrl_name)
            if hasattr(lbl, "SetLabelFor"):
                lbl.SetLabelFor(ctrl)
            setattr(self, attr_name, ctrl)
            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            if attr_name == "key_path_text":
                row = wx.BoxSizer(wx.HORIZONTAL)
                row.Add(ctrl, 1, wx.EXPAND)
                self.browse_btn = wx.Button(self, label="&Browse...")
                self.browse_btn.SetName("Browse Key Path")
                self.browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_key)
                row.Add(self.browse_btn, 0, wx.LEFT, 4)
                grid.Add(row, 1, wx.EXPAND)
            else:
                grid.Add(ctrl, 1, wx.EXPAND)

        right_sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 4)

        self.save_btn = wx.Button(self, label="&Save")
        self.save_btn.SetName("Save Site")
        right_sizer.Add(self.save_btn, 0, wx.ALL | wx.ALIGN_RIGHT, 4)

        main_sizer.Add(right_sizer, 2, wx.EXPAND | wx.ALL, 4)

        self.SetSizer(main_sizer)

        self.protocol_choice.SetSelection(0)

        self.site_list.Bind(wx.EVT_LISTBOX, self._on_site_selected)
        self.add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self.connect_btn.Bind(wx.EVT_BUTTON, self._on_connect)
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save)

        self.site_list.SetFocus()

    def _refresh_site_list(self) -> None:
        self.site_list.Clear()
        for site in self._site_manager.sites:
            self.site_list.Append(site.name, site.id)

    def _on_site_selected(self, event: wx.CommandEvent) -> None:
        idx = self.site_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        site_id = self.site_list.GetClientData(idx)
        site = self._site_manager.get(site_id)
        if site:
            self._selected_site = site
            self._populate_form(site)

    def _populate_form(self, site: Site) -> None:
        self.name_text.SetValue(site.name)
        proto_idx = (
            ["sftp", "ftp", "ftps"].index(site.protocol)
            if site.protocol in ["sftp", "ftp", "ftps"]
            else 0
        )
        self.protocol_choice.SetSelection(proto_idx)
        self.host_text.SetValue(site.host)
        self.port_text.SetValue(str(site.port) if site.port else "")
        self.username_text.SetValue(site.username)
        self.password_text.SetValue(site.password)
        self.key_path_text.SetValue(site.key_path)
        self.initial_dir_text.SetValue(site.initial_dir)

    def _on_add(self, event: wx.CommandEvent) -> None:
        site = Site(name="New Site")
        self._site_manager.add(site)
        self._refresh_site_list()
        self.site_list.SetSelection(self.site_list.GetCount() - 1)
        self._selected_site = site
        self._populate_form(site)
        self.name_text.SetFocus()
        self.name_text.SelectAll()

    def _on_remove(self, event: wx.CommandEvent) -> None:
        if self._selected_site:
            self._site_manager.remove(self._selected_site.id)
            self._selected_site = None
            self._refresh_site_list()

    def _on_save(self, event: wx.CommandEvent) -> None:
        if not self._selected_site:
            return
        self._update_site_from_form(self._selected_site)
        self._site_manager.update(self._selected_site)
        self._refresh_site_list()

    def _update_site_from_form(self, site: Site) -> None:
        site.name = self.name_text.GetValue().strip()
        site.protocol = self.protocol_choice.GetStringSelection()
        site.host = self.host_text.GetValue().strip()
        port_str = self.port_text.GetValue().strip()
        site.port = int(port_str) if port_str else 0
        site.username = self.username_text.GetValue().strip()
        site.password = self.password_text.GetValue()
        site.key_path = self.key_path_text.GetValue().strip()
        site.initial_dir = self.initial_dir_text.GetValue().strip() or "/"

    def _on_connect(self, event: wx.CommandEvent) -> None:
        if self._selected_site:
            self._connect_requested = True
            self.EndModal(wx.ID_OK)

    def _on_browse_key(self, event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self,
            "Select Key File",
            wildcard="All files (*.*)|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.key_path_text.SetValue(dlg.GetPath())

    @property
    def connect_requested(self) -> bool:
        return self._connect_requested

    @property
    def selected_site(self) -> Site | None:
        return self._selected_site
