SHELL := /bin/bash

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
IPERF_EXPORTER_IMAGE_NAME ?= ghcr.io/loktionovam/iperf_exporter_server
IPERF_OPERATOR_IMAGE_NAME ?= ghcr.io/loktionovam/iperf_operator
IPERF_EXPORTER_IMAGE_TAG ?= $(shell ./get_version.sh)
RELEASE_VERSION ?= $(patsubst v%,%,$(IPERF_EXPORTER_IMAGE_TAG))
GIT_BRANCH_NAME := $(shell git branch  --show-current)
DOCKER_COMPOSE ?= docker compose
DOCKER_COMPOSE_FILE ?= demo/docker-compose/docker-compose.yml
KIND_DEMO_CLUSTER_NAME ?= iperf-demo
KIND_DEMO_NAMESPACE ?= iperf-exporter-demo
KIND_DEMO_CONTEXT ?= kind-$(KIND_DEMO_CLUSTER_NAME)
KIND_DEMO_EXPORTER_IMAGE_NAME ?= iperf_exporter:kind-demo
KIND_DEMO_OPERATOR_IMAGE_NAME ?= iperf_operator:kind-demo
export

lint:
	$(PYTHON) -m black --check iperf_exporter iperf_operator tests
	$(PYTHON) -m ruff check iperf_exporter iperf_operator tests
	shellcheck demo/kind/*.sh get_version.sh

test-apps: lint
	$(PYTHON) -m pytest \
		--cov-report=xml \
		--cov-report=term-missing \
		--cov-fail-under=80 \
		--cov=iperf_exporter \
		--cov=iperf_operator \
		tests/apps -v
	$(PYTHON) -m coverage report --include='iperf_exporter/*' --fail-under=80
	$(PYTHON) -m coverage report --include='iperf_operator/*' --fail-under=80

fmt:
	$(PYTHON) -m black iperf_exporter iperf_operator tests
	$(PYTHON) -m ruff check --fix iperf_exporter iperf_operator tests

build-images:
	docker build --build-arg VERSION=$(IPERF_EXPORTER_IMAGE_TAG) -t $(IPERF_EXPORTER_IMAGE_NAME):$(IPERF_EXPORTER_IMAGE_TAG) .
	docker build -f Dockerfile.operator --build-arg VERSION=$(IPERF_EXPORTER_IMAGE_TAG) -t $(IPERF_OPERATOR_IMAGE_NAME):$(IPERF_EXPORTER_IMAGE_TAG) .

test-images:
	$(PYTHON) -m pytest tests/images -v

push-images:
	docker push $(IPERF_EXPORTER_IMAGE_NAME):$(IPERF_EXPORTER_IMAGE_TAG)
	docker push $(IPERF_OPERATOR_IMAGE_NAME):$(IPERF_EXPORTER_IMAGE_TAG)

build-charts:
	helm lint --strict helm/charts/iperf-exporter-server
	mkdir -p .cr-release-packages
	helm package helm/charts/iperf-exporter-server \
		--version $(RELEASE_VERSION) \
		--app-version $(IPERF_EXPORTER_IMAGE_TAG) \
		--destination .cr-release-packages

validate-manifests:
	kubectl kustomize demo/kind/manifests >/dev/null
	kubectl kustomize demo/kind/remote-manifests >/dev/null
	$(DOCKER_COMPOSE) -f $(DOCKER_COMPOSE_FILE) config --quiet
	$(DOCKER_COMPOSE) -f docker-compose.server.yml config --quiet
	$(DOCKER_COMPOSE) -f docker-compose.client.yml config --quiet
	jq --exit-status 'type == "object"' grafana/dashboards/*.json >/dev/null

changelog:
ifeq ($(GIT_BRANCH_NAME), master)
	@echo "Current branch is $(GIT_BRANCH_NAME), create changelog"
	gitchangelog > CHANGELOG.md
else
	@echo "Current branch is $(GIT_BRANCH_NAME), skipping to update CHANGELOG.md"
endif

all: test-apps validate-manifests build-images test-images build-charts

demo-compose-up:
	$(DOCKER_COMPOSE) -f $(DOCKER_COMPOSE_FILE) up -d --build

demo-compose-down:
	$(DOCKER_COMPOSE) -f $(DOCKER_COMPOSE_FILE) down

demo-compose-config:
	$(DOCKER_COMPOSE) -f $(DOCKER_COMPOSE_FILE) config

demo-kind-verify:
	./demo/kind/verify.sh

demo-kind-up:
	./demo/kind/up.sh

demo-kind-down:
	./demo/kind/down.sh

.PHONY: test-apps fmt lint build-images test-images push-images build-charts validate-manifests all \
	demo-compose-up demo-compose-down demo-compose-config \
	demo-kind-up demo-kind-down demo-kind-verify
