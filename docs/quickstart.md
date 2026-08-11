# Quickstart Guide

This guide will walk you through setting up `reeldock` using Docker Compose.

## 1. Prerequisites

Ensure you have Docker and Docker Compose v2 installed on your system.

## 2. Clone the Repository

```bash
git clone https://github.com/andrewtryder/reeldock.git
cd reeldock
```

## 3. Configure the Environment

Copy the example environment file to `.env`:

```bash
cp .env.example .env
```

Open `.env` in a text editor and set `HOST_AUDIOBOOKS_DIR` to the directory on your host machine that Audiobookshelf scans:

```env
# Path on your Docker host (Mac or Linux)
HOST_AUDIOBOOKS_DIR=/mnt/podcasts
```
Compose loads `.env` into the app/worker containers. Fresh Docker installs can leave `AUTH_PASSWORD`, `ABS_API_TOKEN`, and `EXTENSION_API_TOKEN` unset and configure auth, Audiobookshelf, and browser pairing from the Settings page.

To enable the extension API from env and pair from the UI:

```env
EXTENSION_API_ENABLED=true
# EXTENSION_PUBLIC_URL=https://reeldock.example.com
```

Or enable both from Settings after the first start. Pairing is the recommended browser path; `EXTENSION_API_TOKEN` is legacy. See [Security](security.md).

*(Optional)* Restrict permissions or configure Audiobookshelf scan triggers in `.env` as well. See [Configuration Guide](configuration.md) for details.

## 4. Create Necessary Directories

Ensure the local storage directories for database files and configuration exist on the host:

```bash
mkdir -p data config
```

Ensure `HOST_AUDIOBOOKS_DIR` exists on the host and is writable. On macOS with a Synology or other network share, mount the share in Finder first so the path under `/Volumes/...` exists before starting Docker.

## 5. Start the Application

Optionally validate host paths before starting (recommended when using NAS mounts):

```bash
./scripts/check-docker-paths.sh && docker compose up -d
```

Or start the Docker Compose stack directly in detached mode:

```bash
docker compose up -d
```

This will pull the required images, build the custom application/worker container, and start the stack.

## 6. Access the Application

Verify that the application is running by visiting:

**`http://localhost:8080`**

*(Note: By default, the application binds only to localhost for security. See the [Security Guide](security.md) for details on exposing the app to your local network.)*
