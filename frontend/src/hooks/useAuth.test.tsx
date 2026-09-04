import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth, type LoginError } from "./useAuth";
import { loggedIn, stubAuthFetch, TEST_USER } from "../test/authFetch";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

const json = (body: unknown, status: number) =>
  new Response(JSON.stringify(body), { status });

describe("useAuth — restore via /auth/me", () => {
  it("200 popula user e isAdmin", async () => {
    const fetchMock = stubAuthFetch(loggedIn(true));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.user).toEqual(TEST_USER);
    expect(result.current.isAdmin).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/auth\/me$/));
  });

  it("401 = deslogado (ready, sem user)", async () => {
    stubAuthFetch(401);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.user).toBeNull();
    expect(result.current.isAdmin).toBe(false);
  });

  it("falha de rede vira status 'error' (terceiro estado) e retry recupera", async () => {
    const fetchMock = stubAuthFetch("network");
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.user).toBeNull();

    fetchMock.setMe(loggedIn());
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.user?.email).toBe("ana@x.com");
  });

  it("5xx no /auth/me também é 'error', não deslogado", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "unavailable" }, 503)));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.user).toBeNull();
  });
});

describe("useAuth — login", () => {
  it("ok: popula user/isAdmin e devolve null (sem token no corpo)", async () => {
    stubAuthFetch(401, () => json({ user: TEST_USER, is_admin: false }, 200));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = { code: "unavailable" };
    await act(async () => {
      err = await result.current.login("ana@x.com", "s3nh4");
    });
    expect(err).toBeNull();
    expect(result.current.user).toEqual(TEST_USER);
    expect(result.current.isAdmin).toBe(false);
  });

  it("inválido devolve o código estável e não popula", async () => {
    stubAuthFetch(401, () => json({ detail: "invalid-credentials" }, 401));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = null;
    await act(async () => {
      err = await result.current.login("a@x.com", "errada");
    });
    expect(err).toEqual({ code: "invalid-credentials" });
    expect(result.current.user).toBeNull();
  });

  it("forbidden carrega a message da plataforma", async () => {
    stubAuthFetch(401, () =>
      json({ detail: "forbidden", message: "Sua conta está desativada." }, 403)
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = null;
    await act(async () => {
      err = await result.current.login("a@x.com", "s");
    });
    expect(err).toEqual({ code: "forbidden", message: "Sua conta está desativada." });
  });

  it("200 com corpo fora do contrato vira 'unavailable' em vez de lançar", async () => {
    stubAuthFetch(401, () => json({}, 200));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = null;
    await act(async () => {
      err = await result.current.login("a@x.com", "s3nh4");
    });
    expect(err).toEqual({ code: "unavailable" });
    expect(result.current.user).toBeNull();
  });

  it("falha de rede vira 'unavailable'", async () => {
    stubAuthFetch(401, () => {
      throw new Error("down");
    });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = null;
    await act(async () => {
      err = await result.current.login("a@x.com", "s");
    });
    expect(err).toEqual({ code: "unavailable" });
  });
});

describe("useAuth — logout", () => {
  it("zera o estado e chama POST /auth/logout", async () => {
    const fetchMock = stubAuthFetch(loggedIn());
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user).not.toBeNull());
    await act(async () => {
      await result.current.logout();
    });
    expect(result.current.user).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/auth\/logout$/),
      expect.objectContaining({ method: "POST" })
    );
  });
});
