VERSION ?= $(shell git describe --tags --always --dirty)
LDFLAGS:= -s -w -X github.com/friday-ai-codes/friday-ai/runner/internal/cmd.Version=$(VERSION)
PLATFORMS:= linux/amd64 linux/arm64 darwin/amd64 darwin/arm64
.PHONY: build build-all clean
build:
	CGO_ENABLED=0 go build -trimpath -ldflags "$(LDFLAGS)" -o friday-runner ./cmd/friday-runner
build-all: clean
	@$(foreach platform,$(PLATFORMS),\
 $(eval OS:= $(word 1,$(subst /,,$(platform))))\
 $(eval ARCH:= $(word 2,$(subst /,,$(platform))))\
 echo "Building $(OS)/$(ARCH)..." && \
 CGO_ENABLED=0 GOOS=$(OS) GOARCH=$(ARCH) go build -trimpath -ldflags "$(LDFLAGS)" \
 -o dist/friday-runner-$(OS)-$(ARCH) ./cmd/friday-runner && \
	) true
clean:
	rm -rf dist/ friday-runner
