import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GoogleAuth } from "../src/core/library/auth";

type Req = { prompt?: string; login_hint?: string } | undefined;

/** A pretend Google Identity Services that hands out numbered tokens and records how it was asked. */
function fakeGis() {
  const asked: Req[] = [];
  let n = 0;
  window.google = {
    accounts: {
      oauth2: {
        initTokenClient: () => {
          const c = {
            callback: (_r: object) => {},
            requestAccessToken(opts?: Req) {
              asked.push(opts);
              c.callback({ access_token: `tok${++n}`, expires_in: 3600 });
            },
          };
          return c;
        },
        revoke: () => {},
      },
    },
  };
  // the script tag "loads" at once, without going to Google
  vi.spyOn(document.head, "appendChild").mockImplementation(<T extends Node>(el: T): T => {
    queueMicrotask(() => (el as unknown as HTMLScriptElement).onload?.(new Event("load")));
    return el;
  });
  return asked;
}

describe("Google sign-in is remembered on this device", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ user: { emailAddress: "me@example.com" } }), { status: 200 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("reuses the token after a reload, then renews it with no prompt and the same account", async () => {
    const asked = fakeGis();
    const first = new GoogleAuth();
    expect(await first.getToken("CID")).toBe("tok1");
    expect(asked[0]).toEqual({}); // the first time Google shows its usual screens
    await new Promise((r) => setTimeout(r, 0)); // the account is looked up after sign-in

    const reloaded = new GoogleAuth(); // a page reload
    expect(reloaded.signedIn).toBe(true);
    expect(await reloaded.getToken("CID")).toBe("tok1"); // no popup at all within the hour
    expect(asked).toHaveLength(1);

    const saved = JSON.parse(localStorage.getItem("lento.library.auth")!);
    localStorage.setItem("lento.library.auth", JSON.stringify({ ...saved, expires: Date.now() - 1 })); // an hour later
    const later = new GoogleAuth();
    expect(later.signedIn).toBe(false);
    expect(later.remembered).toBe(true);
    expect(await later.getToken("CID")).toBe("tok2");
    expect(asked[1]).toEqual({ prompt: "", login_hint: "me@example.com" });
  });

  it("forgets everything on sign out, and asks afresh for a different client ID", async () => {
    const asked = fakeGis();
    const a = new GoogleAuth();
    await a.getToken("CID");
    const b = new GoogleAuth();
    await b.getToken("OTHER");
    expect(asked[1]).toEqual({});
    b.signOut();
    expect(localStorage.getItem("lento.library.auth")).toBeNull();
    expect(new GoogleAuth().remembered).toBe(false);
  });
});
