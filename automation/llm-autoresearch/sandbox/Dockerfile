# Grading sandbox for model-generated code. Runs with --network none,
# read-only root, no capabilities and a non-root user (see evalctl/grade.py).
FROM python:3.13-slim@sha256:81c118faaca296a46b46a7dd7f3bf7575a956d8a4af22623b3de2ff504a3e89b
RUN pip install --no-cache-dir numpy==2.2.6 PyYAML==6.0.2
COPY run_programs.py /opt/run_programs.py
