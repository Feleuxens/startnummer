# Nginx reverse proxy

Serve Startnummer at the root of a dedicated hostname, such as
`startnummer.example.org`. The web image serves the UI and `/api/` together;
route both to port 8000. A URL prefix such as `/startnummer/` is not supported by
the current frontend. Analysis progress uses polling, so no WebSocket setup is needed.

The examples assume Nginx terminates HTTPS. Keep your existing certificate
management and TLS configuration if the server already has them. Replace the
hostname, certificate paths, and upstream address for your installation.

## Nginx on the host

The default Compose configuration publishes the API on `127.0.0.1:8000`. Keep
`STARTNUMMER_BIND_HOST=127.0.0.1` and `STARTNUMMER_COOKIE_SECURE=1` in `.env.docker`.
The worker and PostgreSQL stay private.

Put this configuration in an Nginx file included from its `http` context, commonly
`/etc/nginx/conf.d/startnummer.conf` or a site under `sites-enabled`:

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

`Host $http_host` preserves the public hostname and any explicit port. Startnummer
compares it with the browser's `Origin` for writes. The forwarded client address
is replaced at this single edge proxy rather than accepting a client-supplied chain.
For an additional trusted proxy or CDN in front of Nginx, configure Nginx's real-IP
handling for that topology before using `$remote_addr` as the client address.

Request/response buffering is disabled to stream uploads and photo responses
without Nginx spooling them to proxy temporary files. The location also disables
an inherited proxy cache, including for authenticated review responses.
These settings concern Nginx; the API still stores imported originals and handles
its own temporary upload files. See the
[Nginx proxy directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

### Trusted proxy address

With a native API on the same host, `FORWARDED_ALLOW_IPS=127.0.0.1` covers this
upstream connection. Compose instead maps `STARTNUMMER_TRUSTED_PROXY_IPS` to that
Uvicorn setting. Docker may present host-originated connections to the API as a
bridge gateway address, rather than loopback.

Check the peer address on a test request in the API access log. Inspect its
networks to identify the corresponding gateway:

```sh
docker inspect "$(docker compose --env-file .env.docker -f compose.yaml ps -q api)" \
  --format '{{json .NetworkSettings.Networks}}'
```

For example, if the observed peer is `172.28.0.1`, set:

```dotenv
STARTNUMMER_TRUSTED_PROXY_IPS=127.0.0.1,172.28.0.1
```

Use the actual address, not this example. Recreate the API after changing its
environment. Avoid `*`; trust the proxy peer or a dedicated proxy subnet.
Uvicorn documents this as
[`--forwarded-allow-ips`](https://uvicorn.dev/settings/#http).

## Nginx in another Docker Compose project

Connect only Nginx and the API to an external proxy network. The following example
uses a fixed Nginx address so the API can trust that peer precisely. Choose an
unused subnet and adjust both configurations if this range overlaps your networks:

```sh
docker network create --subnet 172.30.20.0/24 startnummer-proxy
```

Add this to your existing Nginx Compose configuration, retaining its other
networks, volumes, published ports, and certificate configuration:

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

The reset removes the host port; an empty list alone does not remove inherited
ports. Use a recent Compose v2 release; Compose 2.24.4 or newer supports this
override. See [Compose merge rules](https://docs.docker.com/reference/compose-file/merge/).
Set this in Startnummer's `.env.docker`:

```dotenv
STARTNUMMER_COOKIE_SECURE=1
STARTNUMMER_TRUSTED_PROXY_IPS=172.30.20.2
```

Use the same Nginx server blocks, replacing the upstream block with the following.
This variant requires Nginx 1.28 or newer:

```nginx
upstream startnummer_backend {
    zone startnummer_backend 64k;
    resolver 127.0.0.11 valid=30s ipv6=off;
    server startnummer-api:8000 resolve;
}
```

Docker DNS resolves the API's unique network alias. The `resolve` option refreshes
it when an API replacement gets a new address; see
[Nginx upstream resolution](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#resolve).
Inside the Nginx container, `127.0.0.1:8000` would refer to Nginx's own container.

Include the proxy override on every Startnummer start/update. For the Intel server:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.intel.yaml -f compose.proxy.yaml config --quiet
docker compose --env-file .env.docker -f compose.yaml -f compose.intel.yaml -f compose.proxy.yaml up -d --no-build --wait
```

Use the normal [deployment/update procedure](docker.md#updates-and-status) for
pulling or building images and applying migrations. Finish active face review
before replacing the worker. Bring up the proxy network before starting either
project, and recreate Nginx when changing its network configuration.

## Upload limits and timeouts

The `2100m` request limit leaves room above the default 2 GiB batch-photo limit.
If you change import limits in Administration, adjust Nginx's limit as well. It
covers the whole HTTP request, including roster data and multipart overhead.
Nginx's default limit is only 1 MiB. Its
[body-size and timeout directives](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size)
describe these separately from the application's limits.

The body/send timeouts allow pauses during large uploads. The read timeout allows
time for synchronous gallery imports and publishing; adjust it to observed batch
sizes and gallery response times. Analysis itself is queued and does not hold a
request open for the whole inference run.

## Check the installation

For host Nginx, validate before reloading:

```sh
sudo nginx -t
sudo systemctl reload nginx
curl --fail --silent --show-error https://startnummer.example.org/api/health/ready
```

For containerized Nginx, run `nginx -t` and `nginx -s reload` through `docker compose
exec nginx` in its own project. Check sign-in and a small upload through the public
HTTPS URL. The readiness endpoint checks API/database/storage, not gallery access
or model execution.

| Symptom | Check |
| --- | --- |
| Nginx returns 413 on upload | Raise `client_max_body_size` above the complete request size. |
| Startnummer rejects file/batch size | Check import limits in Administration. |
| Sign-in or saving returns 403 | Preserve the public `Host`, `Origin`, and `X-Requested-With` headers. |
| Sign-in succeeds but the next request is 401 | Use HTTPS with secure cookies; check the browser's cookie rejection reason. |
| Access logs show the proxy address | Set the trusted proxy peer correctly and recreate the API. |
| Nginx returns 502 | Check API health, port/network membership, and Docker DNS resolution. |
| Nginx returns 504 during import/publish | Check API/gallery logs and request duration; the API may still be processing. |

After an uncertain publishing timeout, use **Check gallery outcome** before
retrying the write.
