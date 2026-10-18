# The official MCP Registry listing (T-4633)

`server.json` lists the open-data MCP hub (`https://api.joinedcontext.com/api/mcp`, streamable
HTTP, anonymous reads) in the official registry, https://registry.modelcontextprotocol.io, as
`com.joinedcontext/open-data`. The registry keeps metadata only; aggregators pull from it. It lists
the production host only, never `dev`.

Check it with `mcp-publisher` v1.8.1 (2026-08-06, `mcp-publisher_linux_amd64.tar.gz` sha256
`a06c9096dcb9727c13555b6be26c7effa707b01f06a4c561ba7a3635443cf2cc`), from this directory:

```sh
mcp-publisher validate
```

## Publishing: the owner's steps

Publishing is outward-facing and proves that we own `joinedcontext.com`, so the owner runs it,
once `api.joinedcontext.com` resolves and answers `/api/mcp`.

1. Make a key pair outside any repository (OpenSSL 3):

   ```sh
   openssl genpkey -algorithm Ed25519 -out key.pem
   PUBLIC_KEY="$(openssl pkey -in key.pem -pubout -outform DER | tail -c 32 | base64)"
   ```

2. Prove the name, one of:
   - DNS at Websupport: a TXT record on the apex `joinedcontext.com` (not under a selector)
     with the value `v=MCPv1; k=ed25519; p=${PUBLIC_KEY}`;
   - HTTP: the same line as the whole body of
     `https://joinedcontext.com/.well-known/mcp-registry-auth`.
3. Log in and publish, from this directory:

   ```sh
   PRIVATE_KEY="$(openssl pkey -in key.pem -noout -text | grep -A3 "priv:" | tail -n +2 | tr -d ' :\n')"
   mcp-publisher login dns --domain joinedcontext.com --private-key "${PRIVATE_KEY}"
   mcp-publisher publish
   ```

   With the HTTP file, `login http` takes the same arguments. Keep `key.pem` off every repository,
   task and log; a later version publishes with the same key, and a new key needs the old record removed.

A new version is a new `version` in `server.json`, validated and published the same way.
