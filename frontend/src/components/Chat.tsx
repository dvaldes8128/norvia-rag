import { useEffect, useRef, useState, type FormEvent } from "react";
import { askQuestion } from "../api/endpoints";
import type { AskResponse, Citation } from "../types/api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  confidence?: number;
  error?: boolean;
}

interface Props {
  enabled: boolean;
}

function Citations({ items }: { items: Citation[] }) {
  if (items.length === 0) {
    return <p className="citations citations--empty">No citations (insufficient evidence).</p>;
  }
  return (
    <ul className="citations">
      {items.map((c) => (
        <li key={c.chunk_id} className="citation">
          <header>
            <strong>{c.filename}</strong>
            <span>p. {c.page_number}</span>
          </header>
          <blockquote>{c.excerpt}</blockquote>
        </li>
      ))}
    </ul>
  );
}

export function Chat({ enabled }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy || !enabled) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: q,
    };
    setMessages((m) => [...m, userMsg]);
    setQuestion("");
    setBusy(true);

    try {
      const res: AskResponse = await askQuestion(q);
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: res.answer,
          citations: res.citations,
          confidence: res.confidence,
        },
      ]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: err instanceof Error ? err.message : "Request failed",
          error: true,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel chat" aria-labelledby="chat-heading">
      <header className="panel__head">
        <h2 id="chat-heading">Ask</h2>
        <p className="panel__sub">Answers cite retrieved policy chunks only.</p>
      </header>

      <div className="chat__thread" role="log" aria-live="polite">
        {messages.length === 0 ? (
          <p className="empty">
            Ask about uploaded policies once at least one document is{" "}
            <em>completed</em>.
          </p>
        ) : (
          messages.map((msg) => (
            <article
              key={msg.id}
              className={`bubble bubble--${msg.role}${msg.error ? " bubble--error" : ""}`}
            >
              <p className="bubble__text">{msg.text}</p>
              {msg.role === "assistant" && !msg.error ? (
                <>
                  {typeof msg.confidence === "number" ? (
                    <p className="bubble__conf">
                      confidence {(msg.confidence * 100).toFixed(0)}%
                    </p>
                  ) : null}
                  {msg.citations ? <Citations items={msg.citations} /> : null}
                </>
              ) : null}
            </article>
          ))
        )}
        {busy ? <p className="chat__typing">Retrieving…</p> : null}
        <div ref={bottomRef} />
      </div>

      <form className="chat__composer" onSubmit={(e) => void handleSubmit(e)}>
        <label className="sr-only" htmlFor="question">
          Question
        </label>
        <textarea
          id="question"
          rows={2}
          placeholder={enabled ? "Ask a question about your documents…" : "Connect first"}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={!enabled || busy}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!enabled || busy || !question.trim()}
        >
          {busy ? "…" : "Send"}
        </button>
      </form>
    </section>
  );
}
