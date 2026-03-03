import { useEffect, useMemo, useRef, useState } from "react";

function csvToList(value) {
  return (value || "")
    .split(",")
    .map((v) => v.trim())
    .filter((v) => v.length > 0);
}

function parseOptionalObject(raw) {
  if (!raw || !raw.trim()) return {};
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("추가 메타데이터는 JSON 객체여야 합니다.");
  }
  return parsed;
}

function buildMetadata(departmentsRaw, rolesRaw, extraRaw) {
  const departments = csvToList(departmentsRaw);
  const roles = csvToList(rolesRaw);
  const extra = parseOptionalObject(extraRaw);
  const metadata = { ...extra };

  if (departments.length) metadata.allowed_departments = departments;
  if (roles.length) metadata.allowed_roles = roles;

  return metadata;
}

async function callApi(url, options) {
  const res = await fetch(url, options);
  const body = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }

  return body;
}

function formatOutput(data) {
  return typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

function nextMessageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const ASSISTANT_WELCOME_TEXT = "질문을 입력해 주세요. 업로드된 문서를 기반으로 답변하고 출처를 함께 보여드립니다.";

function buildChatHistory(messages) {
  return messages
    .filter((msg) => !msg.typing && (msg.role === "user" || msg.role === "assistant"))
    .filter((msg) => (msg.text || "").trim().length > 0)
    .filter((msg) => !(msg.role === "assistant" && msg.text === ASSISTANT_WELCOME_TEXT))
    .slice(-8)
    .map((msg) => ({ role: msg.role, text: String(msg.text).trim().slice(0, 1200) }));
}

function ChatMessage({ msg }) {
  return (
    <div className={`msg-row ${msg.role}`}>
      <div className={`bubble ${msg.role === "user" ? "user-bubble" : "assistant-bubble"}`}>
        {msg.typing ? (
          <div className="typing">
            <span></span>
            <span></span>
            <span></span>
          </div>
        ) : (
          <>
            {msg.text}
            {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
              <details className="msg-sources">
                <summary>출처 ({msg.sources.length})</summary>
                <ul>
                  {msg.sources.map((s, idx) => (
                    <li key={`${s.document_id}-${s.chunk_index}-${idx}`}>
                      <strong>{s.title}</strong> ({s.source_name}) #{s.chunk_index} score={s.score}
                      <br />
                      {s.excerpt}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [healthState, setHealthState] = useState({ dot: "", text: "상태 확인 중..." });
  const [isAdminOpen, setIsAdminOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      id: nextMessageId(),
      role: "assistant",
      text: ASSISTANT_WELCOME_TEXT,
      sources: [],
      typing: false,
    },
  ]);
  const [isSending, setIsSending] = useState(false);

  const [question, setQuestion] = useState("");
  const chatSettings = useMemo(
    () => ({
      user_id: "u-1001",
      user_department: "",
      user_roles: "",
    }),
    []
  );

  const [textForm, setTextForm] = useState({
    title: "",
    source_name: "수동입력",
    departments: "",
    roles: "",
    extra_metadata: "",
    content: "",
  });
  const [textResult, setTextResult] = useState("");

  const [fileForm, setFileForm] = useState({
    title: "",
    source_name: "파일업로드",
    departments: "",
    roles: "",
    extra_metadata: "",
  });
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileResult, setFileResult] = useState("");
  const [bulkResult, setBulkResult] = useState("");
  const [isBulkRunning, setIsBulkRunning] = useState(false);

  const [documents, setDocuments] = useState([]);
  const [documentsError, setDocumentsError] = useState("");

  const threadRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    refreshHealth();
    loadDocuments();
  }, []);

  useEffect(() => {
    if (!threadRef.current) return;
    threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [messages]);

  useEffect(() => {
    if (!isAdminOpen) return;

    const handleKeyDown = (event) => {
      if (event.key === "Escape") setIsAdminOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isAdminOpen]);

  async function refreshHealth() {
    setHealthState({ dot: "", text: "상태 확인 중..." });
    try {
      const data = await callApi("/health", { method: "GET" });
      setHealthState({ dot: "ok", text: `API 정상 (db=${data.db}, llm=${data.llm})` });
    } catch (err) {
      setHealthState({ dot: "bad", text: `API 오류: ${err.message}` });
    }
  }

  async function loadDocuments() {
    setDocumentsError("");
    try {
      const rows = await callApi("/documents?limit=50", { method: "GET" });
      setDocuments(rows);
    } catch (err) {
      setDocuments([]);
      setDocumentsError(`오류: ${err.message}`);
    }
  }

  async function handleSendChat(event) {
    event.preventDefault();
    if (isSending) return;

    const trimmed = question.trim();
    if (!trimmed) return;

    const userMsg = { id: nextMessageId(), role: "user", text: trimmed, sources: [], typing: false };
    const typingId = nextMessageId();
    const typingMsg = { id: typingId, role: "assistant", text: "", sources: [], typing: true };

    setMessages((prev) => [...prev, userMsg, typingMsg]);
    setQuestion("");
    setIsSending(true);

    try {
      const history = buildChatHistory(messages);
      const payload = {
        question: trimmed,
        user_id: chatSettings.user_id.trim(),
        user_department: chatSettings.user_department.trim() || null,
        user_roles: csvToList(chatSettings.user_roles),
        history,
      };

      const result = await callApi("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === typingId
            ? { ...msg, typing: false, text: result.answer || "(빈 응답)", sources: result.sources || [] }
            : msg
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((msg) => (msg.id === typingId ? { ...msg, typing: false, text: `오류: ${err.message}` } : msg))
      );
    } finally {
      setIsSending(false);
    }
  }

  async function handleTextIngest(event) {
    event.preventDefault();
    setTextResult("업로드 중...");

    try {
      const metadata = buildMetadata(textForm.departments, textForm.roles, textForm.extra_metadata);
      const payload = {
        title: textForm.title.trim(),
        source_name: textForm.source_name.trim() || "수동입력",
        content: textForm.content,
        metadata,
      };

      const result = await callApi("/documents/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      setTextResult(formatOutput(result));
      await loadDocuments();
    } catch (err) {
      setTextResult(`오류: ${err.message}`);
    }
  }

  async function handleFileIngest(event) {
    event.preventDefault();
    setFileResult("업로드 중...");

    try {
      if (!selectedFile) throw new Error("파일을 선택해 주세요.");

      const metadata = buildMetadata(fileForm.departments, fileForm.roles, fileForm.extra_metadata);
      const data = new FormData();
      data.append("title", fileForm.title.trim());
      data.append("source_name", fileForm.source_name.trim() || "파일업로드");
      data.append("metadata_json", JSON.stringify(metadata));
      data.append("file", selectedFile);

      const result = await callApi("/documents/file", { method: "POST", body: data });
      setFileResult(formatOutput(result));
      await loadDocuments();

      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setFileResult(`오류: ${err.message}`);
    }
  }

  async function handleBulkIngest() {
    if (isBulkRunning) return;
    setIsBulkRunning(true);
    setBulkResult("일괄처리 중...");
    try {
      const result = await callApi("/documents/bulk", { method: "POST" });
      setBulkResult(formatOutput(result));
      await loadDocuments();
    } catch (err) {
      setBulkResult(`오류: ${err.message}`);
    } finally {
      setIsBulkRunning(false);
    }
  }

  const documentsTable = useMemo(() => {
    if (documentsError) return <p>{documentsError}</p>;
    if (!documents.length) return <p>등록된 문서가 없습니다.</p>;

    return (
      <table>
        <thead>
          <tr>
            <th>제목</th>
            <th>출처</th>
            <th>유형</th>
            <th>청크 수</th>
            <th>생성일</th>
            <th>메타데이터</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((row) => (
            <tr key={row.document_id}>
              <td>{row.title}</td>
              <td>{row.source_name}</td>
              <td>{row.source_type}</td>
              <td>{row.chunk_count}</td>
              <td>{new Date(row.created_at).toLocaleString()}</td>
              <td>
                <code>{JSON.stringify(row.metadata)}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }, [documents, documentsError]);

  return (
    <>
      <div className="bg-grid"></div>
      <button
        type="button"
        className={`drawer-backdrop ${isAdminOpen ? "show" : ""}`}
        onClick={() => setIsAdminOpen(false)}
        aria-label="관리 메뉴 닫기"
      />

      <aside className={`admin-drawer ${isAdminOpen ? "open" : ""}`} aria-hidden={!isAdminOpen}>
        <div className="admin-header">
          <h2>관리 메뉴</h2>
          <button type="button" className="drawer-close" onClick={() => setIsAdminOpen(false)}>
            닫기
          </button>
        </div>

        <details className="menu-item" open>
          <summary>시스템 상태</summary>
          <div className="menu-body">
            <button type="button" onClick={refreshHealth}>
              상태 새로고침
            </button>
          </div>
        </details>

        <details className="menu-item">
          <summary>텍스트 문서 업로드</summary>
          <div className="menu-body">
            <form onSubmit={handleTextIngest}>
              <label>
                제목
                <input
                  value={textForm.title}
                  onChange={(e) => setTextForm((prev) => ({ ...prev, title: e.target.value }))}
                  required
                  maxLength={255}
                />
              </label>
              <label>
                출처 이름
                <input
                  value={textForm.source_name}
                  onChange={(e) => setTextForm((prev) => ({ ...prev, source_name: e.target.value }))}
                  maxLength={255}
                />
              </label>
              <label>
                추가 메타데이터 JSON
                <textarea
                  rows="3"
                  value={textForm.extra_metadata}
                  onChange={(e) => setTextForm((prev) => ({ ...prev, extra_metadata: e.target.value }))}
                  placeholder='{"policy_version":"2026.1"}'
                ></textarea>
              </label>
              <label>
                내용
                <textarea
                  rows="7"
                  value={textForm.content}
                  onChange={(e) => setTextForm((prev) => ({ ...prev, content: e.target.value }))}
                  required
                ></textarea>
              </label>
              <button type="submit">텍스트 업로드</button>
            </form>
            <pre className="output">{textResult}</pre>
          </div>
        </details>

        <details className="menu-item">
          <summary>파일 업로드</summary>
          <div className="menu-body">
            <form onSubmit={handleFileIngest}>
              <label>
                제목
                <input
                  value={fileForm.title}
                  onChange={(e) => setFileForm((prev) => ({ ...prev, title: e.target.value }))}
                  required
                  maxLength={255}
                />
              </label>
              <label>
                출처 이름
                <input
                  value={fileForm.source_name}
                  onChange={(e) => setFileForm((prev) => ({ ...prev, source_name: e.target.value }))}
                  maxLength={255}
                />
              </label>
              <label>
                추가 메타데이터 JSON
                <textarea
                  rows="3"
                  value={fileForm.extra_metadata}
                  onChange={(e) => setFileForm((prev) => ({ ...prev, extra_metadata: e.target.value }))}
                  placeholder='{"owner":"ops-team"}'
                ></textarea>
              </label>
              <label>
                파일 (.txt/.md/.pdf/.pptx/.png/.jpg/.jpeg/.bmp/.tiff)
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".txt,.md,.pdf,.pptx,.png,.jpg,.jpeg,.bmp,.tif,.tiff"
                  onChange={(e) => setSelectedFile(e.target.files && e.target.files.length ? e.target.files[0] : null)}
                  required
                />
              </label>
              <button type="submit">파일 업로드</button>
            </form>
            <pre className="output">{fileResult}</pre>
          </div>
        </details>

        <details className="menu-item">
          <summary>최근 문서</summary>
          <div className="menu-body">
            <button type="button" onClick={loadDocuments}>
              목록 새로고침
            </button>
            <div className="table-wrap">{documentsTable}</div>
          </div>
        </details>

        <details className="menu-item">
          <summary>일괄처리</summary>
          <div className="menu-body">
            <p>지정 디렉토리와 ZIP 내부 지원 파일을 한 번에 인덱싱합니다.</p>
            <button type="button" onClick={handleBulkIngest} disabled={isBulkRunning}>
              {isBulkRunning ? "처리 중..." : "일괄처리"}
            </button>
            <pre className="output">{bulkResult}</pre>
          </div>
        </details>
      </aside>

      <main className="container">
        <header className="hero">
          <div className="hero-right">
            <button type="button" className="admin-toggle" onClick={() => setIsAdminOpen(true)}>
              관리 메뉴
            </button>
            <div className="health health-compact">
              <span className={`dot ${healthState.dot}`}></span>
              <strong>{healthState.text}</strong>
            </div>
          </div>
        </header>

        <section className="chat-shell">
          <article className="chat-card">
            <div ref={threadRef} className="chat-thread" aria-live="polite">
              {messages.map((msg) => (
                <ChatMessage key={msg.id} msg={msg} />
              ))}
            </div>

            <form className="chat-composer" onSubmit={handleSendChat}>
              <label className="composer-label">
                <textarea
                  rows="2"
                  required
                  placeholder="메시지를 입력하세요..."
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      e.currentTarget.form?.requestSubmit();
                    }
                  }}
                ></textarea>
              </label>

              <button type="submit" className="send-btn" disabled={isSending}>
                {isSending ? "전송 중..." : "보내기"}
              </button>
            </form>
          </article>
        </section>
      </main>
    </>
  );
}
