from __future__ import annotations

from html import escape
from typing import Any

from .storage import ReviewJob


STATUS_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "completed": "Completed",
    "skipped": "Skipped",
    "failed": "Failed",
    "superseded": "Superseded",
    "rejected": "Rejected",
}

STATUS_TONES = {
    "queued": "tone-blue",
    "running": "tone-cyan",
    "completed": "tone-green",
    "skipped": "tone-amber",
    "failed": "tone-red",
    "superseded": "tone-slate",
    "rejected": "tone-rose",
}

SEVERITY_TONES = {
    "critical": "tone-red",
    "warning": "tone-amber",
    "nitpick": "tone-slate",
}

RISK_TONES = {
    "low": "tone-green",
    "medium": "tone-amber",
    "high": "tone-red",
}


def render_dashboard_page(
    *,
    app_version: str,
    runtime_snapshot: dict[str, int | bool],
    metrics_summary: dict[str, Any],
    recent_jobs: list[ReviewJob],
) -> str:
    status_chips = "".join(
        _pill(label=f"{STATUS_LABELS.get(status, status.title())}: {count}", tone=STATUS_TONES.get(status, "tone-slate"))
        for status, count in sorted(metrics_summary["counts_by_status"].items())
    ) or _pill(label="No jobs yet", tone="tone-slate")

    provider_chips = "".join(
        _pill(label=f"{provider}: {count}", tone="tone-blue")
        for provider, count in sorted(metrics_summary.get("counts_by_provider", {}).items())
    ) or _pill(label="No providers recorded", tone="tone-slate")
    risk_chips = "".join(
        _pill(label=f"{level.title()}: {count}", tone=RISK_TONES.get(level, "tone-slate"))
        for level, count in sorted(metrics_summary.get("counts_by_risk", {}).items())
    ) or _pill(label="No risk data yet", tone="tone-slate")
    repo_chips = "".join(
        _pill(label=f"{repo['repo_full_name']}: {repo['job_count']}", tone="tone-slate")
        for repo in metrics_summary.get("top_repositories", [])
    ) or _pill(label="No repository history yet", tone="tone-slate")

    job_rows = "".join(_render_job_row(job) for job in recent_jobs) or (
        "<tr><td colspan='8' class='empty'>No jobs recorded yet. Trigger a pull request webhook to populate the dashboard.</td></tr>"
    )

    readiness = "Accepting traffic" if runtime_snapshot["queue_accepting"] else "Backpressure active"
    readiness_tone = "tone-green" if runtime_snapshot["queue_accepting"] else "tone-amber"

    content = f"""
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">AI PR Review Bot</p>
        <h1>Operator control plane for your pull request review service.</h1>
        <p class="lede">
          Monitor queue pressure, recent review jobs, provider usage, and end-to-end review health from one place.
        </p>
        <div class="pill-row">
          {_pill(readiness, readiness_tone)}
          {_pill(f"Workers: {runtime_snapshot['running_jobs']}/{runtime_snapshot['max_parallel_reviews']}", "tone-blue")}
          {_pill(f"Queued: {runtime_snapshot['queued_jobs']}/{runtime_snapshot['max_pending_reviews']}", "tone-cyan")}
          {_pill(f"Repo limit: {runtime_snapshot['max_repo_active_reviews']}", "tone-slate")}
        </div>
      </div>
      <div class="hero-panel card">
        <h2>System flow</h2>
        <div class="flow-grid">
          {_flow_step("GitHub App", "Receives PR events from installed repositories")}
          {_flow_step("Webhook API", "Verifies signatures and creates review jobs")}
          {_flow_step("Queue Control", "Rejects overload and supersedes stale work")}
          {_flow_step("Review Engine", "Chunks diffs, redacts secrets, and calls the LLM")}
          {_flow_step("GitHub Output", "Posts summary comments, inline reviews, and check runs")}
        </div>
      </div>
    </section>

    <section class="metrics-grid">
      {_metric_card("Total jobs", str(metrics_summary['total_jobs']), "All recorded webhook-triggered reviews")}
      {_metric_card("Findings", str(metrics_summary['total_findings']), "Structured review findings generated")}
      {_metric_card("Inline comments", str(metrics_summary['total_inline_comments']), "Line-level review comments prepared")}
      {_metric_card("Redactions", str(metrics_summary['total_redactions']), "Likely secret values masked before model calls")}
      {_metric_card("Active repositories", str(metrics_summary['active_repositories']), "Repositories with stored review history")}
      {_metric_card("Avg duration", _seconds_label(metrics_summary['avg_duration_seconds']), "Average elapsed time for finished jobs")}
    </section>

    <section class="three-up">
      <div class="card">
        <div class="section-head">
          <h2>Status mix</h2>
          <span class="subtle">Live queue and fleet state</span>
        </div>
        <div class="pill-row">{status_chips}</div>
      </div>
      <div class="card">
        <div class="section-head">
          <h2>Provider mix</h2>
          <span class="subtle">Which LLM provider handled stored jobs</span>
        </div>
        <div class="pill-row">{provider_chips}</div>
      </div>
      <div class="card">
        <div class="section-head">
          <h2>Risk mix</h2>
          <span class="subtle">Adaptive review routing profile distribution</span>
        </div>
        <div class="pill-row">{risk_chips}</div>
      </div>
    </section>

    <section class="card">
      <div class="section-head">
        <div>
          <h2>Top repositories</h2>
          <p class="subtle">Repositories with the most recorded review activity</p>
        </div>
      </div>
      <div class="pill-row">{repo_chips}</div>
    </section>

    <section class="card">
      <div class="section-head">
        <div>
          <h2>Recent jobs</h2>
          <p class="subtle">Latest review activity across all repositories</p>
        </div>
        <div class="section-actions">
          <a class="ghost-link" href="/jobs">JSON</a>
          <a class="ghost-link" href="/metrics">Metrics</a>
          <a class="ghost-link" href="/readyz">Ready</a>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Repository</th>
              <th>PR</th>
              <th>Provider</th>
              <th>Risk</th>
              <th>Model</th>
              <th>Findings</th>
              <th>Updated</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>{job_rows}</tbody>
        </table>
      </div>
    </section>
    """
    return _page_shell(title="AI PR Review Control Plane", app_version=app_version, body=content)


def render_job_detail_page(*, app_version: str, job: ReviewJob) -> str:
    payload = job.as_dict()
    findings = payload["findings"]
    suggested_tests = payload["suggested_tests"]
    analyzed_files = payload["analyzed_files"]
    skipped_files = payload["skipped_files"]
    summary_points = payload["summary_points"]
    pr_url = f"https://github.com/{job.repo_full_name}/pull/{job.pull_number}"

    findings_html = "".join(_render_finding_card(finding) for finding in findings) or (
        "<div class='empty-block'>No persisted findings were stored for this job.</div>"
    )
    summary_html = "".join(f"<li>{escape(str(point))}</li>" for point in summary_points) or "<li>No summary points recorded.</li>"
    tests_html = "".join(f"<li>{escape(str(item))}</li>" for item in suggested_tests) or "<li>No suggested tests recorded.</li>"
    analyzed_files_html = "".join(f"<li><code>{escape(str(path))}</code></li>" for path in analyzed_files) or "<li>None</li>"
    skipped_files_html = "".join(f"<li><code>{escape(str(path))}</code></li>" for path in skipped_files) or "<li>None</li>"

    content = f"""
    <section class="hero compact">
      <div class="hero-copy">
        <p class="eyebrow">Review Job</p>
        <h1>{escape(job.repo_full_name)} PR #{job.pull_number}</h1>
        <p class="lede">Job <code>{escape(job.job_id)}</code></p>
        <div class="pill-row">
          {_pill(STATUS_LABELS.get(job.status, job.status.title()), STATUS_TONES.get(job.status, 'tone-slate'))}
          {_pill(job.provider or "unknown provider", "tone-blue")}
          {_pill(f"{job.risk_level.title()} risk", RISK_TONES.get(job.risk_level, "tone-slate"))}
          {_pill(job.model_used or "model pending", "tone-cyan")}
        </div>
      </div>
      <div class="hero-panel card metadata">
        <h2>Overview</h2>
        <dl class="meta-grid">
          <div><dt>Repository</dt><dd>{escape(job.repo_full_name)}</dd></div>
          <div><dt>Pull request</dt><dd><a href="{escape(pr_url)}">#{job.pull_number}</a></dd></div>
          <div><dt>Head SHA</dt><dd><code>{escape(job.head_sha[:12])}</code></dd></div>
          <div><dt>Risk</dt><dd>{escape(job.risk_level.title())} ({job.risk_score})</dd></div>
          <div><dt>Findings</dt><dd>{job.findings_count}</dd></div>
          <div><dt>Inline comments</dt><dd>{job.inline_comments_count}</dd></div>
          <div><dt>Duration</dt><dd>{_seconds_label(job.duration_seconds)}</dd></div>
        </dl>
      </div>
    </section>

    <section class="metrics-grid">
      {_metric_card("Created", _timestamp_label(job.created_at), "Webhook accepted")}
      {_metric_card("Started", _timestamp_label(job.started_at), "Worker execution began")}
      {_metric_card("Completed", _timestamp_label(job.completed_at), "Final job state reached")}
      {_metric_card("Chunks", str(job.chunk_count), "Diff chunks reviewed")}
      {_metric_card("Reviewable files", str(job.analyzed_files_count), "Files included in the review")}
      {_metric_card("Redactions", str(job.redaction_count), "Likely secrets masked")}
    </section>

    <section class="two-up">
      <div class="card">
        <div class="section-head">
          <h2>Summary</h2>
          <span class="subtle">High-level outcome captured for this review</span>
        </div>
        <ul class="stack-list">{summary_html}</ul>
      </div>
      <div class="card">
        <div class="section-head">
          <h2>Suggested tests</h2>
          <span class="subtle">Regression ideas generated by the review</span>
        </div>
        <ul class="stack-list">{tests_html}</ul>
      </div>
    </section>

    <section class="card">
      <div class="section-head">
        <h2>Risk routing</h2>
        <span class="subtle">Why this job was routed at its current review intensity</span>
      </div>
      <div class="pill-row">{''.join(_pill(reason, 'tone-slate') for reason in payload['risk_reasons']) or _pill('No risk reasons recorded', 'tone-slate')}</div>
    </section>

    <section class="card">
      <div class="section-head">
        <h2>Findings</h2>
        <span class="subtle">Persisted structured review output</span>
      </div>
      <div class="finding-grid">{findings_html}</div>
    </section>

    <section class="two-up">
      <div class="card">
        <div class="section-head">
          <h2>Analyzed files</h2>
          <span class="subtle">Files included in the review pass</span>
        </div>
        <ul class="stack-list files">{analyzed_files_html}</ul>
      </div>
      <div class="card">
        <div class="section-head">
          <h2>Skipped files</h2>
          <span class="subtle">Ignored or binary files omitted from the review</span>
        </div>
        <ul class="stack-list files">{skipped_files_html}</ul>
      </div>
    </section>
    """

    if job.error_message:
        content += f"""
        <section class="card">
          <div class="section-head">
            <h2>Job note</h2>
            <span class="subtle">Operational reason captured for the final state</span>
          </div>
          <div class="note-block">{escape(job.error_message)}</div>
        </section>
        """

    if job.superseded_by_head_sha:
        content += f"""
        <section class="card">
          <div class="section-head">
            <h2>Supersedence</h2>
            <span class="subtle">This job was replaced by a newer pull request head</span>
          </div>
          <div class="note-block"><code>{escape(job.superseded_by_head_sha[:12])}</code></div>
        </section>
        """

    return _page_shell(title=f"AI PR Review Job {job.job_id}", app_version=app_version, body=content)


def _render_job_row(job: ReviewJob) -> str:
    return (
        "<tr>"
        f"<td>{_pill(STATUS_LABELS.get(job.status, job.status.title()), STATUS_TONES.get(job.status, 'tone-slate'))}</td>"
        f"<td><strong>{escape(job.repo_full_name)}</strong></td>"
        f"<td>#{job.pull_number}</td>"
        f"<td>{escape(job.provider or 'unknown')}</td>"
        f"<td>{_pill(job.risk_level.title(), RISK_TONES.get(job.risk_level, 'tone-slate'))}</td>"
        f"<td><code>{escape((job.model_used or 'pending')[:36])}</code></td>"
        f"<td>{job.findings_count}</td>"
        f"<td>{escape(_timestamp_label(job.updated_at))}</td>"
        f"<td><a class='table-link' href='/jobs/{escape(job.job_id)}/view'>Open</a></td>"
        "</tr>"
    )


def _render_finding_card(finding: dict[str, Any]) -> str:
    tone = SEVERITY_TONES.get(str(finding.get("severity", "")).lower(), "tone-slate")
    location = ""
    file_path = str(finding.get("file_path") or "").strip()
    line = finding.get("line")
    if file_path and line:
        location = f"<p class='finding-location'><code>{escape(file_path)}:{escape(str(line))}</code></p>"
    elif file_path:
        location = f"<p class='finding-location'><code>{escape(file_path)}</code></p>"
    snippet = ""
    if finding.get("code_snippet"):
        snippet = f"<pre><code>{escape(str(finding['code_snippet']))}</code></pre>"
    return f"""
    <article class="finding-card">
      {_pill(str(finding.get("severity", "unknown")).title(), tone)}
      <h3>{escape(str(finding.get("title", "Untitled finding")))}</h3>
      {location}
      <p>{escape(str(finding.get("why_it_matters", "")))}</p>
      <div class="fix-callout">
        <strong>Suggested fix</strong>
        <p>{escape(str(finding.get("suggested_fix", "")))}</p>
      </div>
      {snippet}
    </article>
    """


def _page_shell(*, title: str, app_version: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <style>
      :root {{
        --ink: #0f172a;
        --muted: #52607a;
        --bg: #f6f7fb;
        --panel: rgba(255, 255, 255, 0.82);
        --border: rgba(15, 23, 42, 0.08);
        --shadow: 0 24px 80px rgba(15, 23, 42, 0.08);
        --brand: #ff7a18;
        --brand-2: #118ab2;
        --green: #117a65;
        --amber: #b56a00;
        --red: #b42318;
        --slate: #475467;
        --rose: #be185d;
        --radius: 24px;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(255, 122, 24, 0.20), transparent 34%),
          radial-gradient(circle at top right, rgba(17, 138, 178, 0.18), transparent 28%),
          linear-gradient(180deg, #fcfcfd 0%, #f6f7fb 52%, #eef2f7 100%);
        font-family: "Avenir Next", "Segoe UI", "Trebuchet MS", sans-serif;
      }}
      h1, h2, h3 {{
        font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
        margin: 0;
        letter-spacing: -0.02em;
      }}
      code, pre {{
        font-family: "SFMono-Regular", "JetBrains Mono", "Menlo", monospace;
      }}
      a {{
        color: inherit;
      }}
      .shell {{
        max-width: 1240px;
        margin: 0 auto;
        padding: 32px 20px 56px;
      }}
      .topbar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
        margin-bottom: 24px;
      }}
      .brand {{
        display: flex;
        align-items: center;
        gap: 14px;
      }}
      .brand-mark {{
        width: 48px;
        height: 48px;
        border-radius: 16px;
        background: linear-gradient(135deg, var(--brand), var(--brand-2));
        box-shadow: 0 16px 36px rgba(17, 138, 178, 0.22);
      }}
      .brand-copy p {{
        margin: 0;
        color: var(--muted);
      }}
      .nav {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }}
      .nav a, .ghost-link {{
        padding: 10px 14px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.66);
        border: 1px solid var(--border);
        text-decoration: none;
        color: var(--muted);
      }}
      .hero {{
        display: grid;
        grid-template-columns: 1.3fr 1fr;
        gap: 20px;
        margin-bottom: 22px;
      }}
      .hero.compact {{
        grid-template-columns: 1.1fr 0.9fr;
      }}
      .hero-copy, .card {{
        backdrop-filter: blur(18px);
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        box-shadow: var(--shadow);
      }}
      .hero-copy {{
        padding: 28px;
      }}
      .hero-panel {{
        padding: 24px;
      }}
      .eyebrow {{
        margin: 0 0 10px;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        font-size: 0.74rem;
        color: var(--brand-2);
        font-weight: 700;
      }}
      .lede {{
        margin: 14px 0 0;
        font-size: 1.08rem;
        line-height: 1.65;
        color: var(--muted);
        max-width: 62ch;
      }}
      .pill-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 18px;
      }}
      .pill {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border-radius: 999px;
        font-size: 0.92rem;
        font-weight: 600;
        border: 1px solid transparent;
      }}
      .tone-blue {{ background: rgba(17, 138, 178, 0.14); color: #0c6c8b; border-color: rgba(17, 138, 178, 0.20); }}
      .tone-cyan {{ background: rgba(56, 189, 248, 0.14); color: #0369a1; border-color: rgba(56, 189, 248, 0.22); }}
      .tone-green {{ background: rgba(17, 122, 101, 0.14); color: var(--green); border-color: rgba(17, 122, 101, 0.20); }}
      .tone-amber {{ background: rgba(245, 158, 11, 0.16); color: var(--amber); border-color: rgba(245, 158, 11, 0.24); }}
      .tone-red {{ background: rgba(220, 38, 38, 0.14); color: var(--red); border-color: rgba(220, 38, 38, 0.18); }}
      .tone-slate {{ background: rgba(71, 84, 103, 0.12); color: var(--slate); border-color: rgba(71, 84, 103, 0.18); }}
      .tone-rose {{ background: rgba(190, 24, 93, 0.12); color: var(--rose); border-color: rgba(190, 24, 93, 0.18); }}
      .metrics-grid {{
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 16px;
        margin-bottom: 22px;
      }}
      .metric-card {{
        padding: 20px;
      }}
      .metric-card .label {{
        color: var(--muted);
        font-size: 0.9rem;
      }}
      .metric-card .value {{
        font-size: 2rem;
        font-weight: 800;
        margin: 10px 0 8px;
      }}
      .metric-card .caption {{
        color: var(--muted);
        line-height: 1.55;
        font-size: 0.92rem;
      }}
      .two-up {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 16px;
        margin-bottom: 22px;
      }}
      .three-up {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 16px;
        margin-bottom: 22px;
      }}
      .card {{
        padding: 22px;
      }}
      .section-head {{
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        gap: 12px;
        margin-bottom: 16px;
      }}
      .subtle {{
        color: var(--muted);
        font-size: 0.92rem;
      }}
      .section-actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}
      .flow-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        margin-top: 16px;
      }}
      .flow-step {{
        padding: 16px;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.72);
        border: 1px solid var(--border);
      }}
      .flow-step strong {{
        display: block;
        margin-bottom: 6px;
      }}
      .table-wrap {{
        overflow-x: auto;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
      }}
      th, td {{
        text-align: left;
        padding: 14px 10px;
        border-bottom: 1px solid rgba(15, 23, 42, 0.06);
        vertical-align: top;
      }}
      th {{
        color: var(--muted);
        font-size: 0.84rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}
      .table-link {{
        color: var(--brand-2);
        text-decoration: none;
        font-weight: 700;
      }}
      .empty, .empty-block {{
        color: var(--muted);
        text-align: center;
        padding: 22px 0;
      }}
      .empty-block {{
        border: 1px dashed var(--border);
        border-radius: 18px;
        padding: 24px;
      }}
      .finding-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 16px;
      }}
      .finding-card {{
        padding: 18px;
        border-radius: 20px;
        background: rgba(255, 255, 255, 0.76);
        border: 1px solid var(--border);
      }}
      .finding-card h3 {{
        margin-top: 12px;
        margin-bottom: 8px;
      }}
      .finding-location {{
        margin: 0 0 10px;
        color: var(--muted);
      }}
      .fix-callout {{
        margin-top: 14px;
        padding: 14px;
        border-radius: 16px;
        background: rgba(17, 138, 178, 0.08);
      }}
      .stack-list {{
        margin: 0;
        padding-left: 20px;
        display: grid;
        gap: 10px;
      }}
      .files code {{
        white-space: pre-wrap;
        word-break: break-word;
      }}
      pre {{
        overflow-x: auto;
        padding: 14px;
        border-radius: 16px;
        background: #101828;
        color: #f8fafc;
      }}
      .meta-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
        margin: 16px 0 0;
      }}
      .meta-grid dt {{
        color: var(--muted);
        font-size: 0.84rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 6px;
      }}
      .meta-grid dd {{
        margin: 0;
        font-weight: 700;
      }}
      .note-block {{
        padding: 16px;
        border-radius: 18px;
        background: rgba(71, 84, 103, 0.08);
        color: var(--ink);
      }}
      .footer {{
        display: flex;
        justify-content: space-between;
        gap: 16px;
        margin-top: 28px;
        color: var(--muted);
        font-size: 0.92rem;
      }}
      @media (max-width: 1100px) {{
        .metrics-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
        .hero, .two-up, .three-up, .finding-grid {{ grid-template-columns: 1fr; }}
      }}
      @media (max-width: 720px) {{
        .topbar, .footer, .section-head {{ flex-direction: column; align-items: flex-start; }}
        .metrics-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        .flow-grid, .meta-grid {{ grid-template-columns: 1fr; }}
      }}
      @media (max-width: 520px) {{
        .metrics-grid {{ grid-template-columns: 1fr; }}
        .shell {{ padding: 20px 14px 40px; }}
      }}
    </style>
  </head>
  <body>
    <main class="shell">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark" aria-hidden="true"></div>
          <div class="brand-copy">
            <strong>AI PR Review Bot</strong>
            <p>GitHub App control plane and review operations dashboard</p>
          </div>
        </div>
        <nav class="nav">
          <a href="/">Dashboard</a>
          <a href="/jobs">Jobs API</a>
          <a href="/metrics">Metrics</a>
          <a href="/readyz">Readiness</a>
        </nav>
      </header>
      {body}
      <footer class="footer">
        <span>Version {escape(app_version)}</span>
        <span>Built for multi-repo AI pull request review operations</span>
      </footer>
    </main>
  </body>
</html>
"""


def _metric_card(label: str, value: str, caption: str) -> str:
    return f"""
    <article class="metric-card card">
      <div class="label">{escape(label)}</div>
      <div class="value">{escape(value)}</div>
      <div class="caption">{escape(caption)}</div>
    </article>
    """


def _flow_step(title: str, body: str) -> str:
    return f"<div class='flow-step'><strong>{escape(title)}</strong><span>{escape(body)}</span></div>"


def _pill(label: str, tone: str) -> str:
    return f"<span class='pill {escape(tone)}'>{escape(label)}</span>"


def _seconds_label(value: float | int | None) -> str:
    if value is None:
        return "Pending"
    numeric = float(value)
    if numeric < 1:
        return f"{numeric:.2f}s"
    if numeric < 60:
        return f"{numeric:.1f}s"
    minutes, seconds = divmod(int(round(numeric)), 60)
    return f"{minutes}m {seconds}s"


def _timestamp_label(value: str | None) -> str:
    if not value:
        return "Pending"
    return value.replace("T", " ").replace("+00:00", " UTC")
