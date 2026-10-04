FROM node:22-alpine AS build
WORKDIR /app
RUN npm install -g pnpm@11.19.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM caddy:2-alpine
# The upstream binary carries CAP_NET_BIND_SERVICE for ports 80/443. This
# site only listens on 8080; remove that file capability so cap_drop: ALL
# does not make execve fail with EPERM before Caddy starts.
RUN apk add --no-cache --virtual .fl-build-tools libcap \
    && if getcap /usr/bin/caddy | grep -q .; then setcap -r /usr/bin/caddy; fi \
    && test -z "$(getcap /usr/bin/caddy)" \
    && apk del .fl-build-tools
RUN addgroup -S -g 10001 firstlook && adduser -S -u 10001 -G firstlook firstlook \
    && mkdir -p /var/log/firstlook /data/caddy \
    && chown -R firstlook:firstlook /var/log/firstlook /data/caddy
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
USER 10001:10001
EXPOSE 8080
