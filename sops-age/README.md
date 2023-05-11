# sops

Encrypt secret with sops-age

```
AGE_PUBLIC_KEY=age1qkqm9wxjuezyfkahgckwfj3y09aa0psn3h9zn9tchj9khtaqj9xskg9thv
sops --age=$AGE_PUBLIC_KEY  --encrypt --encrypted-regex '^(data|stringData)$' secret-decrypted.yaml > secret-encrypted.yaml
```
