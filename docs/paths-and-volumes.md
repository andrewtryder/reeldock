# Paths and Volumes Configuration

Understanding how directories map between the Docker host and the application containers is critical for proper setup. If paths are misconfigured, downloaded podcasts may not be visible to Audiobookshelf, or they may write to the container's temporary layer and be lost upon restart.

## The Path Model

When running under Docker, three paths must be configured:

1. **Host Path (`HOST_PODCASTS_DIR`)**: The directory path on your Docker host machine where podcasts are stored.
2. **Container Path (`CONTAINER_PODCASTS_DIR`)**: The mount path inside the Docker container (default is `/media/podcasts`). You typically do not need to change this.
3. **App Output Root (`OUTPUT_ROOT`)**: The path the application writes to.

> [!IMPORTANT]
> **Docker volume mounts must exist before the application can write to the share.**
> Ensure the directory specified in `HOST_PODCASTS_DIR` exists on your host machine and has the correct permissions (writable by the configured `PUID`/`PGID`, default 1000:1000).
> Run `./scripts/check-docker-paths.sh` on the host before `docker compose up` to catch mount problems early.

## Two Failure Layers

Volume problems can appear at two different stages:

1. **Host bind-mount failure (before containers start):** Docker cannot mount `HOST_PODCASTS_DIR` because the path is missing or not shared with Docker Desktop (common on macOS with `/Volumes/...` NAS paths). Compose fails with errors like `permission denied` on `/host_mnt/Volumes/...`. Fix by mounting the share on the host and adding `/Volumes` to Docker Desktop File Sharing. See [Docker Deployment Guide](deployment-docker.md#4-startup-mount-failures).

2. **In-container writability failure (after mount succeeds):** The path is mounted at `/media/podcasts`, but the container user (`PUID`/`PGID`) cannot write. The entrypoint preflight check exits with an error about `OUTPUT_ROOT`. Fix by aligning `PUID`/`PGID` with the share owner.

---

## Scenario Mapping Table

| Scenario | Host Path (`HOST_PODCASTS_DIR`) | Container Path (`CONTAINER_PODCASTS_DIR`) | App Output Root (`OUTPUT_ROOT`) |
| :--- | :--- | :--- | :--- |
| **Mac Docker Test** | `/Volumes/Synology/Media/Podcasts` | `/media/podcasts` | `/media/podcasts` |
| **Proxmox/Linux Docker VM** | `/mnt/podcasts` | `/media/podcasts` | `/media/podcasts` |
| **Native Linux (No Docker)** | `/mnt/podcasts` | *n/a (Not Applicable)* | `/mnt/podcasts` |

---

## Settings Page Behavior

The application allows you to configure the `OUTPUT_ROOT` dynamically from the **Settings** page in the web interface.

* **How it works**: Saving settings on the **Settings** page writes overrides to the `app_settings` database table. Environment variables and YAML configuration take precedence and lock their fields in the UI.
* **Important Note for Docker Users**: The settings path must be a valid, writable path **inside the running container** (normally `/media/podcasts`), **NOT the host path**. Configuring a path outside the mounted volumes (such as using your host path `/Volumes/...` or `/mnt/...` in the Settings page) will cause the application to write to the container's ephemeral filesystem, meaning your downloads will be deleted when the container restarts.
