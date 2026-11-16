# Serve Startnummer through Nginx

Use a dedicated hostname such as `startnummer.example.org` and serve the app at
its root. The same upstream serves the UI and `/api/`. A URL prefix such as
`/startnummer/` is unsupported. Analysis uses polling and needs no WebSocket setup.

The examples assume you already manage HTTPS certificates with Nginx. Replace the
hostname, certificate paths, and upstream addresses for your installation.

## Nginx on the host

### 1. Keep the API on loopback

Set these values in `.env.docker`:

```dotenv
STARTNUMMER_BIND_HOST=127.0.0.1
STARTNUMMER_COOKIE_SECURE=1
```

The proxy will reach port 8000 on the host. Keep the worker and PostgreSQL private.

### 2. Add the server configuration

Put the following in a file included by Nginx's `http` context, such as
`/etc/nginx/conf.d/startnummer.conf`:

```nginx
upstream startnummer_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name startnummer.example.org;
    return 308 https://startnummer.example.org$request_uri;
}

server {
    listen 443 ssl;
    server_name startnummer.example.org;

    ssl_certificate /etc/letsencrypt/live/startnummer.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/startnummer.example.org/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Default app limit: 2 GiB of photo bytes, plus room for multipart fields.
    client_max_body_size 2100m;
    client_body_timeout 300s;

    location / {
        proxy_pass http://startnummer_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;

        proxy_connect_timeout 5s;
        proxy_send_timeout 300s;
        proxy_read_timeout 600s;
        proxy_next_upstream off;

        proxy_request_buffering off;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

`Host $http_host` preserves the public hostname and port for Startnummer's origin
checks. The proxy replaces forwarded client headers with the address it sees.
If a CDN or another proxy sits in front of Nginx, configure trusted real-IP
handling for that topology first.

Request/response buffering and inherited proxy caching are disabled for this
location. This avoids Nginx spooling uploads and photo responses to its temporary
files. The API still handles its own temporary uploads and stored originals.
See the [Nginx proxy directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

### 3. Trust the proxy's actual address

For a native API on the same host, `FORWARDED_ALLOW_IPS=127.0.0.1` covers the
connection. Compose maps `STARTNUMMER_TRUSTED_PROXY_IPS` to that Uvicorn setting.
Docker may present host connections as a bridge gateway address instead.

Check the API access log for the peer address and inspect the container networks:

```sh
docker inspect "$(docker compose --env-file .env.docker ps -q api)" \
  --format '{{json .NetworkSettings.Networks}}'
```

If the observed peer is `172.28.0.1`, for example, set:

```dotenv
STARTNUMMER_TRUSTED_PROXY_IPS=127.0.0.1,172.28.0.1
```

Use your actual address and recreate the API after editing its environment.
Trust only that peer or a dedicated proxy subnet; `*` trusts every sender.
See Uvicorn's [`--forwarded-allow-ips`](https://uvicorn.dev/settings/#http).

## Nginx in another Docker project

Connect the API and Nginx to an external proxy network. The example uses a fixed
Nginx address so the API can trust it precisely. Choose an unused subnet.

### 1. Create and attach the network

```sh
docker network create --subnet 172.30.20.0/24 startnummer-proxy
```

Add this network to your existing Nginx Compose configuration. Keep its current
networks, ports, certificate mounts, and other settings:

```yaml
services:
  nginx:
    networks:
      startnummer_proxy:
        ipv4_address: 172.30.20.2

networks:
  startnummer_proxy:
    external: true
    name: startnummer-proxy
```

Create `compose.proxy.yaml` beside Startnummer's `compose.yaml`:

```yaml
services:
  api:
    ports: !reset []
    networks:
      database: {}
      outbound: {}
      proxy:
        aliases: [startnummer-api]

networks:
  proxy:
    external: true
    name: startnummer-proxy
```

Use Compose 2.24.4 or newer for this override. `!reset []` removes the published
host port; an empty list alone keeps inherited ports. See
[Compose merge rules](https://docs.docker.com/reference/compose-file/merge/).
Use a distinct API alias if this network serves several Startnummer installations.

Set these values in Startnummer's `.env.docker`:

```dotenv
STARTNUMMER_COOKIE_SECURE=1
STARTNUMMER_TRUSTED_PROXY_IPS=172.30.20.2
```

### 2. Configure the upstream

Use the HTTPS server blocks above, replacing their upstream with this block.
It requires Nginx 1.28 or newer:

```nginx
upstream startnummer_backend {
    zone startnummer_backend 64k;
    resolver 127.0.0.11 valid=30s ipv6=off;
    server startnummer-api:8000 resolve;
}
```

Docker DNS resolves the alias and refreshes it when the API is replaced. Inside
the Nginx container, `127.0.0.1:8000` would refer to Nginx itself. See
[Nginx upstream resolution](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#resolve).

### 3. Start with the override

Include both files on every Startnummer start, pull, or update command:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.proxy.yaml config --quiet
docker compose --env-file .env.docker -f compose.yaml -f compose.proxy.yaml up -d --wait
```

Create the shared network before starting either project. Recreate Nginx after
changing its networks. Use the normal [update procedure](operations.md#update-startnummer)
when replacing Startnummer, and finish active face review first.

## Upload limits and timeouts

The example's `2100m` body limit leaves room above the default 2 GiB batch-photo
limit. It covers the entire request, including roster data and multipart overhead.
If you raise import limits in Administration, raise this limit too. Nginx's default
body limit is 1 MiB; see its
[body-size directive](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size).

Body/send timeouts allow pauses in large uploads. The read timeout allows time
for gallery imports and publishing; adjust it to the sizes and durations you see.
Queued analysis does not hold an HTTP request open for the whole inference run.

## Check the installation

For host Nginx, validate before reloading:

```sh
sudo nginx -t
sudo systemctl reload nginx
curl --fail --silent --show-error https://startnummer.example.org/api/health/ready
```

For containerized Nginx, run `nginx -t` and `nginx -s reload` through
`docker compose exec nginx` in its own project. Then sign in and upload a small
batch through the public HTTPS URL. Readiness checks API/database/storage;
it does not check gallery access or model execution.

| Symptom                                      | Check                                                                                            |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Nginx returns 413 on upload                  | Raise `client_max_body_size` above the full request size.                                        |
| Startnummer rejects file/batch size          | Check import limits in Administration.                                                           |
| Sign-in or saving returns 403                | Preserve public `Host`, `Origin`, and `X-Requested-With` headers.                                |
| Sign-in succeeds but the next request is 401 | Use HTTPS with secure cookies; check the browser's cookie rejection reason.                      |
| Logs show only the proxy address             | Correct the trusted proxy peer and recreate the API.                                             |
| API readiness returns 503                    | Read database/storage status and check [storage access](operations.md#check-persistent-storage). |
| Nginx returns 502                            | Check API health, port/network membership, and Docker DNS.                                       |
| Import/publish returns 504                   | Check API/gallery logs and duration; processing may still be running.                            |

After an uncertain publishing timeout, use **Check gallery outcome** before
retrying the write.
