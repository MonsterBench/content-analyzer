# Frontend Dockerfile (Next.js)
FROM node:20-slim AS base

# --- Dependencies ---
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# --- Build ---
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Backend URL for server-side rewrites (Railway internal networking)
ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=$BACKEND_URL

RUN npm run build

# --- Production ---
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV BACKEND_URL=http://localhost:8000

# Copy built app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public 2>/dev/null || true

EXPOSE 3000

CMD ["node", "server.js"]
