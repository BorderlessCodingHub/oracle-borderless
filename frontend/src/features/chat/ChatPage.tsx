import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useConversations } from "../../hooks/useConversations";
import { useConversation } from "../../hooks/useConversation";
import { useAskStream } from "../../hooks/useAskStream";
import { Sidebar } from "./components/Sidebar";
import { MessageList, type Turn } from "./components/MessageList";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { ThinkingIndicator } from "./components/ThinkingIndicator";
import { ErrorState } from "./components/ErrorState";
import { Logo } from "../../components/Logo/Logo";
import styles from "./ChatPage.module.css";

let turnIdSeq = 0;
function nextTurnId(): string {
  turnIdSeq += 1;
  return `turn-${turnIdSeq}`;
}

export default function ChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { conversations, refresh } = useConversations();
  const { detail, loading: detailLoading } = useConversation(conversationId);
  const stream = useAskStream();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [lastQuestion, setLastQuestion] = useState<string>("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // "Run token" identifies which turn-set the currently in-flight stream belongs
  // to. It's bumped on every send/retry/newConversation and on a genuine route
  // change, so events from a superseded stream run can be told apart from the
  // active one by the reflect effect below (fixes stale-stream clobbering).
  const runTokenRef = useRef(0);
  const streamRunTokenRef = useRef<number | null>(null);
  // The conversation id we just created (via a finished stream) and are already
  // displaying in-memory. Used so navigating to it doesn't get treated as a
  // "different conversation" and doesn't get its turns wiped by history-loading.
  const liveConversationIdRef = useRef<string | null>(null);
  const prevConversationIdRef = useRef<string | undefined>(conversationId);

  // Genuine navigation to a different conversation (sidebar click, "Nova
  // conversa", or a stale run's target changing): reset the stream and clear
  // turns so stale content/streams from the previous conversation don't leak.
  // Self-navigation performed after adopting a freshly created conversation id
  // (liveConversationIdRef matches) is NOT a "different conversation" and must
  // not reset anything, otherwise the answer we just produced would vanish.
  useEffect(() => {
    const previous = prevConversationIdRef.current;
    prevConversationIdRef.current = conversationId;
    if (previous === conversationId) return;
    if (conversationId && conversationId === liveConversationIdRef.current) return;
    runTokenRef.current += 1;
    streamRunTokenRef.current = null;
    liveConversationIdRef.current = null;
    stream.reset();
    setTurns([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  // Load history when opening an existing conversation (skip re-fetching for
  // the conversation we just created and are already displaying live).
  useEffect(() => {
    if (conversationId && conversationId === liveConversationIdRef.current) return;
    if (detail && detail.id === conversationId) {
      setTurns(detail.messages.map((m) => ({ id: nextTurnId(), role: m.role, content: m.content, citations: m.sources })));
    } else if (!conversationId) {
      setTurns([]);
    }
  }, [detail, conversationId]);

  // Reflect the streaming answer into the trailing assistant turn — but only
  // for the run that actually produced it; a superseded run is ignored.
  useEffect(() => {
    if (stream.status === "idle") return;
    if (streamRunTokenRef.current === null || streamRunTokenRef.current !== runTokenRef.current) return;
    setTurns((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === "assistant") {
        next[next.length - 1] = { ...last, content: stream.answer, citations: stream.citations.length ? stream.citations : last.citations };
      }
      return next;
    });
  }, [stream.answer, stream.citations, stream.status]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, stream.status]);

  useEffect(() => {
    if (stream.status === "done") void refresh();
  }, [stream.status, refresh]);

  // Once a stream run finishes and it created a new conversation, adopt its id
  // into the route so a follow-up question continues the same conversation
  // instead of spawning a duplicate. Mark it "live" first so the history-load
  // effect above skips fetching/replacing the turns we already have in memory.
  useEffect(() => {
    if (stream.status !== "done") return;
    if (streamRunTokenRef.current !== runTokenRef.current) return;
    if (stream.conversationId && stream.conversationId !== conversationId) {
      liveConversationIdRef.current = stream.conversationId;
      navigate(`/c/${stream.conversationId}`, { replace: true });
    }
  }, [stream.status, stream.conversationId, conversationId, navigate]);

  async function send(question: string) {
    setLastQuestion(question);
    runTokenRef.current += 1;
    streamRunTokenRef.current = runTokenRef.current;
    setTurns((prev) => [...prev, { id: nextTurnId(), role: "user", content: question }, { id: nextTurnId(), role: "assistant", content: "" }]);
    await stream.ask({ question, conversationId });
  }

  // Retry re-runs the SAME trailing turn pair instead of appending a new one:
  // it resets the existing assistant turn's content/citations, then re-asks.
  async function retry() {
    streamRunTokenRef.current = runTokenRef.current;
    setTurns((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === "assistant") {
        next[next.length - 1] = { ...last, content: "", citations: undefined };
      }
      return next;
    });
    await stream.ask({ question: lastQuestion, conversationId });
  }

  function newConversation() {
    runTokenRef.current += 1;
    streamRunTokenRef.current = null;
    liveConversationIdRef.current = null;
    setTurns([]);
    stream.reset();
    navigate("/");
  }

  const showThinking = stream.status === "thinking";
  const showError = stream.status === "error";
  const streamingIndex = stream.status === "streaming" ? turns.length - 1 : null;
  // While "thinking", hide the trailing empty assistant bubble entirely so the
  // ThinkingIndicator (which already renders its own Logo) is the only thing
  // shown — otherwise both render a Logo and it reads as a double-logo flash.
  const visibleTurns = showThinking ? turns.slice(0, -1) : turns;
  const isLoadingExistingConversation = turns.length === 0 && stream.status === "idle" && !!conversationId && detailLoading;

  return (
    <div className={styles.shell}>
      <Sidebar
        conversations={conversations}
        activeId={conversationId ?? null}
        onNew={newConversation}
        onOpen={(id) => navigate(`/c/${id}`)}
      />
      <div className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <strong>{turns.length ? "Conversa" : "Nova conversa"}</strong>
            <span className={styles.topSub}>● Respondendo só com fontes aprovadas do Notion</span>
          </div>
          {/* Identidade volta aqui quando /me existir (fase de autenticação). */}
        </header>
        <div className={styles.thread} ref={scrollRef}>
          {turns.length === 0 && stream.status === "idle" ? (
            isLoadingExistingConversation ? (
              <div className={styles.empty} aria-busy="true">
                <Logo size={72} />
                <p>Carregando conversa…</p>
              </div>
            ) : (
              <EmptyState onPick={send} />
            )
          ) : (
            <div className={styles.threadInner}>
              <MessageList turns={visibleTurns} streamingIndex={streamingIndex} />
              {showThinking && <ThinkingIndicator />}
              {showError && <ErrorState message={stream.errorMessage ?? "Erro ao gerar a resposta."} onRetry={retry} />}
            </div>
          )}
        </div>
        <div className={styles.composerWrap}>
          <Composer onSend={send} disabled={stream.status === "thinking" || stream.status === "streaming"} />
          <p className={styles.composerNote}>O oráculo responde só com fontes aprovadas · nada confidencial</p>
        </div>
      </div>
    </div>
  );
}
