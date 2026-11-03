/**
 * Norvia RAG frontend shell.
 * Will host: document upload, document list with live status, and a chat
 * view that renders citations next to each answer.
 */
export function App() {
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 820, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Norvia RAG</h1>
      <p>Multi-tenant policy assistant — scaffold.</p>
      {/* TODO: <UploadPanel /> <DocumentList /> <Chat /> */}
    </main>
  );
}
