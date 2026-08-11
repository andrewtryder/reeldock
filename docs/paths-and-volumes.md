# Paths and Volumes Configuration

Understanding how directories map between the Docker host and the application containers is critical for proper setup. If paths are misconfigured, downloaded audiobooks may not be visible to Audiobookshelf, or they may write to the container's temporary layer and be lost upon restart.

## The Path Model

When running under Docker, configure **two** paths:

1. **Host Path (`HOST_AUDIOBOOKS_DIR`)**: The directory on your Docker host where Audiobookshelf media lives. Legacy alias: `HOST_PODCASTS_DIR`.
2. **Container Path (`OUTPUT_ROOT`)**: The mount path inside the container **and** the path the application writes to (default `/media/podcasts`). Compose uses this value as the bind-mount target. Legacy alias for the mount target only: `CONTAINER_PODCASTS_DIR`.

> [!IMPORTANT]
> **Docker volume mounts must exist before the application can write to the share.**
> Ensure the directory specified in `HOST_AUDIOBOOKS_DIR` exists on your host machine and has the correct permissions (writable by the configured `PUID`/`PGID`, default 1000:1000).
> Run `./scripts/check-docker-paths.sh` on the host before `docker compose up` to catch mount problems early.

## Two Failure Layers

Volume problems can appear at two different stages:

1. **Host bind-mount failure (before containers start):** Docker cannot mount `HOST_AUDIOBOOKS_DIR` because the path is missing or not shared with Docker Desktop (common on macOS with `/Volumes/...` NAS paths). Compose fails with errors like `permission denied` on `/host_mnt/Volumes/...`. Fix by mounting the share on the host and adding `/Volumes` to Docker Desktop File Sharing. See [Docker Deployment Guide](deployment-docker.md#4-startup-mount-failures).

2. **In-container writability failure (after mount succeeds):** The path is mounted at `/media/podcasts`, but the container user (`PUID`/`PGID`) cannot write. The entrypoint preflight check exits with an error about `OUTPUT_ROOT`. Fix by aligning `PUID`/`PGID` with the share owner.

---

## Scenario Mapping Table

| Scenario | Host Path (`HOST_AUDIOBOOKS_DIR`) | App / Mount Path (`OUTPUT_ROOT`) |
| :--- | :--- | :--- |
| **Mac Docker Test** | `/Volumes/Synology/Media/Podcasts` | `/media/podcasts` |
| **Proxmox/Linux Docker VM** | `/mnt/podcasts` | `/media/podcasts` |
| **Native Linux (No Docker)** | `/mnt/podcasts` | `/mnt/podcasts` |

---

## Settings Page Behavior

The application allows you to configure the `OUTPUT_ROOT` dynamically from the **Settings** page in the web interface.

* **How it works**: Saving settings on the **Settings** page writes overrides to the `app_settings` database table. Environment variables and YAML configuration take precedence and lock their fields in the UI.
* **Important Note for Docker Users**: The settings path must be a valid, writable path **inside the running container** (normally `/media/podcasts`), **NOT the host path**. Configuring a path outside the mounted volumes (such as using your host path `/Volumes/...` or `/mnt/...` in the Settings page) will cause the application to write to the container's ephemeral filesystem, meaning your downloads will be deleted when the container restarts.
