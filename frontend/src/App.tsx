import { Routes, Route, Navigate, useParams } from "react-router-dom";
import ChatPage from "./features/chat/ChatPage";
import OpsPage from "./features/ops/OpsPage";
import { useCurrentUser } from "./hooks/useCurrentUser";

/** Links de /oracle/:id já foram compartilhados; preservam a conversa. */
function LegacyConversationRedirect() {
  const { conversationId } = useParams();
  return <Navigate to={`/c/${conversationId}`} replace />;
}

export default function App() {
  const { isAdmin } = useCurrentUser();
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/c/:conversationId" element={<ChatPage />} />
      <Route path="/oracle" element={<Navigate to="/" replace />} />
      <Route path="/oracle/:conversationId" element={<LegacyConversationRedirect />} />
      {/* Sem admin, a rota nem existe — ver useCurrentUser. */}
      {isAdmin && <Route path="/ops" element={<OpsPage />} />}
      {/* URL desconhecida (favorito de /about, /knowledge; erro de digitação;
          ou /ops sem isAdmin) — sem isto, <Routes> renderiza null: tela branca. */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
