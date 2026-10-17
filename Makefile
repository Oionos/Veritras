export BUILDX_CONFIG ?= $(CURDIR)/.testing/buildx
TEST_COMPOSE = docker compose -f compose.testing.yml
ifneq ($(strip $(CODEX_PROXY_CERT)),)
TEST_COMPOSE += -f compose.testing.cloud.yml
endif

.PHONY: testing-up testing-check testing-status testing-logs testing-down testing-reset
testing-up:
	$(TEST_COMPOSE) up --build -d --wait --wait-timeout 180
testing-check:
	$(TEST_COMPOSE) --profile checks run --build --no-deps --rm smoke
testing-status:
	$(TEST_COMPOSE) ps
testing-logs:
	$(TEST_COMPOSE) logs --tail 60
testing-down:
	$(TEST_COMPOSE) down
# Destructive only to this explicitly named disposable testing project.
testing-reset:
	$(TEST_COMPOSE) down --volumes
