import { Routes, Route, Navigate, useParams } from "react-router-dom";
import ChatPage from "./features/chat/ChatPage";
import LoginPage from "./features/auth/LoginPage";
import OpsPage from "./features/ops/OpsPage";
import { RequireAuth } from "./components/RequireAuth/RequireAuth";
import { useCurrentUser } from "./hooks/useCurrentUser";

/** Links de /oracle/:id já foram compartilhados; preservam a conversa. */
function LegacyConversationRedirect() {
  const { conversationId } = useParams();
  return <Navigate to={`/c/${conversationId}`} replace />;
}

function PrivateChat() {
  return (
    <RequireAuth>
      <ChatPage />
    </RequireAuth>
  );
}

export default function App() {
  const { isAdmin } = useCurrentUser();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<PrivateChat />} />
      <Route path="/c/:conversationId" element={<PrivateChat />} />
      <Route path="/oracle" element={<Navigate to="/" replace />} />
      <Route path="/oracle/:conversationId" element={<LegacyConversationRedirect />} />
      {/* Sem admin, a rota nem existe (UI); o backend garante com 404. */}
      {isAdmin && (
        <Route
          path="/ops"
          element={
            <RequireAuth>
              <OpsPage />
            </RequireAuth>
          }
        />
      )}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
