# Use a lightweight base image with some dev tools
FROM mcr.microsoft.com/devcontainers/base:ubuntu

# Install essential tools
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive && apt-get install -y \
    curl wget git unzip gnupg lsb-release bash-completion zsh \
    && rm -rf /var/lib/apt/lists/*

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
