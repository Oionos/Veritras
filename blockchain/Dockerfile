# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim

WORKDIR /app

# Copy package files and install dependencies
COPY package*.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci

# Copy the rest of the Hardhat project
COPY . .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npx hardhat compile

# Expose the default Hardhat Network port
EXPOSE 8545

# Start the local Hardhat node, binding to all interfaces so it is accessible from other containers
CMD ["npx", "hardhat", "node", "--hostname", "0.0.0.0"]
