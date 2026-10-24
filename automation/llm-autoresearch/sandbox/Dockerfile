# Grading sandbox for model-generated code. Runs with --network none,
# read-only root, no capabilities and a non-root user (see evalctl/grade.py).
FROM python:3.15-slim@sha256:533b0b2f9b5d46fd097091cf826f27902f1d6c3bca714b6dc74551356aa97a51
RUN pip install --no-cache-dir numpy==2.2.6 PyYAML==6.0.2
COPY run_programs.py /opt/run_programs.py
