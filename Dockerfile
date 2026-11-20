FROM node:22-alpine

WORKDIR /app

COPY server.mjs index.html ua.html ./

EXPOSE 3000

CMD ["node", "server.mjs"]
