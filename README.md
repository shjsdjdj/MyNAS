# MyNAS v3.1

A Windows-native personal cloud system for photo and file management.

---

## 📌 Overview

MyNAS is a local-first personal cloud system designed for Windows users to manage photos, videos, and files in a secure and structured way.

It focuses on:

- Photo management (like Apple Photos / Google Photos)
- Local storage indexing
- Timeline browsing
- Multi-storage support
- Secure asset-based architecture

---

## ✨ Features

### 📷 Photo System
- Masonry photo gallery
- Timeline view (year / month / day)
- Recent uploads
- Favorites system
- Fullscreen viewer
- EXIF metadata support

### 💾 Storage System
- Multiple Windows storage locations
- Automatic disk scanning
- Asset-based indexing system
- UUID file storage (no direct path exposure)

### 🔍 Scanner System
- Recursive disk scanning
- SHA256 hashing
- Duplicate detection (stable mode)
- Thumbnail generation (best-effort)
- EXIF extraction (best-effort)

### 🔐 Security
- JWT authentication
- HttpOnly cookie session
- User isolation
- Asset-level access control
- No direct filesystem exposure

### 🌐 UI
- Vue3 + Vite frontend
- iCloud Photos-like experience
- Responsive layout
- Chinese / English support

---

## 🧠 Architecture

- Backend: FastAPI
- Frontend: Vue3 + Vite
- Database: SQLite
- Storage: Local Windows filesystem
- Scheduler: APScheduler
- Core entity: Asset

Everything is built around the Asset model.

---

## 📁 Storage Model
E:\MyNAS\Storage<user_id><uuid>

- Files are never accessed directly
- All operations go through `asset_id`

---

## 📸 Screenshots

> (Add your screenshots here)

- Dashboard
- Photos
- Storage Manager

---

## ⚙️ Tech Stack

- FastAPI
- Vue3
- SQLite
- APScheduler
- JWT Authentication

---

## 🚀 Release Status

Version: v3.1.0

Status:
- Backend tests: PASS
- Frontend build: PASS
- Scanner: STABLE
- UI: PRODUCTION READY

---

## 📜 License

MIT License

---

## 🎯 Goal

To build a beautiful, secure, Windows-native personal cloud system like:

- Apple iCloud Photos
- Google Photos
- Immich

NOT a traditional NAS admin panel.
