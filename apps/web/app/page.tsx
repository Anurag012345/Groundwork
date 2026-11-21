"use client";

import { FormEvent, useState } from "react";

type KnowledgeBase = { id: string; name: string; description: string; created_at: string };
type Tenant = { id: string; name: string };
type ChatSource = { id: number; document_name: string; page_number?: number; section?: string; excerpt: string };
type Chatbot = { id: string; public_key: string; name: string; greeting: string; allowed_origins: string[]; knowledge_base_id: string };
type Doc = {
  id: string; name: string; version: number; status: string; error_message: string | null;
  metadata: Record<string, string | number | boolean>;
};

// Tags are typed as `key=value` pairs separated by commas or new lines, and always saved as text:
// a filter matches the exact stored value, so "2026" and 2026 are different.
function parseTags(text: string): Record<string, string> {
  const tags: Record<string, string> = {};
  for (const part of text.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)) {
    const at = part.indexOf("=");
    const name = part.slice(0, at).trim();
    const value = part.slice(at + 1).trim();
    if (at < 1 || !value) throw new Error(`"${part}" should look like key=value.`);
    if (name.length > 64 || value.length > 200) throw new Error(`"${part}" is too long.`);
    tags[name] = value;
  }
  if (Object.keys(tags).length > 20) throw new Error("Use at most 20 tags.");
  return tags;
}

function formatTags(tags: Record<string, string | number | boolean>): string {
  return Object.entries(tags).map(([name, value]) => `${name}=${value}`).join(", ");
}

export default function Home() {
  const [key, setKey] = useState("");
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [docs, setDocs] = useState<Record<string, Doc[]>>({});
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [chatBase, setChatBase] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<ChatSource[]>([]);
  const [bots, setBots] = useState<Chatbot[]>([]);
  const [botName, setBotName] = useState("");
  const [botBase, setBotBase] = useState("");
  const [botGreeting, setBotGreeting] = useState("");
  const [botOrigins, setBotOrigins] = useState("");
  // Where this workspace's API answers from. The dashboard reaches it through a
  // server-side proxy and so cannot discover it, but the snippet must name it.
  const [apiOrigin, setApiOrigin] = useState("http://localhost:8000");
  const [copied, setCopied] = useState("");
  // Signing in with an email and password is the default; the API key stays as the other way in.
  const [useKey, setUseKey] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signedIn, setSignedIn] = useState(false);
  const [uploadTags, setUploadTags] = useState("");
  const [filterText, setFilterText] = useState("");
  const [tagging, setTagging] = useState<{ id: string; text: string } | null>(null);

  async function api(path: string, method = "GET", body?: object, token = key) {
    const response = await fetch("/api/backend/v1/" + path, {
      method, headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(typeof data.detail === "string" ? data.detail : "Please check the supplied values.");
    }
    return response.status === 204 ? null : response.json();
  }

  // `token` is passed in because a sign-in has only just produced it and state has not caught up.
  async function load(token: string) {
    const identity = await api("me", "GET", undefined, token);
    const data = await api("knowledge-bases", "GET", undefined, token);
    const botList = await api("chatbots", "GET", undefined, token);
    setTenant(identity); setBases(data.items); setBots(botList.items);
    setChatBase(data.items[0]?.id || "");
    setBotBase(data.items[0]?.id || "");
    await Promise.all(data.items.map((base: KnowledgeBase) => loadDocs(base.id, token)));
  }

  async function connect(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try { await load(key); setSignedIn(false); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch("/api/backend/v1/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not sign in.");
      setKey(data.token); setPassword("");
      await load(data.token);
      setSignedIn(true);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    // Signing out ends the session on the server too; an API key is only forgotten here.
    if (signedIn) await api("auth/logout", "POST").catch(() => undefined);
    setTenant(null); setKey(""); setSignedIn(false); setBases([]); setBots([]); setDocs({});
    setError(""); setNotice("");
  }

  async function loadDocs(baseId: string, token = key) {
    const data = await api(`knowledge-bases/${baseId}/documents`, "GET", undefined, token);
    setDocs((current) => ({ ...current, [baseId]: data.items }));
  }

  async function saveTags(base: KnowledgeBase, doc: Doc) {
    if (!tagging) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api(`documents/${doc.id}/metadata`, "PUT", { metadata: parseTags(tagging.text) });
      setTagging(null);
      setNotice(`Tags saved on ${doc.name}. They apply to questions straight away.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); void loadDocs(base.id).catch(() => undefined); }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice("");
    try {
      const created = await api("knowledge-bases", "POST", { name, description });
      setBases((current) => [created, ...current]); setName(""); setDescription("");
      if (!chatBase) setChatBase(created.id);
      if (!botBase) setBotBase(created.id);
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
      const survivor = bases.find((item) => item.id !== base.id)?.id || "";
      if (chatBase === base.id) setChatBase(survivor);
      if (botBase === base.id) setBotBase(survivor);
      setNotice("Knowledge base deleted.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function upload(base: KnowledgeBase, file: File | undefined) {
    if (!file) return;
    setBusy(true); setError(""); setNotice("");
    const form = new FormData(); form.set("file", file);
    try {
      form.set("metadata", JSON.stringify(parseTags(uploadTags)));
      const response = await fetch(`/api/backend/v1/knowledge-bases/${base.id}/documents`, {
        method: "POST", headers: { Authorization: "Bearer " + key }, body: form,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Upload failed.");
      setNotice(`${data.name} uploaded. Generating its search index…`);
      const processed = await api(`ingestion-jobs/${data.job_id}/process`, "POST");
      setNotice(`${data.name} is ready with ${processed.chunk_count} searchable chunks.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); void loadDocs(base.id).catch(() => undefined); }
  }

  async function reindex(base: KnowledgeBase, doc: Doc) {
    setBusy(true); setError(""); setNotice("");
    try {
      const queued = await api(`documents/${doc.id}/reindex`, "POST");
      setNotice(`${doc.name} is being reindexed. The current version keeps answering until it finishes…`);
      const processed = await api(`ingestion-jobs/${queued.job_id}/process`, "POST");
      setNotice(`${doc.name} reindexed with ${processed.chunk_count} searchable chunks.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); void loadDocs(base.id).catch(() => undefined); }
  }

  async function removeDoc(base: KnowledgeBase, doc: Doc) {
    if (!window.confirm(`Delete "${doc.name}"? Chatbots will stop answering from it immediately.`)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api(`documents/${doc.id}`, "DELETE");
      setNotice(`${doc.name} deleted.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); void loadDocs(base.id).catch(() => undefined); }
  }

  function snippet(bot: Chatbot) {
    return `<script src="${apiOrigin.replace(/\/$/, "")}/widget.js"
        data-key="${bot.public_key}" defer></script>`;
  }

  async function createBot(event: FormEvent) {
    event.preventDefault();
    // One origin per line, so a client's staging and live sites are both easy to add.
    const origins = botOrigins.split(/[\n,]/).map((line) => line.trim()).filter(Boolean);
    if (!origins.length) { setError("Add at least one website address this chatbot may answer on."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const created = await api("chatbots", "POST", {
        knowledge_base_id: botBase, name: botName, greeting: botGreeting, allowed_origins: origins,
      });
      setBots((current) => [created, ...current]);
      setBotName(""); setBotGreeting(""); setBotOrigins("");
      setNotice(`${created.name} is ready. Paste its snippet into the website.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function removeBot(bot: Chatbot) {
    if (!window.confirm(`Delete "${bot.name}"? Its snippet will stop working on every site using it.`)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api("chatbots/" + bot.id, "DELETE");
      setBots((current) => current.filter((item) => item.id !== bot.id));
      setNotice("Chatbot deleted.");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function copySnippet(bot: Chatbot) {
    try {
      await navigator.clipboard.writeText(snippet(bot));
      setCopied(bot.id);
      window.setTimeout(() => setCopied(""), 2000);
    } catch {
      setError("This browser blocked copying. Select the snippet and copy it manually.");
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!chatBase || !question.trim()) return;
    setBusy(true); setError(""); setNotice(""); setAnswer(""); setSources([]);
    try {
      const filters = parseTags(filterText);
      const response = await fetch("/api/backend/v1/chat/stream", {
        method: "POST",
        headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" },
        body: JSON.stringify({ knowledge_base_id: chatBase, question, top_k: 5, filters }),
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
      <a className="brand" href="/"><span className="mark">g</span> ground<span className="brand-light">work</span></a>
      <div className="workspace-label">WORKSPACE</div>
      <div className="workspace"><span className="avatar">{tenant?.name[0]?.toUpperCase() || "W"}</span><div>{tenant?.name || "Your workspace"}<small>{tenant ? "Connected" : "Connect to get started"}</small></div></div>
      <nav aria-label="Workspace navigation"><span className="active">▤ &nbsp; Knowledge bases</span><span>◌ &nbsp; Chat playground</span><span>◇ &nbsp; Website chatbots</span></nav>
      <div className="aside-footer"><span className="dot" /> Local development <p>Your knowledge. Your workspace.</p></div>
    </aside>
    <main>
      <header><span>Workspace / Knowledge bases</span><span className="pill">Foundation release</span></header>
      <section className="heading"><div className="eyebrow">YOUR SOURCE OF TRUTH</div><h1>A home for your knowledge.</h1><p>Create dedicated collections for the information your chatbot will use.</p></section>
      {error && <div className="message error" role="alert">{error}</div>}
      {notice && <div className="message success" role="status">{notice}</div>}
      {!tenant ? <section className="connect panel"><div><span className="section-number">01 / CONNECT</span><h2>Open your workspace</h2><p>{useKey ? "Enter your organization’s API key to manage its knowledge bases." : "Sign in with the email and password your administrator set up for you."}</p><p className="muted">Your {useKey ? "key" : "sign-in"} stays in this browser tab’s memory and is cleared when you {useKey ? "disconnect" : "sign out"} or refresh.</p></div>{useKey ? <form onSubmit={connect}><label htmlFor="key">Workspace API key</label><input id="key" type="password" autoComplete="off" required value={key} onChange={(e) => setKey(e.target.value)} placeholder="rag_…" /><button disabled={busy}>{busy ? "Connecting…" : "Connect workspace →"}</button><button className="link" type="button" onClick={() => { setUseKey(false); setKey(""); setError(""); }}>Sign in with email instead</button></form> : <form onSubmit={signIn}><label htmlFor="email">Email</label><input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" /><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /><button disabled={busy}>{busy ? "Signing in…" : "Sign in →"}</button><button className="link" type="button" onClick={() => { setUseKey(true); setPassword(""); setError(""); }}>Use an API key instead</button></form>}</section> :
      <><div className="section-top"><h2>Knowledge bases <span className="count">{bases.length}</span></h2><button className="secondary" disabled={busy} onClick={() => void disconnect()}>{signedIn ? "Sign out" : "Disconnect"}</button></div>
        <div className="content-grid"><section className="bases">
          {bases.length === 0 ? <div className="empty panel"><div className="empty-icon">▤</div><h3>Your first knowledge base starts here</h3><p>Give it a name, like “Customer support” or “Product documentation”.</p></div> : bases.map((base) => <article className="base panel" key={base.id}><span className="folder">▤</span><h3>{base.name}</h3><p>{base.description || "No description yet."}</p>{(docs[base.id] || []).length > 0 && <ul className="docs">{docs[base.id].map((doc) => <li key={doc.id}><span>{doc.name}{Object.keys(doc.metadata || {}).length > 0 && <small className="tags">{formatTags(doc.metadata)}</small>}{tagging?.id === doc.id && <div className="tag-edit"><input aria-label={"Tags for " + doc.name} value={tagging.text} onChange={(e) => setTagging({ id: doc.id, text: e.target.value })} placeholder="month=jul-2026, published=2026-07-10" /><button type="button" disabled={busy} onClick={() => void saveTags(base, doc)}>Save</button></div>}</span><span className={"status" + (doc.status === "failed" ? " failed" : "")} title={doc.error_message || undefined}>{doc.status}{doc.version > 1 && ` · v${doc.version}`}</span><button className="secondary" type="button" disabled={busy} onClick={() => setTagging(tagging?.id === doc.id ? null : { id: doc.id, text: formatTags(doc.metadata || {}) })} aria-label={"Edit tags on " + doc.name}>Tags</button><button className="secondary" type="button" disabled={busy || doc.status === "queued"} onClick={() => reindex(base, doc)} aria-label={"Reindex " + doc.name}>Reindex</button><button className="delete" type="button" disabled={busy} onClick={() => removeDoc(base, doc)} aria-label={"Delete " + doc.name}>Delete</button></li>)}</ul>}<input className="tags-field" aria-label="Tags for the next upload" value={uploadTags} onChange={(e) => setUploadTags(e.target.value)} placeholder="Tags for the next upload, e.g. month=jul-2026" /><label className="upload">Add a document<input type="file" disabled={busy} accept=".pdf,.docx,.txt,.md,.html,.htm" onChange={(event) => { void upload(base, event.target.files?.[0]); event.target.value = ""; }} /></label><footer><span>Created {new Date(base.created_at).toLocaleDateString()}</span><button className="delete" disabled={busy} onClick={() => remove(base)} aria-label={"Delete " + base.name}>Delete</button></footer></article>)}
        </section><form className="panel create" onSubmit={create}><span className="section-number">NEW COLLECTION</span><h2>Create a knowledge base</h2><label htmlFor="name">Name</label><input id="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="e.g. Customer support" required /><label htmlFor="description">Description <span className="optional">(optional)</span></label><textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} placeholder="What belongs in this collection?" rows={4} /><button disabled={busy || !name.trim()}>{busy ? "Working…" : "Create knowledge base +"}</button></form></div></>}
      {tenant && <section className="playground panel"><div><span className="section-number">RAG PLAYGROUND</span><h2>Ask your knowledge base</h2><p>Answers use only active, indexed documents and include their sources.</p></div><form onSubmit={ask}><label htmlFor="chat-base">Knowledge base</label><select id="chat-base" value={chatBase} onChange={(event) => setChatBase(event.target.value)} disabled={busy || bases.length === 0}>{bases.length === 0 && <option value="">Create a knowledge base first</option>}{bases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}</select><label htmlFor="question">Question</label><textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} maxLength={4000} placeholder="What would you like to know?" required /><label htmlFor="filters">Only search documents tagged <span className="optional">(optional)</span></label><input id="filters" value={filterText} onChange={(e) => setFilterText(e.target.value)} placeholder="month=jul-2026" /><button disabled={busy || !chatBase || !question.trim()}>{busy ? "Working…" : "Ask question →"}</button></form>{answer && <div className="answer"><span>ANSWER</span><p>{answer}</p>{sources.length > 0 && <ol>{sources.map((source) => <li key={source.id}><strong>[{source.id}] {source.document_name}</strong>{source.page_number && ` · page ${source.page_number}`}{source.section && ` · ${source.section}`}<small>{source.excerpt}</small></li>)}</ol>}</div>}</section>}
      {tenant && <section className="bots panel">
        <div className="section-top"><div><span className="section-number">WEBSITE CHATBOTS</span><h2>Answer questions on your website <span className="count">{bots.length}</span></h2></div></div>
        <p className="muted">Each chatbot answers from one knowledge base, and only on the websites you list.</p>
        <div className="content-grid">
          <div className="bases">
            {bots.length === 0 ? <div className="empty panel"><div className="empty-icon">◇</div><h3>No chatbots yet</h3><p>Create one to get a snippet you can paste into a website.</p></div> :
            bots.map((bot) => <article className="base panel" key={bot.id}>
              <h3>{bot.name}</h3>
              <p>{bases.find((base) => base.id === bot.knowledge_base_id)?.name || "Knowledge base removed"}</p>
              <p className="muted">Answers on: {bot.allowed_origins.join(", ")}</p>
              <label htmlFor={"snippet-" + bot.id}>Paste this into the website</label>
              <pre className="snippet" id={"snippet-" + bot.id}>{snippet(bot)}</pre>
              <footer>
                <button className="secondary" type="button" onClick={() => copySnippet(bot)}>{copied === bot.id ? "Copied ✓" : "Copy snippet"}</button>
                <button className="delete" disabled={busy} onClick={() => removeBot(bot)} aria-label={"Delete " + bot.name}>Delete</button>
              </footer>
            </article>)}
          </div>
          <form className="panel create" onSubmit={createBot}>
            <span className="section-number">NEW CHATBOT</span><h2>Create a chatbot</h2>
            <label htmlFor="bot-name">Name</label>
            <input id="bot-name" value={botName} onChange={(e) => setBotName(e.target.value)} maxLength={120} placeholder="e.g. Support assistant" required />
            <label htmlFor="bot-base">Knowledge base</label>
            <select id="bot-base" value={botBase} onChange={(e) => setBotBase(e.target.value)} disabled={bases.length === 0} required>
              {bases.length === 0 && <option value="">Create a knowledge base first</option>}
              {bases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}
            </select>
            <label htmlFor="bot-greeting">Greeting <span className="optional">(optional)</span></label>
            <input id="bot-greeting" value={botGreeting} onChange={(e) => setBotGreeting(e.target.value)} maxLength={500} placeholder="Hi! How can I help?" />
            <label htmlFor="bot-origins">Website addresses</label>
            <textarea id="bot-origins" value={botOrigins} onChange={(e) => setBotOrigins(e.target.value)} rows={3} placeholder={"https://example.com\nhttps://www.example.com"} required />
            <p className="muted">One per line, scheme and domain only. The chatbot refuses to answer anywhere else, so include every address the site is served from.</p>
            <label htmlFor="api-origin">This workspace&rsquo;s API address</label>
            <input id="api-origin" value={apiOrigin} onChange={(e) => setApiOrigin(e.target.value)} placeholder="https://rag.example.com" />
            <p className="muted">Used to build the snippet. It is where visitors&rsquo; browsers load the widget from.</p>
            <button disabled={busy || !botName.trim() || !botBase}>{busy ? "Working…" : "Create chatbot +"}</button>
          </form>
        </div>
      </section>}
      <section className="next-step"><span>UP NEXT</span><p>Durable queue delivery, conversation history, and chatbot branding.</p></section>
    </main>
  </div>;
}
