FROM alpine:3.20

RUN apk add --no-cache \
      nginx php83 php83-fpm php83-pdo_mysql \
      python3 py3-psutil py3-yaml supervisor curl tzdata \
 && mkdir -p /var/log/app /var/log/php /run/nginx /var/www/app \
 && chown -R nobody:nobody /var/log/app /var/log/php

COPY nginx.conf        /etc/nginx/http.d/default.conf
COPY php-fpm.conf      /etc/php83/php-fpm.d/zz-ismas.conf
COPY supervisord.conf  /etc/supervisord.conf
COPY app/              /var/www/app/

EXPOSE 80
CMD ["supervisord", "-c", "/etc/supervisord.conf"]
