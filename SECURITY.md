# Security Policy

## Supported versions

FluxWave is pre-`1.0` (`0.2.2`). Security fixes are applied to the latest
release on `main`. Pin a version you have reviewed for production use.

## Reporting a vulnerability

Please report security issues **privately** rather than opening a public issue:

- Use GitHub's [private vulnerability reporting](https://github.com/FluxWaveProject/fluxwave/security/advisories/new), or
- Contact the maintainer directly.

Include a description, affected versions, and a reproduction if possible. You'll
get an acknowledgement and a fix timeline; please allow time to patch before any
public disclosure.

## Handling secrets

FluxWave talks to Discord and Lavalink, so bots using it hold sensitive
credentials. When reporting issues or sharing logs:

- **Never** include real Discord bot tokens or Lavalink passwords.
- Read tokens/passwords from environment variables or a secret manager, not
  source code.
- If a token is ever exposed, regenerate it immediately (Discord Developer
  Portal → Bot → Reset Token) and rotate any shared Lavalink passwords.

## Trust boundaries

Treat Lavalink plugin endpoints and custom REST routes as trusted-server APIs.
Validate any user-supplied input before forwarding it to a node.
