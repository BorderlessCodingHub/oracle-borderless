/**
 * Identidade do usuário. HOJE: placeholder — não existe endpoint /me, e a
 * página de ops está aberta por decisão da dona do produto.
 *
 * QUANDO A AUTH CHEGAR: buscar de /me e devolver `isAdmin` de verdade. Quem não
 * for admin não deve renderizar nem o link no header nem a <Route> de /ops —
 * a rota simplesmente não existe para essa pessoa (404 do lado do backend).
 */
export interface CurrentUser {
  email: string | null;
  isAdmin: boolean;
}

export function useCurrentUser(): CurrentUser {
  return { email: null, isAdmin: true };
}
