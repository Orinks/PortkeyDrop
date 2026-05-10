from __future__ import annotations

from unittest.mock import MagicMock

from tests._wx_stub import load_module_with_fake_wx


class FakeListBox:
    def __init__(self, *_args, **_kwargs):
        self.items: list[str] = []
        self.selection = -1
        self.Bind = MagicMock()
        self.SetFocus = MagicMock()

    def InsertItems(self, items, pos):
        for offset, item in enumerate(items):
            self.items.insert(pos + offset, item)

    def SetString(self, index, value):
        self.items[index] = value

    def GetSelection(self):
        return self.selection

    def SetSelection(self, index):
        self.selection = index

    def Clear(self):
        self.items.clear()
        self.selection = -1

    def Delete(self, index):
        del self.items[index]


class FakeKeyEvent:
    def __init__(self, key_code):
        self.key_code = key_code
        self.skipped = False

    def GetKeyCode(self):
        return self.key_code

    def Skip(self):
        self.skipped = True


def test_macos_report_list_uses_listbox_with_complete_row_text(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.accessible_list", monkeypatch)
    fake_wx.Platform = "__WXMAC__"
    fake_wx.WXK_RETURN = 13
    fake_wx.WXK_NUMPAD_ENTER = 370
    fake_wx.EVT_LISTBOX_DCLICK = object()

    listbox = FakeListBox()
    fake_wx.ListBox = MagicMock(return_value=listbox)

    report = module.create_report_list(
        MagicMock(),
        style=fake_wx.LC_REPORT | fake_wx.LC_SINGLE_SEL,
        row_formatter=module.file_row_text,
    )
    report.InsertColumn(0, "Name", width=200)
    report.InsertColumn(1, "Size", width=80)
    report.InsertColumn(2, "Type", width=70)
    report.InsertColumn(3, "Modified", width=130)
    report.InsertColumn(4, "Permissions", width=100)

    row = report.InsertItem(0, "archive.zip")
    report.SetItem(row, 1, "42 MB")
    report.SetItem(row, 2, "File")
    report.SetItem(row, 3, "2026-05-02 10:00")
    report.SetItem(row, 4, "rw-r--r--")

    assert report.window is listbox
    assert listbox.items == [
        "archive.zip, File, size 42 MB, modified 2026-05-02 10:00, permissions rw-r--r--"
    ]
    assert report.GetItemText(0, 0) == "archive.zip"
    assert report.GetItemText(0, 3) == "2026-05-02 10:00"


def test_file_row_text_announces_name_before_directory_type(monkeypatch):
    module, _ = load_module_with_fake_wx("portkeydrop.accessible_list", monkeypatch)

    assert module.file_row_text(["Projects", "", "Directory"], []) == "Projects, Directory"


def test_report_list_passes_through_to_listctrl_off_macos(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.accessible_list", monkeypatch)
    fake_wx.Platform = "__WXMSW__"

    listctrl = MagicMock(name="listctrl")
    listctrl.InsertItem.return_value = 4
    listctrl.GetItemText.return_value = "cell"
    listctrl.GetItemCount.return_value = 3
    listctrl.GetFirstSelected.return_value = 2
    listctrl.GetFocusedItem.return_value = 1
    listctrl.custom_attr = "forwarded"
    fake_wx.ListCtrl = MagicMock(return_value=listctrl)

    report = module.create_report_list(MagicMock(), style=fake_wx.LC_REPORT)
    assert report.window is listctrl

    report.InsertColumn(0, "Name", width=200)
    assert report.InsertItem(1, "file.txt") == 4
    report.SetItem(4, 1, "42 MB")
    assert report.GetItemText(4, 1) == "cell"
    assert report.GetItemCount() == 3
    report.DeleteAllItems()
    report.DeleteItem(2)
    assert report.GetFirstSelected() == 2
    assert report.GetFocusedItem() == 1
    report.Select(2, False)
    report.Focus(1)
    report.Bind(fake_wx.EVT_CONTEXT_MENU, MagicMock())
    report.SetFocus()
    assert report.custom_attr == "forwarded"

    listctrl.InsertColumn.assert_called_once_with(0, "Name", width=200)
    listctrl.SetItem.assert_called_once_with(4, 1, "42 MB")
    listctrl.DeleteAllItems.assert_called_once_with()
    listctrl.DeleteItem.assert_called_once_with(2)
    listctrl.Select.assert_called_once_with(2, False)
    listctrl.Focus.assert_called_once_with(1)
    listctrl.Bind.assert_called_once()
    listctrl.SetFocus.assert_called_once_with()


def test_macos_report_list_preserves_selection_api(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.accessible_list", monkeypatch)
    fake_wx.Platform = "__WXMAC__"
    fake_wx.EVT_LISTBOX_DCLICK = object()

    listbox = FakeListBox()
    fake_wx.ListBox = MagicMock(return_value=listbox)

    report = module.create_report_list(MagicMock(), style=fake_wx.LC_REPORT)
    report.InsertColumn(0, "File")
    report.InsertItem(0, "a.txt")
    report.InsertItem(1, "b.txt")

    report.Select(1)
    assert report.GetFirstSelected() == 1
    assert report.GetFocusedItem() == 1

    report.DeleteItem(1)
    assert report.GetItemCount() == 1
    assert report.GetFocusedItem() == -1


def test_macos_report_list_handles_empty_rows_and_out_of_range_cells(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.accessible_list", monkeypatch)
    fake_wx.Platform = "__WXMAC__"

    listbox = FakeListBox()
    fake_wx.ListBox = MagicMock(return_value=listbox)

    report = module.create_report_list(MagicMock(), style=fake_wx.LC_REPORT)
    row = report.InsertItem(5, "lonely.txt")

    assert row == 0
    assert listbox.items == [""]
    assert report.GetItemText(99, 0) == ""
    assert report.GetItemText(0, 99) == ""

    report.SetItem(1, 2, "Directory")
    assert report.GetItemCount() == 2
    assert report.GetItemText(1, 2) == "Directory"

    report.Focus(1)
    assert report.GetFocusedItem() == 1
    report.Select(1, False)
    assert report.GetFirstSelected() == -1
    assert report.GetFocusedItem() == 1
    report.DeleteAllItems()
    assert report.GetItemCount() == 0
    assert report.GetFocusedItem() == -1


def test_macos_report_list_activation_and_key_bindings(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.accessible_list", monkeypatch)
    fake_wx.Platform = "__WXMAC__"
    fake_wx.WXK_RETURN = 13
    fake_wx.WXK_NUMPAD_ENTER = 370
    fake_wx.EVT_LISTBOX_DCLICK = object()

    listbox = FakeListBox()
    fake_wx.ListBox = MagicMock(return_value=listbox)
    handler = MagicMock()

    report = module.create_report_list(MagicMock(), style=fake_wx.LC_REPORT)
    report.InsertColumn(0, "File")
    report.InsertItem(0, "a.txt")
    report.Bind(fake_wx.EVT_LIST_ITEM_ACTIVATED, handler)

    assert listbox.Bind.call_count == 2
    double_click_event, double_click_handler = listbox.Bind.call_args_list[0].args
    assert double_click_event is fake_wx.EVT_LISTBOX_DCLICK
    assert double_click_handler is handler

    char_event, char_handler = listbox.Bind.call_args_list[1].args
    assert char_event is fake_wx.EVT_CHAR_HOOK

    enter = FakeKeyEvent(13)
    char_handler(enter)
    handler.assert_called_once_with(enter)
    assert not enter.skipped

    other = FakeKeyEvent(65)
    char_handler(other)
    assert other.skipped

    key_handler = MagicMock()
    report.Bind(fake_wx.EVT_KEY_DOWN, key_handler)
    assert listbox.Bind.call_args.args == (fake_wx.EVT_CHAR_HOOK, key_handler)

    context_handler = MagicMock()
    report.Bind(fake_wx.EVT_CONTEXT_MENU, context_handler)
    assert listbox.Bind.call_args.args == (fake_wx.EVT_CONTEXT_MENU, context_handler)
