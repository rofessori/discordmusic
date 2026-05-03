# Security Policy

Thanks for taking the time to report security issues. This is a personal/open project, not a company security desk, but I do want real problems handled responsibly and fixed as quickly as I reasonably can.

## Reporting a vulnerability

Please do not open a public GitHub issue with exploit details, bot tokens, private server ids, logs that contain secrets, or step-by-step abuse instructions.

Use GitHub's private vulnerability reporting for this repository if it is available. If private reporting is not available, open a normal issue with a short title like:

```text
security report - private contact needed
```

Do not include the vulnerability details in that public issue. I will reply and move the discussion somewhere private.

## What to include

Helpful reports usually include:

- what version or commit you tested
- what file/function/command is affected
- what an attacker needs to do
- what the impact is
- whether this requires admin permissions, Discord server access, voice-channel access, or local filesystem access
- a safe proof of concept, if you have one
- any logs with tokens, cookies, user ids, and server ids removed

If the issue involves the setup assistant, `.env`, `setup.tmp`, systemd setup, playlist files, downloaded media files, or dependency alerts, please mention that directly.

## What I consider security-sensitive

Please report things like:

- Discord bot token exposure or unsafe secret storage
- auth/admin bypasses
- commands that let normal users act as admins
- path traversal or unsafe file deletion
- ways to make the bot read local files or private-network URLs
- command injection or unsafe shell execution
- dependency vulnerabilities that affect this bot in practice
- denial-of-service issues that can be triggered by normal Discord users
- playlist/download bugs that can overwrite files outside the project directory

## What is usually not a security issue

These are still useful bug reports, but usually not security reports:

- a song failing to play
- YouTube extraction breaking because YouTube changed something
- slash commands not syncing immediately
- normal Discord permission mistakes made while inviting the bot
- someone with full server admin permissions using the bot in a way you did not want

## Response expectations

I will try to acknowledge serious reports quickly, but this is maintained in spare time. If the issue is real and affects users, I will prioritize a fix, note the change in the changelog, and credit the reporter if they want credit.

For high-impact reports, please give me a reasonable chance to patch before posting public details.

## Secret handling reminder

If you think your Discord bot token was exposed, rotate it immediately in the Discord Developer Portal. Do not wait for a code fix. A leaked bot token should be treated as compromised.
