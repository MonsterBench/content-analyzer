# Frontend Dockerfile (Next.js)
FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

RUN npm run build

ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "start"]
