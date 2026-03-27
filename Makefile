SHELL := /bin/bash

IPERF_EXPORTER_SERVER_IMAGE_NAME ?= loktionovam/iperf_exporter_server
IPERF_EXPORTER_CLIENT_IMAGE_NAME ?= loktionovam/iperf_exporter_client
IPERF_EXPORTER_IMAGE_TAG ?= $(shell ./get_version.sh)
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
	python -m black --check iperf_exporter tests

test-apps: lint
	python -m pytest --cov-report=xml --cov-report=term --cov=iperf_exporter tests/apps -v

fmt:
	python -m black iperf_exporter tests

build-images:
	docker build --build-arg MODE=server --build-arg VERSION=$(IPERF_EXPORTER_IMAGE_TAG) -t $(IPERF_EXPORTER_SERVER_IMAGE_NAME):$(IPERF_EXPORTER_IMAGE_TAG) .
	docker build --build-arg MODE=client --build-arg VERSION=$(IPERF_EXPORTER_IMAGE_TAG) -t $(IPERF_EXPORTER_CLIENT_IMAGE_NAME):$(IPERF_EXPORTER_IMAGE_TAG) .

test-images:
	python -m pytest tests/images -v

push-images:
	docker push $(IPERF_EXPORTER_SERVER_IMAGE_NAME):$(IPERF_EXPORTER_IMAGE_TAG)
	docker push $(IPERF_EXPORTER_CLIENT_IMAGE_NAME):$(IPERF_EXPORTER_IMAGE_TAG)

build-charts:
	helm lint helm/charts/iperf-exporter-server
	# helm lint helm/charts/iperf-exporter-client
	helm/release_helm_chart.py

changelog:
ifeq ($(GIT_BRANCH_NAME), master)
	@echo "Current branch is $(GIT_BRANCH_NAME), create changelog"
	gitchangelog > CHANGELOG.md
else
	@echo "Current branch is $(GIT_BRANCH_NAME), skipping to update CHANGELOG.md"
endif

all: test-apps build-images test-images build-charts

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

.PHONY: test-apps fmt lint build-images test-images push-images build-charts all \
	demo-compose-up demo-compose-down demo-compose-config \
	demo-kind-up demo-kind-down demo-kind-verify
