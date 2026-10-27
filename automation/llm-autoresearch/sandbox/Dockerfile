# Grading sandbox for model-generated code. Runs with --network none,
# read-only root, no capabilities and a non-root user (see evalctl/grade.py).
FROM python:3.13-slim@sha256:d3449c0493345868b09708d7056dce5edda3a75233ea86008fc80c934d355a10
RUN pip install --no-cache-dir numpy==2.2.6 PyYAML==6.0.2
COPY run_programs.py /opt/run_programs.py
