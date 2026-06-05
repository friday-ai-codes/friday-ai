VERSION ?= $(shell git describe --tags --always --dirty)
LDFLAGS := -s -w -X github.com/friday-ai-codes/friday-ai/runner/internal/cmd.Version=$(VERSION)
PLATFORMS := linux/amd64 linux/arm64 darwin/amd64 darwin/arm64
PREFIX ?= /usr/local
BINDIR := $(PREFIX)/bin

.PHONY: build build-all install uninstall clean

build:
	CGO_ENABLED=0 go build -trimpath -ldflags "$(LDFLAGS)" -o friday-runner ./cmd/friday-runner

build-all: clean
	@$(foreach platform,$(PLATFORMS),\
		$(eval OS := $(word 1,$(subst /, ,$(platform))))\
		$(eval ARCH := $(word 2,$(subst /, ,$(platform))))\
		echo "Building $(OS)/$(ARCH)..." && \
		CGO_ENABLED=0 GOOS=$(OS) GOARCH=$(ARCH) go build -trimpath -ldflags "$(LDFLAGS)" \
			-o dist/friday-runner-$(OS)-$(ARCH) ./cmd/friday-runner && \
	) true

install: build
	@echo "Installing friday-runner to $(BINDIR)..."
	@install -d $(BINDIR)
	@install -m 755 friday-runner $(BINDIR)/friday-runner
	@echo "Done. $(BINDIR)/friday-runner ($(VERSION))"

uninstall:
	@rm -f $(BINDIR)/friday-runner
	@echo "Removed $(BINDIR)/friday-runner"

clean:
	rm -rf dist/ friday-runner
