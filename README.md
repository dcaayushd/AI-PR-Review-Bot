# AI PR Review Bot

Multi-tenant AI pull request review service built in Python. This version is designed as a global service: you deploy one backend, register one GitHub App, install that app on many repositories, and the service reviews PRs across all of them.

## What changed

The original repo-local GitHub Action path still exists as a self-hosted fallback in [.github/workflows/ai-pr-review.yml](./.github/workflows/ai-pr-review.yml), but the main architecture is now a GitHub App service:

1. GitHub sends `pull_request` webhooks to the service.
2. The backend verifies the webhook signature.
3. The backend mints a GitHub App installation token for the specific tenant repo.
4. It fetches the PR head from `refs/pull/<number>/head`, checks out the code in a temporary workspace, and loads that repo's `.ai-review.yml`.
5. The review engine chunks the diff, calls the OpenAI Responses API, validates structured output, and builds summary plus inline review comments.
6. Its posts the review back to the PR as the GitHub App bot account.

## Architecture

### Core components

- [src/pr_review_bot/server.py](./src/pr_review_bot/server.py)
  - FastAPI webhook server
  - `/webhooks/github`
  - `/healthz`
  - `/jobs/{job_id}`
- [src/pr_review_bot/review_service.py](./src/pr_review_bot/review_service.py)
  - background review execution
  - stale-delivery detection
  - GitHub posting
- [src/pr_review_bot/github_app.py](./src/pr_review_bot/github_app.py)
  - GitHub App JWT auth
  - installation access token creation
- [src/pr_review_bot/checkout.py](./src/pr_review_bot/checkout.py)
  - safe PR checkout from the target repo
- [src/pr_review_bot/storage.py](./src/pr_review_bot/storage.py)
  - sqlite-backed job persistence
- [src/pr_review_bot/reviewer.py](./src/pr_review_bot/reviewer.py)
  - diff extraction, chunking, LLM review orchestration
- [src/pr_review_bot/llm_client.py](./src/pr_review_bot/llm_client.py)
  - OpenAI integration with retries and fallback model support

## GitHub App setup

Create a GitHub App and configure it with:

- Webhook URL: `https://your-domain.com/webhooks/github`
- Webhook secret: a strong random secret
- Repository permissions:
  - `Contents: Read-only`
  - `Pull requests: Read & write`
  - `Issues: Read & write`
  - `Metadata: Read-only`
- Subscribe to:
  - `Pull request`

After that, install the app on any repository or organization you want the service to review.

Because reviews are posted with an installation token, the comments show up as an actual bot review from your GitHub App instead of `github-actions[bot]`.

## Environment

Copy [.env.example](./.env.example) to `.env` and fill in:

- `LLM_PROVIDER`
- `OPENAI_API_KEY` for OpenAI
- or `GOOGLE_API_KEY` for Gemini
- `GITHUB_APP_ID`
- `GITHUB_APP_PRIVATE_KEY` or `GITHUB_APP_PRIVATE_KEY_PATH`
- `GITHUB_WEBHOOK_SECRET`
- `DATABASE_URL`
- `WORKSPACE_ROOT`

Important: `GITHUB_APP_PRIVATE_KEY_PATH` must point to the `.pem` file you download from your GitHub App settings page. The example path `./github-app.private-key.pem` is only a placeholder until you save the real key there.

For PR diff accuracy, `GIT_FETCH_DEPTH` should usually be at least `32`. The service will deepen history automatically when it needs a merge base for `git diff base...head`.

Current LLM providers:

- `openai`: uses the OpenAI Responses API
- `gemini`: uses Google's OpenAI-compatible `chat.completions` endpoint with structured parsing

## Local development

### 1. Install dependencies

```bash
python3 -m pip install -e .
```

### 2. Start the review server

```bash
set -a
source .env
set +a

ai-pr-review-server
```

Or:

```bash
uvicorn pr_review_bot.server:app --host 0.0.0.0 --port 8000
```

### 3. Expose the webhook locally

Use ngrok, Cloudflare Tunnel, or another reverse tunnel:

```bash
ngrok http 8000
```

Then paste the public URL into the GitHub App webhook settings.

## Docker deployment

Build and run:

```bash
docker build -t ai-pr-review .
docker run --env-file .env -p 8000:8000 ai-pr-review
```

The container installs `git` because the service performs PR fetch and checkout operations for target repositories.

## Repo-level configuration

Each installed repository can still define its own `.ai-review.yml` to control safe review behavior:

- model selection
- fallback model
- temperature
- chunk sizing
- inline comment limits
- ignored files
- repository context files

For service safety, repo config is not allowed to override GitHub API destination settings.

## API

### `POST /webhooks/github`

Receives GitHub App webhook deliveries.

### `GET /healthz`

Simple liveness endpoint.

### `GET /jobs/{job_id}`

Returns review job status:

- `queued`
- `running`
- `completed`
- `skipped`
- `failed`

## How it looks on GitHub

The service posts:

- a summary comment in the PR conversation
- an inline PR review on changed lines when the model returns line-level findings

That means it appears like a real review bot in the GitHub UI, attached to the PR and authored by the GitHub App.

## Security notes

- Webhook deliveries are verified with `X-Hub-Signature-256`.
- The service uses short-lived GitHub App installation tokens per review job.
- The repo checkout uses `git fetch` against the base repository's PR ref instead of executing untrusted CI code.
- Repo config cannot redirect the service to a different GitHub API host.

## Self-hosted single-repo mode

If you want the older per-repository GitHub Action mode, the CLI path still works:

```bash
ai-pr-review --repo-root . --event-path "$GITHUB_EVENT_PATH"
```

That mode is useful for experiments, but the GitHub App server is the real global path.
