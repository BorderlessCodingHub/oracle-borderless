import { Routes, Route } from "react-router-dom";
import LandingPage from "./features/landing/LandingPage";
import AboutPage from "./features/about/AboutPage";
import KnowledgePage from "./features/knowledge/KnowledgePage";
import ChatPage from "./features/chat/ChatPage";
import OpsPage from "./features/ops/OpsPage";
import { useCurrentUser } from "./hooks/useCurrentUser";

export default function App() {
  const { isAdmin } = useCurrentUser();
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/about" element={<AboutPage />} />
      <Route path="/knowledge" element={<KnowledgePage />} />
      <Route path="/oracle" element={<ChatPage />} />
      <Route path="/oracle/:conversationId" element={<ChatPage />} />
      {/* Sem admin, a rota nem existe — ver useCurrentUser. */}
      {isAdmin && <Route path="/ops" element={<OpsPage />} />}
    </Routes>
  );
}
