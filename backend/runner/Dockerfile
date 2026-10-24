# The sandbox image: compiles and traces one C/C++ program per container.
#   docker build -t kaaran-runner backend/runner
# backend/sandbox.py starts it with no network, limited memory/CPU,
# a read-only filesystem and a non-root user.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ gdb libc6-dev python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY c_analysis.py c_tracer.py mi.py /app/

RUN useradd --uid 10001 --create-home runner
USER 10001
WORKDIR /tmp
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1

# Reads {"language", "code", "input"} as JSON on stdin, prints the trace JSON
ENTRYPOINT ["python3", "/app/c_tracer.py"]
