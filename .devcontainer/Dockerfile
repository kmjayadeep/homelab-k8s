# Use a lightweight base image with some dev tools
FROM mcr.microsoft.com/devcontainers/base:ubuntu


USER vscode

# Setup nix
RUN curl --proto '=https' --tlsv1.2 -sSf -L https://nixos.org/nix/install | sh -s -- --no-daemon
