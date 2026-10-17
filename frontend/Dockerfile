# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS dependencies

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm install -g npm@11.17.0 && npm ci

# Copy source code
COPY . .

FROM dependencies AS testing
EXPOSE 3000
CMD ["node", "start-testing.mjs"]

FROM dependencies AS builder
ARG VITE_API_URL
ARG VITE_APP_ENV=production
ARG VITE_CHAIN_ID=11155111
ARG VITE_RPC_URL
ARG VITE_PRODUCT_REGISTRY_CONTRACT
ARG VITE_SHIPMENT_TRACKER_CONTRACT
ARG VITE_WALLETCONNECT_PROJECT_ID
ENV VITE_API_URL=$VITE_API_URL VITE_APP_ENV=$VITE_APP_ENV \
    VITE_CHAIN_ID=$VITE_CHAIN_ID VITE_RPC_URL=$VITE_RPC_URL \
    VITE_PRODUCT_REGISTRY_CONTRACT=$VITE_PRODUCT_REGISTRY_CONTRACT \
    VITE_SHIPMENT_TRACKER_CONTRACT=$VITE_SHIPMENT_TRACKER_CONTRACT \
    VITE_WALLETCONNECT_PROJECT_ID=$VITE_WALLETCONNECT_PROJECT_ID

# Build the application
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
