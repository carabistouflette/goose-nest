GOOSE ?= .toolchain/goose/build/goose
HONK ?= ../honk/.build/honk
.PHONY: build check test bench clean
build:
	mkdir -p .build
	$(GOOSE) build cli.goose -o .build/nest
check:
	python3 scripts/check-vendor.py
	$(GOOSE) check cli.goose
	$(GOOSE) format --check nest.goose cli.goose tests/core.goose
	python3 -m py_compile tools/registry.py tests/integration.py bench/run.py
	git diff --check
test: build
	$(GOOSE) run tests/core.goose
	$(GOOSE) build tests/core.goose -o .build/core
	.build/core
	GOOSE=$(abspath $(GOOSE)) NEST=$(CURDIR)/.build/nest python3 -m unittest discover -s tests -p '*.py' -v
bench: build
	python3 bench/run.py --nest .build/nest --honk $(HONK) --output bench/results.json
clean:
	rm -rf .build

.PHONY: setup native-test
setup:
	./scripts/setup-goose.sh
native-test:
	mkdir -p .build
	$(CC) -D_GNU_SOURCE -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer tests/native.c $$(pkg-config --cflags --libs libcurl libarchive openssl) -o .build/native-sanitize
	ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 .build/native-sanitize
