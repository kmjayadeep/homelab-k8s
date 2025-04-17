# Use a lightweight base image with some dev tools
FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Install essential tools
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive && apt-get install -y \
    curl wget git unzip gnupg lsb-release bash-completion zsh \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl

# Install helm
RUN curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Install kustomize
RUN curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash \
    && mv kustomize /usr/local/bin/

# Install Terraform
RUN wget https://releases.hashicorp.com/terraform/1.6.6/terraform_1.6.6_linux_amd64.zip \
    && unzip terraform_1.6.6_linux_amd64.zip \
    && mv terraform /usr/local/bin/ \
    && rm terraform_1.6.6_linux_amd64.zip


# Set user (for Coder/VSCode devcontainers)
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    && chsh -s /bin/bash $USERNAME

USER $USERNAME

