FROM node:22-alpine

RUN apk add --no-cache python3

WORKDIR /app

COPY server.mjs index.html ua.html case.html ua-case.html .nojekyll ./
COPY tasks ./tasks
COPY assets ./assets
COPY ledgerguard ./ledgerguard

ENV PYTHONPATH=/app/ledgerguard/src

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD wget -qO- http://127.0.0.1:3000/api/health >/dev/null || exit 1

CMD ["node", "--max-old-space-size=72", "server.mjs"]
