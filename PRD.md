# AccessiTransfer - Product Requirements Document

## Overview
AccessiTransfer is an accessible file transfer client built for screen reader users. It provides a clean, keyboard-driven interface for connecting to remote servers via FTP, SFTP, FTPS, SCP, and WebDAV. Built with wxPython and Prismatoid for full NVDA/JAWS compatibility.

## Why This Exists
Existing file transfer clients (FileZilla, WinSCP, Cyberduck) have dual-pane layouts that are difficult to navigate with screen readers. They rely heavily on visual cues (drag-and-drop, tree views with icons) that don't translate well to assistive technology. AccessiTransfer takes a single-pane, list-based approach where every action is keyboard-accessible and every state change is announced.

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
- Single-pane file list (not dual-pane like FileZilla)
- Navigate remote files with arrow keys
- File details announced: name, size, type, modified date, permissions
- Breadcrumb path bar showing current directory
- Go to parent directory (Backspace)
- Quick search/filter within current directory (type to filter)

### Transfer Operations
- Upload files/folders (from local file picker dialog)
- Download files/folders (to local directory picker)
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
- **Settings**: JSON config at `~/.accessitransfer/settings.json`
- **Site Manager**: JSON at `~/.accessitransfer/sites.json` (passwords encrypted)
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
