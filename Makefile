IPERF_EXPORTER_SERVER_IMAGE_NAME ?= loktionovam/iperf_exporter_server
IPERF_EXPORTER_CLIENT_IMAGE_NAME ?= loktionovam/iperf_exporter_client
IPERF_EXPORTER_IMAGE_TAG ?= $(shell ./get_version.sh)
GIT_BRANCH_NAME := $(shell git branch  --show-current)
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
ifeq ($(GIT_BRANCH_NAME), main)
	@echo "Current branch is $(GIT_BRANCH_NAME), create changelog"
	gitchangelog > CHANGELOG.md
else
	@echo "Current branch is $(GIT_BRANCH_NAME), skipping to update CHANGELOG.md"
endif

all: test-apps build-images test-images build-charts

.PHONY: test-apps fmt lint build-images test-images push-images build-charts all
