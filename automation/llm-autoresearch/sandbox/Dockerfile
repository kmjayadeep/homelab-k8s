# Grading sandbox for model-generated code. Runs with --network none,
# read-only root, no capabilities and a non-root user (see evalctl/grade.py).
FROM python:3.13-slim@sha256:5dde09372dfa8e7762892b2a12619fcf6c23b0b78bce1058a9fa5a3a7a40e68e
RUN pip install --no-cache-dir numpy==2.2.6 PyYAML==6.0.2
COPY run_programs.py /opt/run_programs.py
