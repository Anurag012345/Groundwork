"use client";

import { FormEvent, useState } from "react";

type KnowledgeBase = { id: string; name: string; description: string; created_at: string };
type Tenant = { id: string; name: string };
type ChatSource = { id: number; document_name: string; page_number?: number; section?: string; excerpt: string };

export default function Home() {
  const [key, setKey] = useState("");
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [chatBase, setChatBase] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<ChatSource[]>([]);

  async function api(path: string, method = "GET", body?: object) {
    const response = await fetch("/api/backend/v1/" + path, {
      method, headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(typeof data.detail === "string" ? data.detail : "Please check the supplied values.");
    }
    return response.status === 204 ? null : response.json();
  }

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const identity = await api("me");
      const data = await api("knowledge-bases");
      setTenant(identity); setBases(data.items);
      setChatBase(data.items[0]?.id || "");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const created = await api("knowledge-bases", "POST", { name, description });
      setBases((current) => [created, ...current]); setName(""); setDescription("");
      if (!chatBase) setChatBase(created.id);
      setNotice("Knowledge base created.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function remove(base: KnowledgeBase) {
    if (!window.confirm('Delete "' + base.name + '"?')) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api("knowledge-bases/" + base.id, "DELETE");
      setBases((current) => current.filter((item) => item.id !== base.id));
      if (chatBase === base.id) setChatBase(bases.find((item) => item.id !== base.id)?.id || "");
      setNotice("Knowledge base deleted.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function upload(base: KnowledgeBase, file: File | undefined) {
    if (!file) return;
    setBusy(true); setError(""); setNotice("");
    const form = new FormData(); form.set("file", file);
    try {
      const response = await fetch(`/api/backend/v1/knowledge-bases/${base.id}/documents`, {
        method: "POST", headers: { Authorization: "Bearer " + key }, body: form,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Upload failed.");
      setNotice(`${data.name} uploaded. Generating its search index…`);
      const processed = await api(`ingestion-jobs/${data.job_id}/process`, "POST");
      setNotice(`${data.name} is ready with ${processed.chunk_count} searchable chunks.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!chatBase || !question.trim()) return;
    setBusy(true); setError(""); setNotice(""); setAnswer(""); setSources([]);
    try {
      const response = await fetch("/api/backend/v1/chat/stream", {
        method: "POST",
        headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" },
        body: JSON.stringify({ knowledge_base_id: chatBase, question, top_k: 5 }),
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(typeof data.detail === "string" ? data.detail : "Unable to answer the question.");
      }
      if (!response.body) throw new Error("This browser could not open the response stream.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        for (const frame of frames) {
          const lines = frame.split(/\r?\n/);
          const eventName = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
          const encoded = lines.filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart()).join("\n");
          if (!encoded) continue;
          const data = JSON.parse(encoded);
          if (eventName === "token") setAnswer((current) => current + data.text);
          if (eventName === "sources") setSources(data);
          if (eventName === "error") throw new Error(data.detail || "The model provider failed.");
        }
        if (done) break;
      }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <div className="shell">
    <aside>
      <a className="brand" href="/"><span className="mark">k</span> knowledge<span className="brand-light">studio</span></a>
      <div className="workspace-label">WORKSPACE</div>
      <div className="workspace"><span className="avatar">{tenant?.name[0]?.toUpperCase() || "W"}</span><div>{tenant?.name || "Your workspace"}<small>{tenant ? "Connected" : "Connect to get started"}</small></div></div>
      <nav aria-label="Workspace navigation"><span className="active">▤ &nbsp; Knowledge bases</span><span>◌ &nbsp; Chat playground <small>Coming next</small></span><span>◇ &nbsp; Chatbots <small>Coming next</small></span></nav>
      <div className="aside-footer"><span className="dot" /> Local development <p>Your knowledge. Your workspace.</p></div>
    </aside>
    <main>
      <header><span>Workspace / Knowledge bases</span><span className="pill">Foundation release</span></header>
      <section className="heading"><div className="eyebrow">YOUR SOURCE OF TRUTH</div><h1>A home for your knowledge.</h1><p>Create dedicated collections for the information your chatbot will use.</p></section>
      {error && <div className="message error" role="alert">{error}</div>}
      {notice && <div className="message success" role="status">{notice}</div>}
      {!tenant ? <section className="connect panel"><div><span className="section-number">01 / CONNECT</span><h2>Open your workspace</h2><p>Enter your organization’s API key to manage its knowledge bases.</p><p className="muted">Your key stays in this browser tab’s memory and is cleared when you disconnect or refresh.</p></div><form onSubmit={connect}><label htmlFor="key">Workspace API key</label><input id="key" type="password" autoComplete="off" required value={key} onChange={(e) => setKey(e.target.value)} placeholder="rag_…" /><button disabled={busy}>{busy ? "Connecting…" : "Connect workspace →"}</button></form></section> :
      <><div className="section-top"><h2>Knowledge bases <span className="count">{bases.length}</span></h2><button className="secondary" disabled={busy} onClick={() => { setTenant(null); setKey(""); setBases([]); setError(""); setNotice(""); }}>Disconnect</button></div>
        <div className="content-grid"><section className="bases">
          {bases.length === 0 ? <div className="empty panel"><div className="empty-icon">▤</div><h3>Your first knowledge base starts here</h3><p>Give it a name, like “Customer support” or “Product documentation”.</p></div> : bases.map((base) => <article className="base panel" key={base.id}><span className="folder">▤</span><h3>{base.name}</h3><p>{base.description || "No description yet."}</p><label className="upload">Add a document<input type="file" disabled={busy} accept=".pdf,.docx,.txt,.md,.html,.htm" onChange={(event) => { void upload(base, event.target.files?.[0]); event.target.value = ""; }} /></label><footer><span>Created {new Date(base.created_at).toLocaleDateString()}</span><button className="delete" disabled={busy} onClick={() => remove(base)} aria-label={"Delete " + base.name}>Delete</button></footer></article>)}
        </section><form className="panel create" onSubmit={create}><span className="section-number">NEW COLLECTION</span><h2>Create a knowledge base</h2><label htmlFor="name">Name</label><input id="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="e.g. Customer support" required /><label htmlFor="description">Description <span className="optional">(optional)</span></label><textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} placeholder="What belongs in this collection?" rows={4} /><button disabled={busy || !name.trim()}>{busy ? "Working…" : "Create knowledge base +"}</button></form></div></>}
      {tenant && <section className="playground panel"><div><span className="section-number">RAG PLAYGROUND</span><h2>Ask your knowledge base</h2><p>Answers use only active, indexed documents and include their sources.</p></div><form onSubmit={ask}><label htmlFor="chat-base">Knowledge base</label><select id="chat-base" value={chatBase} onChange={(event) => setChatBase(event.target.value)} disabled={busy || bases.length === 0}>{bases.length === 0 && <option value="">Create a knowledge base first</option>}{bases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}</select><label htmlFor="question">Question</label><textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} maxLength={4000} placeholder="What would you like to know?" required /><button disabled={busy || !chatBase || !question.trim()}>{busy ? "Working…" : "Ask question →"}</button></form>{answer && <div className="answer"><span>ANSWER</span><p>{answer}</p>{sources.length > 0 && <ol>{sources.map((source) => <li key={source.id}><strong>[{source.id}] {source.document_name}</strong>{source.page_number && ` · page ${source.page_number}`}{source.section && ` · ${source.section}`}<small>{source.excerpt}</small></li>)}</ol>}</div>}</section>}
      <section className="next-step"><span>UP NEXT</span><p>Durable queue delivery, private Vercel Blob uploads, conversation history, and the embeddable widget.</p></section>
    </main>
  </div>;
}
