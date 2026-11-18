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

map "$request_method:$uri" $startnummer_upload_key {
    default "";
    ~^POST:/api/(batches|roster/preview)/?$ $server_name;
}

limit_conn_zone $startnummer_upload_key zone=startnummer_uploads:1m;

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

    # 2 GiB of photos plus 16 MiB for the rest of the import request.
    client_max_body_size 2064m;
    client_body_timeout 300s;
    limit_conn startnummer_uploads 2;
    limit_conn_status 429;

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

    location / {
        proxy_pass http://startnummer_backend;
    }

    location ~ ^/api/roster/preview/?$ {
        client_max_body_size 11m;
        proxy_pass http://startnummer_backend;
    }
}
```

`Host $http_host` preserves the public hostname and port for Startnummer's origin
checks. The proxy replaces forwarded client headers with the address it sees.
If a CDN or another proxy sits in front of Nginx, configure trusted real-IP
handling for that topology first.

Request and response buffering are disabled for this server. This lets the API
check the session as soon as the request headers arrive and avoids Nginx spooling
uploads and photo responses to its temporary files.
See the [Nginx proxy directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

### 3. Trust the proxy's actual address

For a native API on the same host, `FORWARDED_ALLOW_IPS=127.0.0.1` covers the
connection. Compose maps `STARTNUMMER_TRUSTED_PROXY_IPS` to that Uvicorn setting.
Docker may present host connections as a bridge gateway address instead.

If API access logs show the proxy address, inspect the container networks to
identify the peer that should be trusted:

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

Match the proxy's import body limit to **Maximum batch size** plus 16 MiB for
the roster, metadata, and multipart overhead. The default is `2064m`. Keep the
roster preview limit at `11m`, which includes 1 MiB above the 10 MiB roster limit.
Set these limits at the first proxy that accepts the request body. See the
[Nginx body-size directive](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size).

Keep `proxy_request_buffering off` for these routes when possible. If your proxy
buffers bodies, it can read and store them before Startnummer sees the headers.
Apply the size, concurrency, and body timeout limits at that proxy to bound its
temporary storage. The example allows two concurrent upload requests across batch
import and roster preview. It returns `429` for additional uploads while other
requests, such as batch polling, continue. See the
[Nginx connection limit](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html).

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

To verify the address used for sign-in limits, request `/api/health/ready`
through the public hostname from two networks. Compare the Nginx and API access
logs for those requests. The API should show the client address Nginx forwarded
for each request. If it shows the proxy's address for both, correct the trusted
proxy configuration before relying on the per-source limit.

| Symptom                                      | Check                                                                                            |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Nginx returns 413 on upload                  | Raise `client_max_body_size` above the full request size.                                        |
| Upload returns 429                          | Wait for a current import or roster preview to finish, then retry.                              |
| Startnummer rejects file/batch size          | Check import limits in Administration.                                                           |
| Sign-in or saving returns 403                | Preserve public `Host`, `Origin`, and `X-Requested-With` headers.                                |
| Sign-in succeeds but the next request is 401 | Use HTTPS with secure cookies; check the browser's cookie rejection reason.                      |
| Logs show only the proxy address             | Correct the trusted proxy peer and recreate the API.                                             |
| API readiness returns 503                    | Read database/storage status and check [storage access](operations.md#check-persistent-storage). |
| Nginx returns 502                            | Check API health, port/network membership, and Docker DNS.                                       |
| Import/publish returns 504                   | Check API/gallery logs and duration; processing may still be running.                            |

After an uncertain publishing timeout, use **Check gallery outcome** before
retrying the write.
