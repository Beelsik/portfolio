FROM node:22-alpine

RUN apk add --no-cache python3

WORKDIR /app

COPY server.mjs index.html ua.html ./
COPY ledgerguard ./ledgerguard

ENV PYTHONPATH=/app/ledgerguard/src

EXPOSE 3000

CMD ["node", "server.mjs"]
