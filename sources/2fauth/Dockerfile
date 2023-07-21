FROM 2fauth/2fauth:4.1.0

ARG UID=1000
ARG GID=1000

USER 0

RUN apk add --update --no-cache php81-pgsql php81-pdo_pgsql

USER ${UID}:${GID}
