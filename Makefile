SHELL := /bin/bash

.PHONY: heroku-config-set heroku-config-set-dry-run

heroku-config-set:
	@if [[ -n "$(APP)" ]]; then \
		./scripts/heroku-config-set-from-env.sh --app "$(APP)"; \
	else \
		./scripts/heroku-config-set-from-env.sh; \
	fi

heroku-config-set-dry-run:
	@if [[ -n "$(APP)" ]]; then \
		./scripts/heroku-config-set-from-env.sh --dry-run --app "$(APP)"; \
	else \
		./scripts/heroku-config-set-from-env.sh --dry-run; \
	fi
