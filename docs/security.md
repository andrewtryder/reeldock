# Security Guidelines

Security is a primary consideration when self-hosting web applications. This guide describes the built-in security features of `reeldock` and best practices for secure deployment.

## 1. Localhost Binding (Default)

By default, the `docker-compose.yml` file binds the web port only to localhost:

```yaml
    ports:
      - "127.0.0.1:8080:8080"
```

This prevents external machines on your local network (LAN) or the public internet from accessing the application until you explicitly choose to expose it.

---

## 2. Authentication Configuration

If you expose the application beyond your localhost (e.g. by changing the port binding to `"8080:8080"`), you must enable authentication.

Preferred: open **Settings → Security** and enable sign-in with a username and password. Changes apply on the next request (no container restart). Leave `AUTH_PASSWORD` unset in `.env` so the UI can own the secret.

You can still bootstrap auth from `.env` (`AUTH_ENABLED=true` plus username/password). Setting `AUTH_ENABLED=true` without credentials still refuses to start.

> [!WARNING]
> Do not expose the application to the internet or your general LAN without enabling Basic Authentication and setting a strong password.
>
> If you change the port binding to `"8080:8080"`, enable auth first.

Pair browsers from **Settings → Pair a Browser**. Codes expire in five minutes and are one-use. Device tokens are stored as SHA-256 hashes. Store-installed extensions need a browser-trusted HTTPS origin; loopback HTTP is for local unpacked testing. This does not resist a fully compromised Docker host.

Legacy `EXTENSION_API_TOKEN` still works if configured; it is not created in the UI.

---

## 3. Reverse Proxy Routing

We strongly recommend routing all external/public traffic through a secure reverse proxy rather than exposing the application port directly to the internet.

Common reverse proxies include:
* **Caddy** / **Nginx** / **Traefik**
* **Cloudflare Tunnels** (highly recommended for simple, secure WAN access without opening router ports)

Ensure your reverse proxy is configured with valid SSL/TLS certificates (e.g. via Let's Encrypt) so that authentication credentials are encrypted in transit.

---

## 4. Path Traversal Protection

`reeldock` contains built-in validation to prevent path traversal vulnerabilities.
* The application validates all destination folder paths and output filenames.
* Any request to write to a path outside the configured `OUTPUT_ROOT` directory will be rejected with an HTTP 400 bad request error.

---

## 5. Proxmox Scripts Warning

Our automated Proxmox VE installation script is provided as a convenience.

> [!CAUTION]
> **Do not run arbitrary scripts downloaded from the internet directly as `root` on your Proxmox VE hypervisor.**
> Always review the code of `proxmox-install.sh` and `guest-install.sh` in the repository before executing them on your host.
