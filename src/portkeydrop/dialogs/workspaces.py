"""Dialogs for saved workspace bookmarks."""

from __future__ import annotations

import wx

from portkeydrop.workspaces import WorkspaceBookmark, WorkspaceManager


class WorkspaceDialog(wx.Dialog):
    """Select or remove a saved workspace bookmark."""

    def __init__(self, parent, manager: WorkspaceManager) -> None:
        super().__init__(parent, title="Open Workspace", size=(520, 360))
        self.SetName("Open Workspace")
        self._manager = manager
        self.selected_workspace: WorkspaceBookmark | None = None

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label="Saved &workspaces:")
        self.workspace_list = wx.ListBox(panel, style=wx.LB_SINGLE)
        self.workspace_list.SetName("Saved workspaces")
        if hasattr(label, "SetLabelFor"):
            label.SetLabelFor(self.workspace_list)

        sizer.Add(label, 0, wx.ALL, 8)
        sizer.Add(self.workspace_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.open_button = wx.Button(panel, wx.ID_OK, "&Open")
        self.remove_button = wx.Button(panel, label="&Remove")
        close_button = wx.Button(panel, label="&Close")
        button_sizer.Add(self.open_button, 0, wx.ALL, 4)
        button_sizer.Add(self.remove_button, 0, wx.ALL, 4)
        button_sizer.Add(close_button, 0, wx.ALL, 4)
        sizer.Add(button_sizer, 0, wx.ALL, 4)

        panel.SetSizer(sizer)
        root_sizer = wx.BoxSizer(wx.VERTICAL)
        root_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(root_sizer)

        self.open_button.Bind(wx.EVT_BUTTON, self._on_open)
        self.remove_button.Bind(wx.EVT_BUTTON, self._on_remove)
        close_button.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CANCEL))
        self.workspace_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_open)

        self._reload()

    def _reload(self) -> None:
        self._workspaces = self._manager.workspaces
        labels = [
            f"{workspace.name} - {workspace.local_path} -> {workspace.remote_path}"
            for workspace in self._workspaces
        ]
        self.workspace_list.Set(labels)
        if labels:
            self.workspace_list.SetSelection(0)

    def _selected_index(self) -> int:
        selection = self.workspace_list.GetSelection()
        return selection if selection != wx.NOT_FOUND else -1

    def _on_open(self, event) -> None:
        index = self._selected_index()
        if index < 0:
            return
        self.selected_workspace = self._workspaces[index]
        self.EndModal(wx.ID_OK)

    def _on_remove(self, event) -> None:
        index = self._selected_index()
        if index < 0:
            return
        workspace = self._workspaces[index]
        self._manager.remove(workspace.id)
        self.selected_workspace = None
        self._reload()


def create_workspace_dialog(parent, manager: WorkspaceManager) -> WorkspaceDialog:
    """Create the workspace picker dialog."""

    return WorkspaceDialog(parent, manager)
