import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./useAuth";
import { clearSession, loadSession, saveSession } from "../lib/auth/session";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
  clearSession(); // module-level memorySession (CRITICAL 2) não é resetado pelo storage.clear()
});

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

describe("useAuth", () => {
  it("restaura sessão existente do storage", async () => {
    saveSession({
      user: { id: "u-1", email: "ana@x.com", name: null, username: null },
      accessToken: "jwt-abc",
      isAdmin: true,
    });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.user?.email).toBe("ana@x.com");
    expect(result.current.isAdmin).toBe(true);
  });

  it("storage bloqueado vira status 'error' (terceiro estado) e retry recupera", async () => {
    const getItemSpy = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.user).toBeNull();

    getItemSpy.mockRestore();
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.user).toBeNull();
  });

  it("login ok grava a sessão e devolve null", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            user: { id: "u-1", email: "ana@x.com", name: "Ana", username: "ana" },
            access_token: "jwt-abc",
            expires_in: 3600,
            is_admin: false,
          }),
          { status: 200 }
        )
      )
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let code: string | null = "pending";
    await act(async () => {
      code = await result.current.login("ana@x.com", "s3nh4");
    });
    expect(code).toBeNull();
    expect(result.current.user?.email).toBe("ana@x.com");
    expect(loadSession()?.accessToken).toBe("jwt-abc");
  });

  it("login inválido devolve o código estável e não grava sessão", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "invalid-credentials" }), { status: 401 })
      )
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let code: string | null = null;
    await act(async () => {
      code = await result.current.login("a@x.com", "errada");
    });
    expect(code).toBe("invalid-credentials");
    expect(result.current.user).toBeNull();
  });

  // MINOR 8: um 200 cujo corpo não bate com o contrato (proxy devolvendo
  // HTML, ou faltando `user`/`access_token`) não pode deixar a exceção do
  // parse escapar do login() — senão o form fica preso em "Entrando…".
  it("200 com corpo fora do contrato vira 'unavailable' em vez de lançar", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({}), { status: 200 }))
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let code: string | null = "pending";
    await act(async () => {
      code = await result.current.login("a@x.com", "s3nh4");
    });
    expect(code).toBe("unavailable");
    expect(result.current.user).toBeNull();
  });

  it("falha de rede vira 'unavailable'", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let code: string | null = null;
    await act(async () => {
      code = await result.current.login("a@x.com", "s");
    });
    expect(code).toBe("unavailable");
  });

  it("logout limpa tudo", async () => {
    saveSession({
      user: { id: "u-1", email: "ana@x.com", name: null, username: null },
      accessToken: "jwt-abc",
      isAdmin: false,
    });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user).not.toBeNull());
    act(() => result.current.logout());
    expect(result.current.user).toBeNull();
    expect(loadSession()).toBeNull();
  });
});
