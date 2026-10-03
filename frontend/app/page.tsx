"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getRun, resumeRun, startRun, type Run } from "@/lib/api";

const STAGES = [
  { label: "Safety check", hint: "Moderation and PII masking" },
  { label: "Research", hint: "Gathers notes with the search tool" },
  { label: "Plan", hint: "Splits the work for each agent" },
  { label: "Write", hint: "Drafts the article" },
  { label: "Edit", hint: "Scores the draft and sends notes back" },
  { label: "SEO", hint: "Title, description, keywords, slug" },
  { label: "Your review", hint: "Approve or request changes" },
  { label: "Publish", hint: "Adds front matter and publishes" },
];

type StageState = "done" | "active" | "pending" | "failed";

function stageStates(run: Run | null): StageState[] {
  if (!run) return STAGES.map(() => "pending");
  const v = run.values;
  const done = [
    v.initial_route === "researcher",
    !!v.research_notes,
    !!v.plan,
    !!v.markdown_content,
    v.editor_score != null,
    !!v.seo,
    run.status === "completed",
    run.status === "completed",
  ];
  let active = done.findIndex((d) => !d);
  if (run.status === "awaiting_approval") active = 6;
  const rewriting = v.human_approval && !v.human_approval.human_approved;
  if (run.status === "running" && rewriting) active = 3;
  if (run.status === "completed") active = -1;
  const failedAt = run.status === "blocked" ? 0 : run.status === "error" ? Math.max(active, 0) : -1;

  return STAGES.map((_, i) => {
    if (i === failedAt) return "failed";
    if (run.status === "blocked") return "pending";
    if (i < active || active === -1) return "done";
    if (i === active) return "active";
    return "pending";
  });
}

function Rail({ run }: { run: Run | null }) {
  const states = stageStates(run);
  return (
    <ol className="rail" aria-label="Pipeline progress">
      {STAGES.map((s, i) => (
        <li key={s.label} className={`stage ${states[i]}`}>
          <span className="dot" aria-hidden>
            {states[i] === "done" ? "✓" : states[i] === "failed" ? "!" : i + 1}
          </span>
          <span>
            <strong>{s.label}</strong>
            <small>{s.hint}</small>
          </span>
        </li>
      ))}
    </ol>
  );
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Home() {
  const [topic, setTopic] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [poll, setPoll] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!threadId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const r = await getRun(threadId);
        if (stop) return;
        setRun(r);
        if (r.status === "running") timer = setTimeout(tick, 1500);
      } catch (e) {
        if (!stop) setError((e as Error).message);
      }
    };
    tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [threadId, poll]);

  async function onStart(e: React.FormEvent) {
    e.preventDefault();
    if (topic.trim().length < 2) return;
    setBusy(true);
    setError(null);
    setRun(null);
    setAsking(false);
    setFeedback("");
    try {
      const { thread_id } = await startRun(topic.trim());
      setThreadId(thread_id);
      setPoll((p) => p + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onDecide(approved: boolean) {
    if (!threadId) return;
    setBusy(true);
    setError(null);
    try {
      await resumeRun(threadId, approved, approved ? undefined : feedback.trim());
      setAsking(false);
      setFeedback("");
      setRun((r) => (r ? { ...r, status: "running", interrupt: null } : r));
      setPoll((p) => p + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const v = run?.values ?? {};
  const working = run?.status === "running" || (!!threadId && !run && !error);
  const finished = run?.status === "completed" || run?.status === "blocked" || run?.status === "error";
  const draft = run?.interrupt?.["markdown content"] ?? v.markdown_content;
  const final = run?.status === "completed" ? v.markdown_content : undefined;

  return (
    <main className="shell">
      <header className="top">
        <h1>Content Offloader</h1>
        <p>Give it a topic. Review the draft it produces before anything is published.</p>
        <form onSubmit={onStart} className="topic">
          <label htmlFor="topic" className="sr">Topic</label>
          <input
            id="topic"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Prompt caching for LLM apps"
            disabled={working || run?.status === "awaiting_approval"}
            maxLength={500}
          />
          <button className="primary" disabled={busy || working || topic.trim().length < 2 || run?.status === "awaiting_approval"}>
            {finished ? "Write another article" : "Write article"}
          </button>
        </form>
      </header>

      {error && <div className="note bad" role="alert">{error}</div>}

      <div className="grid">
        <aside><Rail run={run} /></aside>

        <section className="main">
          {!threadId && (
            <div className="empty">
              <h2>No article yet</h2>
              <p>Enter a topic above and select Write article. Research and drafting take a minute or two.</p>
            </div>
          )}

          {working && !draft && <p className="status">Working on “{v.topic ?? topic}”…</p>}

          {run?.status === "blocked" && (
            <div className="note bad">
              The safety check blocked this topic. Try a different one.
            </div>
          )}

          {run?.status === "error" && (
            <div className="note bad">
              The pipeline stopped: {run.error}
            </div>
          )}

          {v.research_notes && (
            <details className="panel">
              <summary>Research notes</summary>
              <div className="prose small"><ReactMarkdown>{v.research_notes}</ReactMarkdown></div>
            </details>
          )}

          {draft && !final && (
            <article className="panel">
              <div className="panel-head">
                <h2>Draft</h2>
                <div className="chips">
                  {v.editor_score != null && <span className="chip">Editor score {v.editor_score}/10</span>}
                  {!!v.writer_editor_iterations && <span className="chip">{v.writer_editor_iterations} editor rewrite{v.writer_editor_iterations > 1 ? "s" : ""}</span>}
                  {!!v.writer_human_iterations && <span className="chip">{v.writer_human_iterations} requested change{v.writer_human_iterations > 1 ? "s" : ""}</span>}
                </div>
              </div>
              <div className="prose"><ReactMarkdown>{draft}</ReactMarkdown></div>
              {v.editor_feedback && (
                <details className="sub"><summary>Editor feedback</summary><p>{v.editor_feedback}</p></details>
              )}
            </article>
          )}

          {v.seo && (
            <section className="panel">
              <h2>SEO</h2>
              <dl className="seo">
                <dt>Title</dt><dd>{v.seo.title} <em>{v.seo.title.length}/60</em></dd>
                <dt>Description</dt><dd>{v.seo.metadata} <em>{v.seo.metadata.length}/160</em></dd>
                <dt>Slug</dt><dd><code>{v.seo.slug}</code></dd>
                <dt>Keywords</dt>
                <dd className="chips">{v.seo.keywords.map((k) => <span className="chip" key={k}>{k}</span>)}</dd>
              </dl>
            </section>
          )}

          {run?.status === "awaiting_approval" && (
            <section className="panel review">
              <h2>Publish this article?</h2>
              {asking ? (
                <>
                  <label htmlFor="fb">What should the writer change?</label>
                  <textarea
                    id="fb"
                    rows={4}
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    placeholder="e.g. Shorter intro, add a concrete example."
                  />
                  <div className="row">
                    <button className="primary" disabled={busy || !feedback.trim()} onClick={() => onDecide(false)}>Send to writer</button>
                    <button className="ghost" onClick={() => setAsking(false)}>Cancel</button>
                  </div>
                </>
              ) : (
                <div className="row">
                  <button className="primary" disabled={busy} onClick={() => onDecide(true)}>Approve and publish</button>
                  <button className="ghost" disabled={busy} onClick={() => setAsking(true)}>Request changes</button>
                </div>
              )}
            </section>
          )}

          {final && (
            <section className="panel done">
              <div className="panel-head">
                <h2>Published</h2>
                <div className="row">
                  <button className="ghost" onClick={async () => { await navigator.clipboard.writeText(final); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                    {copied ? "Copied" : "Copy markdown"}
                  </button>
                  <button className="ghost" onClick={() => download(`${v.seo?.slug || "article"}.md`, final)}>Download .md</button>
                </div>
              </div>
              <pre>{final}</pre>
            </section>
          )}
        </section>
      </div>
    </main>
  );
}
