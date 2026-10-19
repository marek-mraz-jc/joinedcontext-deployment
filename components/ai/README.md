# ai

The standalone assistant on `https://ai.{domain}/{publicId}` (T-4694): a static copy of the
public widget, built by the platform's `crates/assistant/widget/app/build.mjs --template` into
`charts/app/files/site/`. It talks to `https://assistant.{domain}/api/v1/d/{publicId}/*` only
(config, challenge, token, chat, feedback); the chat answers it only when `https://ai.{domain}`
is in the deployment's `allowedOrigins`. A city site embeds it with

    <script src="https://ai.{domain}/embed.js" data-deployment="{publicId}" defer></script>

and app.js shows the framed copy only inside the deployment's own origins.

Refresh the bundle after a widget change on platform `main`:

    node ../joinedcontext-platform/crates/assistant/widget/app/build.mjs --template --out components/ai/charts/app/files/site

Tests: `tests/test_ai_app.py`.
