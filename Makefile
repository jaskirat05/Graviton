SHELL := /bin/bash

VERSION ?= dev
REGISTRY ?=
REGISTRY_PREFIX := $(if $(REGISTRY),$(REGISTRY)/)
BACKEND_IMAGE ?= $(REGISTRY_PREFIX)graviton-backend:$(VERSION)
FRONTEND_IMAGE ?= $(REGISTRY_PREFIX)graviton-frontend:$(VERSION)
COMPOSE_PROFILES ?= --profile infra --profile app

.PHONY: up dev down build release push

up:
	BACKEND_IMAGE=$(BACKEND_IMAGE) FRONTEND_IMAGE=$(FRONTEND_IMAGE) docker compose $(COMPOSE_PROFILES) up -d

dev:
	BACKEND_IMAGE=graviton-backend:dev FRONTEND_IMAGE=graviton-frontend:dev docker compose $(COMPOSE_PROFILES) -f docker-compose.yml -f docker-compose.dev.yml up

down:
	docker compose --profile infra --profile app down

build:
	BACKEND_IMAGE=$(BACKEND_IMAGE) FRONTEND_IMAGE=$(FRONTEND_IMAGE) docker compose build graviton-worker graviton-frontend

release: build
	@if [ "$(VERSION)" = "dev" ]; then echo "Set VERSION=vX.Y.Z"; exit 1; fi
	$(MAKE) push VERSION=$(VERSION) REGISTRY=$(REGISTRY)

push:
	@if [ -z "$(REGISTRY)" ]; then echo "Set REGISTRY (for example ghcr.io/<org>)"; exit 1; fi
	docker push $(BACKEND_IMAGE)
	docker push $(FRONTEND_IMAGE)
