# syntax=docker/dockerfile:1

# EPUBWeave is frozen with PyInstaller. The resulting artifact contains its
# Python runtime and dependencies, so its consumer does not need Python/pip.
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends binutils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir pyinstaller

COPY main.py ./
COPY static ./static

RUN pyinstaller \
    --noconfirm \
    --clean \
    --onefile \
    --name epubweave \
    --add-data "static:static" \
    --collect-all ebooklib \
    --collect-all PIL \
    main.py

# Verify the executable in an image without Python installed.
FROM debian:bookworm-slim AS smoke-test

WORKDIR /work

COPY --from=builder /app/dist/epubweave /usr/local/bin/epubweave
COPY sample ./sample

RUN epubweave --input /work/sample --output /tmp/sample.epub \
    && test -s /tmp/sample.epub

# Export this target with BuildKit's --output option.
FROM scratch AS artifact

COPY --from=smoke-test /usr/local/bin/epubweave /epubweave
