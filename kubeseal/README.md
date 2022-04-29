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
Encrypt the secret with kubeseal:

kubeseal --format=yaml --cert=pub-sealed-secrets.pem \
< basic-auth.yaml > basic-auth-sealed.yaml
```
