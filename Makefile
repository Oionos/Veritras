export BUILDX_CONFIG ?= $(CURDIR)/.testing/buildx
TEST_COMPOSE = docker compose $(if $(TESTING_COMPOSE_PROJECT),-p $(TESTING_COMPOSE_PROJECT)) -f compose.testing.yml
ifneq ($(strip $(CODEX_PROXY_CERT)),)
TEST_COMPOSE += -f compose.testing.cloud.yml
endif

.PHONY: testing-up testing-build testing-check testing-status testing-logs testing-down testing-reset testing-restart-api testing-indexer-check
testing-up:
	$(TEST_COMPOSE) up -d --wait --wait-timeout 180
testing-build:
	$(TEST_COMPOSE) --profile checks build
testing-check:
	$(TEST_COMPOSE) --profile checks run --no-deps --rm smoke
testing-restart-api:
	$(TEST_COMPOSE) restart backend
testing-status:
	$(TEST_COMPOSE) ps
testing-logs:
	$(TEST_COMPOSE) logs --tail 60
testing-down:
	$(TEST_COMPOSE) down
# Destructive only to this explicitly named disposable testing project.
testing-reset:
	$(TEST_COMPOSE) down --volumes

# Reorg regression only: refuses hosted APIs and non-Hardhat chains.
testing-indexer-check:
	$(TEST_COMPOSE) --profile checks run --no-deps --rm smoke npx hardhat run scripts/check-durable-indexer.ts --network localhost
