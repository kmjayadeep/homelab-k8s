# Grading sandbox for model-generated code. Runs with --network none,
# read-only root, no capabilities and a non-root user (see evalctl/grade.py).
FROM python:3.13-slim@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc
RUN pip install --no-cache-dir numpy==2.2.6 PyYAML==6.0.2
COPY run_programs.py /opt/run_programs.py
