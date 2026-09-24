// Shared by all three dashboard prototypes: data access, demo data and small helpers.
// Opened from `factory ui` it reads the real runs; with ?demo (or from file://) it
// uses a simulated factory whose running runs keep moving.

const STEPS = ["prepare", "plan", "implement", "review", "ship", "learn"];
const ARTIFACTS = ["task.md", "prepare.md", "spec.md", "implement.md", "checks.md", "review.md", "ship.md", "learning.md"];
const STEP_ARTIFACT = { prepare: "prepare.md", plan: "spec.md", implement: "checks.md", review: "review.md", ship: "ship.md", learn: "learning.md" };
const MIN = 60_000;
const AGENTS = { planner: "plan", implementer: "implement", reviewer: "review", scribe: "learn" }; // agent -> its step colour

const Factory = {
  demo: new URLSearchParams(location.search).has("demo") || location.protocol === "file:",

  async runs() {
    if (!this.demo) {
      try { return await (await fetch("/api/runs")).json(); } catch { this.demo = true; }
    }
    return Demo.runs().map(({ events, artifacts, ...summary }) => summary);
  },

  async run(id) {
    if (!this.demo) return (await fetch(`/api/runs/${id}`)).json();
    return Demo.runs().find((run) => run.id === id);
  },

  // A null answer means "approve" or "let the agent decide".
  answer(runId, questionId, answer) {
    if (this.demo) return Demo.answer(runId, questionId, answer);
    return this.post(`/api/runs/${runId}/answer`, { question: questionId, answer });
  },

  resume(runId, step, guidance) {
    if (this.demo) return Demo.resume(runId, step, guidance);
    return this.post(`/api/runs/${runId}/resume`, { step, guidance });
  },

  async post(url, body) {
    const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Factory": "1" }, body: JSON.stringify(body) });
    if (!response.ok) throw new Error((await response.text()).match(/<p>Message: (.*?)\.<\/p>/)?.[1] ?? response.statusText);
    return response.json();
  },

  // Calls `render` now and every `ms` after, which is enough for a local dashboard.
  poll(render, ms = 2000) {
    render();
    return setInterval(render, ms);
  },
};

// ---------- helpers ----------

const esc = (text = "") =>
  String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function duration(ms) {
  if (ms == null || ms < 0) return "";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

function ago(iso) {
  const ms = Date.now() - new Date(iso);
  if (ms < MIN) return "just now";
  if (ms < 60 * MIN) return `${Math.floor(ms / MIN)}m ago`;
  if (ms < 24 * 60 * MIN) return `${Math.floor(ms / 60 / MIN)}h ago`;
  return new Date(iso).toLocaleDateString();
}

const agentColor = (agent) => `var(--${AGENTS[agent] ?? "prepare"})`;
const tokens = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k` : String(n ?? 0));
const turnsOf = (run) => run.events.filter((e) => e.usage);

// Per agent: model turns, tool calls, tokens spent and fullest context. The server sends the same shape.
function usageOf(events) {
  const agents = {};
  for (const e of events.filter((e) => e.usage)) {
    const a = (agents[e.agent] ??= { turns: 0, tools: 0, tokens: 0, peak: 0 });
    a.turns += 1; a.tools += e.tools.length; a.tokens += e.usage.context + e.usage.output; a.peak = Math.max(a.peak, e.usage.context);
  }
  return agents;
}

const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const hhmm = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

function stepDuration(step) {
  if (!step.started_at) return null;
  return new Date(step.finished_at ?? Date.now()) - new Date(step.started_at);
}

function runDuration(run) {
  const started = run.steps.find((s) => s.started_at)?.started_at;
  if (!started) return null;
  const last = [...run.steps].reverse().find((s) => s.finished_at)?.finished_at;
  return new Date(run.status === "running" ? Date.now() : last ?? Date.now()) - new Date(started);
}

// Artifacts in pipeline order, and the one worth opening first: the file for the step the run is on.
const artifactNames = (run) => [...ARTIFACTS.filter((a) => a in run.artifacts), ...Object.keys(run.artifacts).filter((a) => !ARTIFACTS.includes(a))];
function focusArtifact(run) {
  const wanted = run.status === "done" ? "learning.md" : STEP_ARTIFACT[run.step];
  return run.artifacts[wanted] ? wanted : artifactNames(run).at(-1);
}

// Everything waiting on a human, oldest first, each tagged with its run.
const allNeeds = (runs) =>
  runs.flatMap((run) => (run.needs ?? []).map((need) => ({ ...need, run })))
    .sort((a, b) => new Date(a.asked_at) - new Date(b.asked_at));
const needKey = (run, need) => `${run.id}/${need.id}/${need.asked_at}`;
const NEED_LABEL = { question: "Question", spec: "Approve spec", code: "Approve changes", escalation: "Escalated" };

const needsHuman = (run) => run.status === "escalated" || run.status === "failed";
const isActive = (run) => run.status === "running";
const doneSteps = (run) => run.steps.filter((s) => s.status === "done").length;

// The implement attempt a run is on, read from its notes ("checks passed on attempt 2").
function attempt(run) {
  const note = run.steps.find((s) => s.name === "implement")?.note ?? "";
  return Number(note.match(/attempt (\d+)/)?.[1] ?? 0) || null;
}

function stats(runs) {
  const finished = runs.filter((r) => r.status === "done" || needsHuman(r));
  const shipped = runs.filter((r) => r.status === "done");
  const leads = shipped.map(runDuration).filter(Boolean).sort((a, b) => a - b);
  return {
    total: runs.length,
    active: runs.filter(isActive).length,
    needsHuman: runs.filter(needsHuman).length,
    shipped: shipped.length,
    successRate: finished.length ? Math.round((shipped.length / finished.length) * 100) : null,
    medianLead: leads.length ? leads[Math.floor(leads.length / 2)] : null,
  };
}

// Tiny markdown: headings, fenced code, lists, bold, inline code, links. Escapes everything else.
function md(text = "") {
  const inline = (s) =>
    esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(https?:\/\/[^\s)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  const html = [];
  let code = null, list = false;
  for (const line of text.split("\n")) {
    if (line.startsWith("```")) {
      if (code === null) { code = []; } else { html.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); code = null; }
      continue;
    }
    if (code !== null) { code.push(line); continue; }
    const item = line.match(/^\s*[-*] (.*)/);
    if (item && !list) { html.push("<ul>"); list = true; }
    if (!item && list) { html.push("</ul>"); list = false; }
    const heading = line.match(/^(#{1,4}) (.*)/);
    if (heading) html.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`);
    else if (item) html.push(`<li>${inline(item[1])}</li>`);
    else if (line.trim()) html.push(`<p>${inline(line)}</p>`);
  }
  if (list) html.push("</ul>");
  if (code !== null) html.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
  return html.join("");
}

function copy(text, button) {
  navigator.clipboard?.writeText(text);
  if (!button) return;
  const label = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => (button.textContent = label), 1200);
}

// ---------- demo factory ----------

const Demo = (() => {
  const boot = Date.now();
  const answered = new Map(); // "runId/questionId" -> { text, at }
  const resumed = new Map(); // runId -> { step, guidance, at }
  const at = (minutesAgo) => new Date(boot - minutesAgo * MIN).toISOString();

  // Each script entry: [step, status, minutes it took (or has been running), note]
  const scripts = [
    {
      title: "Add --json flag to the export command", kind: "software", size: "simple", source: "issue",
      url: "https://github.com/acme/shop/issues/412", ago: 14,
      steps: [["prepare", "done", 0.4, "factory/add-json at .factory/worktrees/add-json"], ["plan", "done", 3.1, "software, simple"],
              ["implement", "running", 10.5, ""]],
      extra: { implement: [["implementing, attempt 1 of 3"], ["1 of 2 checks failed", "warn"], ["implementing, attempt 2 of 3"]] },
    },
    {
      title: "Fix flaky test_checkout_timeout", kind: "software", size: "simple", source: "text", ago: 95, pr: 1289,
      steps: [["prepare", "done", 0.5], ["plan", "done", 2.2, "software, simple"], ["implement", "done", 8.4, "checks passed on attempt 1"],
              ["review", "done", 3.0, "approve"], ["ship", "done", 0.3, "https://github.com/acme/shop/pull/1289"], ["learn", "done", 0.6]],
    },
    {
      title: "Add dbt model fct_orders with grain tests", kind: "data", size: "standard", source: "file", url: "tasks/fct_orders.md", ago: 62,
      steps: [["prepare", "done", 1.8, "hydrated: dbt deps"], ["plan", "done", 6.5, "data, standard"],
              ["implement", "escalated", 31, "checks still failing after 2 retries, see checks.md"]],
      extra: { implement: [["implementing, attempt 1 of 3"], ["1 of 3 checks failed", "warn"], ["implementing, attempt 2 of 3"],
                           ["1 of 3 checks failed", "warn"], ["implementing, attempt 3 of 3"], ["1 of 3 checks failed", "warn"]] },
    },
    {
      title: "Raise eval threshold for the summarizer prompt", kind: "ai", size: "standard", source: "issue",
      url: "https://github.com/acme/ml/issues/77", ago: 4,
      steps: [["prepare", "done", 0.6], ["plan", "running", 3.4, ""]],
      ask: { id: "q7f3a1c2", kind: "question", ago: 1.5,
             text: "Should the new 0.82 threshold apply to every summarizer variant, or only summarizer-v2? v1 scores 0.79 today and would start failing." },
    },
    {
      title: "Add cursor pagination to GET /orders", kind: "software", size: "standard", source: "issue",
      url: "https://github.com/acme/shop/issues/421", ago: 9,
      steps: [["prepare", "done", 0.5], ["plan", "running", 8.5, ""]],
      ask: { id: "q19be0d4", kind: "spec", ago: 3, text: "Approve the spec? Answer with the changes you want, or leave it empty to approve." },
    },
    {
      title: "Rename Customer.fullname to full_name", kind: "software", size: "simple", source: "text", ago: 180,
      steps: [["prepare", "done", 0.3], ["plan", "done", 1.6, "software, simple"], ["implement", "done", 5.2, "checks passed on attempt 2"],
              ["review", "done", 2.1, "approve"], ["ship", "done", 0.2, "branch factory/rename-fullname is ready in .factory/worktrees/rename-fullname"],
              ["learn", "done", 0.5]],
    },
    {
      title: "Add rate limiting to /api/login", kind: "software", size: "standard", source: "text", ago: 240,
      steps: [["prepare", "escalated", 2.4, "hydration failed, see prepare.md"]],
    },
    {
      title: "Refactor retry helper into a decorator", kind: "software", size: "standard", source: "issue",
      url: "https://github.com/acme/shop/issues/398", ago: 38,
      steps: [["prepare", "done", 0.4], ["plan", "done", 4.8, "software, standard"], ["implement", "done", 14.2, "checks passed on attempt 1"],
              ["review", "running", 18, ""]],
      extra: { review: [["review: request_changes: jitter is applied twice on the last retry", "warn"], ["implementing, attempt 1 of 3"]] },
    },
    {
      title: "Document the webhook signature check", kind: "software", size: "simple", source: "text", ago: 300, pr: 1270,
      steps: [["prepare", "done", 0.3], ["plan", "done", 1.2, "software, simple"], ["implement", "done", 3.9, "checks passed on attempt 1"],
              ["review", "done", 1.4, "approve"], ["ship", "done", 0.4, "https://github.com/acme/shop/pull/1270"], ["learn", "done", 0.4]],
    },
  ];

  const TOOLS = {
    planner: ["Read README.md", "Glob **/*.py", "Grep def export", "Read pyproject.toml", "WebSearch click json output"],
    implementer: ["Read src/export.py", "Edit src/export.py", "Bash uv run pytest tests/test_export.py -q", "Write tests/test_export.py",
                  "Grep json.dumps", "Bash uv run ruff check src", "Skill software"],
    reviewer: ["Read src/export.py", "Bash git diff --stat", "Bash uv run pytest -q", "Edit src/export.py"],
    scribe: [],
  };

  // Simulated model turns between two times: tool calls, a context that grows and is compacted near 170k.
  function turns(agent, step, from, to, seed) {
    const random = (i) => (Math.sin(seed * 7919 + i * 104729) + 1) / 2;
    const count = agent === "scribe" ? 1 : Math.min(60, Math.max(2, Math.round((to - from) / 20_000)));
    let context = 4_000 + random(0) * 6_000;
    return Array.from({ length: count }, (_, i) => {
      const last = i === count - 1 && agent !== "implementer";
      const tools = last ? [] : Array.from({ length: 1 + Math.floor(random(i + 1) * 2.4) }, (_, j) => TOOLS[agent][Math.floor(random(i * 3 + j) * TOOLS[agent].length)]);
      context += 1_500 + random(i + 7) * 6_500;
      if (context > 170_000) context = 32_000;
      const usage = { context: Math.round(context), output: Math.round(150 + random(i + 3) * 1_400) };
      return { at: new Date(from + ((to - from) * (i + 1)) / (count + 1)).toISOString(), step, level: "debug", message: tools.join(" · ") || "replied", agent, tools, usage };
    });
  }

  function build(script, index) {
    const id = `20260923-${String(100000 + index * 1111).slice(0, 6)}-${script.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40).replace(/-$/, "")}`;
    let minutes = script.ago;
    const events = [];
    const steps = STEPS.map((name) => ({ name, status: "pending", started_at: null, finished_at: null, note: "" }));

    for (const [name, status, took, note = ""] of script.steps) {
      const step = steps.find((s) => s.name === name);
      step.started_at = at(minutes);
      events.push({ at: at(minutes), step: name, level: "info", message: "started" });
      const extra = script.extra?.[name] ?? [];
      extra.forEach(([message, level = "info"], i) =>
        events.push({ at: at(minutes - (took * (i + 1)) / (extra.length + 1)), step: name, level, message }));
      const agent = Object.keys(AGENTS).find((a) => AGENTS[a] === name);
      const end = status === "running" ? Date.now() : boot - (minutes - took) * MIN;
      if (agent) events.push(...turns(agent, name, boot - minutes * MIN, end, index + STEPS.indexOf(name)));
      if (status === "running") {
        step.status = "running";
      } else {
        minutes -= took;
        Object.assign(step, { status, finished_at: at(minutes), note });
        const level = status === "done" ? "info" : "warn";
        events.push({ at: at(minutes), step: name, level, message: note ? `${status}: ${note}` : status });
      }
    }
    const again = resumed.get(id);
    if (again) {
      const from = STEPS.indexOf(again.step);
      for (const step of steps.slice(from)) Object.assign(step, { status: "pending", started_at: null, finished_at: null, note: "" });
      Object.assign(steps[from], { status: "running", started_at: new Date(again.at).toISOString() });
      events.push({ at: new Date(again.at).toISOString(), step: again.step, level: "info", message: "started" });
      if (again.guidance) events.push({ at: new Date(again.at + 400).toISOString(), step: again.step, level: "info", message: `guidance from a human: ${again.guidance}` });
    }

    const needs = [];
    const ask = script.ask;
    if (ask && !again) {
      const step = steps.find((s) => s.status === "running")?.name;
      events.push({ at: at(ask.ago), step, level: "warn", message: `waiting for a human: ${ask.text}` });
      const reply = answered.get(`${id}/${ask.id}`);
      if (reply) events.push({ at: new Date(reply.at).toISOString(), step, level: "info", message: `human answered: ${reply.text ?? "go ahead"}` });
      else needs.push({ id: ask.id, kind: ask.kind, step, text: ask.text, asked_at: at(ask.ago) });
    }
    const stuck = steps.find((s) => s.status === "escalated" || s.status === "failed");
    if (stuck) needs.push({ id: "escalation", kind: "escalation", step: stuck.name, text: stuck.note, asked_at: stuck.finished_at });
    events.sort((a, b) => new Date(a.at) - new Date(b.at));

    const status = steps.find((s) => s.status !== "done")?.status ?? "done";
    const planned = steps[1].status === "done";
    const pr = script.pr && `https://github.com/acme/shop/pull/${script.pr}`;
    return {
      id, title: script.title, source: script.source, url: script.url ?? null, status,
      step: steps.find((s) => s.status !== "done")?.name ?? null,
      kind: planned ? script.kind : null, size: planned ? script.size : null, branch: `factory/${id}`, workspace: `.factory/worktrees/${id}`,
      pr_url: pr ?? null, created_at: at(script.ago), steps, needs, events, artifacts: artifacts(script, steps), usage: usageOf(events),
    };
  }

  function artifacts(script, steps) {
    const reached = (name) => steps.find((s) => s.name === name).status !== "pending";
    const files = { "task.md": `# ${script.title}\n\n${script.url ? `Source: ${script.url}` : "Typed in the CLI."}\n` };
    if (reached("plan") && (steps[1].status === "done" || script.ask?.kind === "spec")) {
      files["spec.md"] = `# ${script.title}\n\n\`${script.kind}\` · \`${script.size}\`\n\n## Purpose\n\nMake the change described in the task with no behaviour change elsewhere.\n\n## Scenarios\n\n**happy path**\n- Given an existing project\n- When the change is applied\n- Then the acceptance commands pass\n\n## Must not infer\n\n- Do not add new dependencies.\n- Do not change public names beyond the task.\n\n## Acceptance\n\n- \`uv run pytest -q\`\n- \`uv run ruff check .\`\n`;
    }
    if (reached("implement")) {
      const failing = steps[2].status !== "done";
      files["checks.md"] = failing
        ? "# Checks\n\n- pass `uv run ruff check .`\n- FAIL `uv run pytest -q`\n\nThe following checks failed. Fix them without weakening the checks.\n\n### `uv run pytest -q`\n```\nFAILED tests/test_models.py::test_grain - AssertionError: 2 duplicate order_id\n1 failed, 41 passed in 3.2s\n```\n"
        : "# Checks\n\n- pass `uv run ruff check .`\n- pass `uv run pytest -q`\n";
    }
    if (steps[3].status === "done") files["review.md"] = "# Review: approve\n\n## Summary\n\nMatches the spec, tests cover the success and failure scenarios. Renamed one local variable for clarity.\n";
    if (steps[4].status === "done") files["ship.md"] = `# Shipped\n\n${steps[4].note}\n`;
    if (steps[5].status === "done") files["learning.md"] = "# What happened\n\nThe test sometimes failed because it waited on a real clock. We gave it a fake clock, so it now takes the same path every time.\n\n**Try it:** `uv run pytest tests/test_checkout.py -q`\n";
    if (steps[0].status === "escalated") files["prepare.md"] = "# Hydration\n\n- FAIL `uv sync`\n\n```\nerror: Failed to fetch: https://pypi.internal/simple/limits/\n```\n";
    return files;
  }

  const idOf = (runId) => scripts.map(build).find((run) => run.id === runId);
  return {
    runs: () => scripts.map(build),
    answer(runId, questionId, text) {
      answered.set(`${runId}/${questionId}`, { text: text || null, at: Date.now() });
      return Promise.resolve({ id: questionId });
    },
    resume(runId, step, guidance) {
      if (idOf(runId)?.status === "running") return Promise.reject(new Error("run is already running"));
      resumed.set(runId, { step, guidance: guidance || null, at: Date.now() });
      return Promise.resolve({ resumed: runId, from: step });
    },
  };
})();
