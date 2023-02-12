#!/bin/bash

# mksecret-alertmanager.sh: Create alertmanager secret

kubectl create secret generic alertmanager-config --from-file=config.yml=config-decrypted.yaml --dry-run=client -oyaml > ./alertmanager-decrypted.yaml
kubeseal --format=yaml --cert ../../../../kubeseal/pub-sealed-secrets.pem < alertmanager-decrypted.yaml > alermanager-config-sealed.yaml
