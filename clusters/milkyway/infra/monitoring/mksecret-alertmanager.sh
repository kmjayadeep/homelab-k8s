#!/bin/bash

# mksecret-alertmanager.sh: Create alertmanager secret

kubectl create secret generic alertmanager-config -n monitoring --from-file=alertmanager.yaml=config/alertmanager-decrypted.yaml --dry-run=client -oyaml > ./alertmanager-config-decrypted.yaml
kubeseal --format=yaml --cert ../../../../kubeseal/milkyway-sealed-secrets.pem < alertmanager-config-decrypted.yaml > alermanager-config-sealed.yaml
