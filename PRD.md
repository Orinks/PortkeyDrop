# Portkey Drop - Product Requirements Document

## Overview
Portkey Drop is an accessible file transfer client built for screen reader users. It provides a clean, keyboard-driven interface for connecting to remote servers via FTP, SFTP, FTPS, SCP, and WebDAV. Built with wxPython and Prismatoid for full NVDA/JAWS compatibility.

## Why This Exists
Existing file transfer clients (FileZilla, WinSCP, Cyberduck) rely heavily on visual cues (drag-and-drop, tree views with icons) that don't translate well to assistive technology. Portkey Drop uses a dual-pane layout with properly labeled standard ListCtrl panes ("Local Files" / "Remote Files") that screen readers like NVDA and JAWS handle naturally. Each pane is a standard list control with SetName(), so screen readers announce which pane has focus. Every action is keyboard-accessible and every state change is announced.

## Supported Protocols
1. **SFTP** (SSH File Transfer Protocol) - Primary, most secure, most common
2. **FTP** (File Transfer Protocol) - Legacy support, still widely used
3. **FTPS** (FTP over SSL/TLS) - Encrypted FTP
4. **SCP** (Secure Copy Protocol) - Fast SSH-based transfers
5. **WebDAV** (Web Distributed Authoring) - HTTP-based, used by cloud services

## Core Features

### Connection Management
- Site Manager: save/edit/delete connection profiles
- Quick Connect bar: host, port, username, password/key
- Connection history (recent connections)
- SSH key authentication support
- Automatic protocol detection from URL schemes

### File Browser
- Dual-pane layout: Local Files (left) and Remote Files (right)
- Each pane is a labeled wx.ListCtrl — screen readers announce "Local Files" or "Remote Files" on focus
- Tab switches between panes
- Navigate files with arrow keys in either pane
- File details announced: name, size, type, modified date, permissions
- Path bar above each pane showing current directory
- Go to parent directory (Backspace) in whichever pane has focus
- Quick search/filter within current directory (Ctrl+F)
- Local pane starts at user's home directory

### Transfer Operations
- Upload selected local file(s) to current remote directory (Ctrl+U, no file picker needed)
- Download selected remote file(s) to current local directory (Ctrl+D, no save-as dialog needed)
- Transfer queue with progress announcements
- Resume interrupted transfers
- Batch transfers (select multiple files)
- Background transfers with speech notifications

### File Operations
- Rename, delete, create directory
- View/edit file permissions (chmod)
- View file properties (size, dates, owner)
- Copy/move files on remote server

### Accessibility
- All actions via keyboard shortcuts
- Speech announcements for: connection status, directory changes, transfer progress, errors
- No reliance on visual-only indicators
- Configurable speech rate/volume/verbosity
- Sounds for: connected, disconnected, transfer complete, error

## Settings (Sensible Defaults)

### Connection Defaults
- Default protocol: SFTP (most secure)
- Default port: 22 (SFTP), 21 (FTP), 990 (FTPS), 443 (WebDAV)
- Connection timeout: 30 seconds
- Keepalive interval: 60 seconds
- Max retries: 3
- Default transfer mode: Binary
- SSH host key verification: Ask on first connect, remember after

### Transfer Defaults
- Concurrent transfers: 2
- Overwrite existing: Ask
- Resume partial: Yes
- Preserve timestamps: Yes
- Follow symlinks: No
- Default local download dir: ~/Downloads

### UI Defaults
- Announce file count on directory load: Yes
- Announce transfer progress: Every 25%
- Show hidden files: No
- Sort by: Name ascending
- Date format: Relative ("2 days ago") with full date on request

## Architecture
- **UI Layer**: wxPython + Prismatoid (screen reader announcements)
- **Protocol Layer**: Abstract `TransferClient` interface per protocol
  - `paramiko` for SFTP/SCP
  - `ftplib` (stdlib) for FTP
  - `ftplib` with SSL context for FTPS
  - `requests` + `webdavlib` for WebDAV
- **Settings**: JSON config at `~/.portkeydrop/settings.json`
- **Site Manager**: JSON at `~/.portkeydrop/sites.json` (passwords encrypted)
- **Transfer Queue**: Threaded background transfers with progress callbacks

## Keyboard Shortcuts
- `Ctrl+N`: Quick Connect
- `Ctrl+S`: Site Manager
- `Ctrl+U`: Upload files
- `Ctrl+D`: Download selected
- `Ctrl+R`: Refresh directory
- `Delete`: Delete selected
- `F2`: Rename selected
- `Ctrl+Shift+N`: New directory
- `Backspace`: Parent directory
- `Enter`: Open directory / download file
- `Ctrl+Q`: Disconnect
- `Ctrl+I`: File properties
- `Ctrl+T`: Transfer queue
- `/` or `Ctrl+F`: Filter/search files
