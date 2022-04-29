# kubeseal

public key retrieved using the command:

```
kubeseal --fetch-cert \
--controller-name=sealed-secrets-controller \
--controller-namespace=flux-system \
> pub-sealed-secrets.pem
```

Encrypt secret with kubeseal:

```
cat secret.yaml| kubeseal --format=yaml --cert ../../kubeseal/pub-sealed-secrets.pem > secret-sealed.yaml
```
