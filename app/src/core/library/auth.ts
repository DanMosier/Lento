/**
 * Google sign-in with Google Identity Services (token model), no server needed.
 * Scopes: read the library, and create only the app's own small request files (drive.file cannot touch anything else).
 */

const SCOPE = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file";

interface TokenResponse {
  access_token?: string;
  expires_in?: number;
  error?: string;
  error_description?: string;
}
interface TokenClient {
  callback: (r: TokenResponse) => void;
  error_callback?: (e: { type: string; message?: string }) => void;
  requestAccessToken(opts?: { prompt?: string; login_hint?: string }): void;
}
declare global {
  interface Window {
    google?: { accounts: { oauth2: { initTokenClient(cfg: object): TokenClient; revoke(token: string, done?: () => void): void } } };
  }
}

let gis: Promise<void> | null = null;

function loadGis(): Promise<void> {
  gis ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      gis = null;
      reject(new Error("Could not reach Google to sign in. Are you offline?"));
    };
    document.head.appendChild(s);
  });
  return gis;
}

/**
 * Kept on this device between visits, so a reload doesn't mean signing in again:
 * - the access token until it expires (Google makes them last an hour), so reloads within the hour need nothing;
 * - that the user has said yes once, and which Google account, so after the hour Google is asked with no prompt and
 *   that account as the hint: its window opens and closes by itself, with nothing to choose.
 * The token only reaches Google Drive for the scopes above. Sign out clears all of it.
 */
const SAVED = "lento.library.auth";

interface Saved {
  clientId: string;
  token?: string;
  expires?: number;
  hint?: string;
}

function load(): Saved | null {
  try {
    return JSON.parse(localStorage.getItem(SAVED) ?? "null") as Saved | null;
  } catch {
    return null;
  }
}

function save(s: Saved | null): void {
  try {
    if (s) localStorage.setItem(SAVED, JSON.stringify(s));
    else localStorage.removeItem(SAVED);
  } catch {
    /* storage blocked: sign-in still works, just not remembered */
  }
}

export class GoogleAuth {
  private client: TokenClient | null = null;
  private clientId = "";
  private token = "";
  private expires = 0;
  private consented = false;
  private hint = "";

  constructor() {
    const s = load();
    if (!s?.clientId) return;
    this.clientId = s.clientId;
    this.consented = true; // saved only after a yes
    this.hint = s.hint ?? "";
    if (s.token && (s.expires ?? 0) > Date.now()) {
      this.token = s.token;
      this.expires = s.expires!;
    }
  }

  get signedIn(): boolean {
    return !!this.token && Date.now() < this.expires;
  }

  /** Has this device signed in before (so asking again shows no choices)? */
  get remembered(): boolean {
    return this.consented;
  }

  /** A valid access token, asking Google for one if needed. Call from a click so the sign-in popup is allowed. */
  async getToken(clientId: string, fresh = false): Promise<string> {
    if (!clientId) throw new Error("Add your Google client ID in Settings first.");
    if (!fresh && this.signedIn && clientId === this.clientId) return this.token;
    await loadGis();
    if (!this.client || clientId !== this.clientId) {
      if (clientId !== this.clientId) {
        this.consented = false; // a different app ID: Google asks again
        this.hint = "";
      }
      this.clientId = clientId;
      this.client = window.google!.accounts.oauth2.initTokenClient({ client_id: clientId, scope: SCOPE, callback: () => {} });
    }
    const client = this.client;
    return new Promise<string>((resolve, reject) => {
      client.callback = (r) => {
        if (r.error || !r.access_token) return reject(new Error(r.error_description || r.error || "Google sign-in failed."));
        this.token = r.access_token;
        this.expires = Date.now() + ((r.expires_in ?? 3600) - 60) * 1000;
        this.consented = true;
        this.remember();
        if (!this.hint) void this.learnAccount();
        resolve(this.token);
      };
      client.error_callback = (e) => reject(new Error(e.type === "popup_closed" ? "Sign-in was closed." : e.message || `Google sign-in failed (${e.type}).`));
      // after the first yes: no consent screen, and the same account, so Google's window closes by itself
      client.requestAccessToken(this.consented ? { prompt: "", ...(this.hint ? { login_hint: this.hint } : {}) } : {});
    });
  }

  private remember(): void {
    save({ clientId: this.clientId, token: this.token, expires: this.expires, hint: this.hint || undefined });
  }

  /** Which Google account signed in, so the next sign-in can skip the account chooser. */
  private async learnAccount(): Promise<void> {
    try {
      const r = await fetch("https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)", { headers: { Authorization: `Bearer ${this.token}` } });
      const email = r.ok ? ((await r.json()) as { user?: { emailAddress?: string } }).user?.emailAddress : undefined;
      if (email) {
        this.hint = email;
        this.remember();
      }
    } catch {
      /* only a convenience */
    }
  }

  signOut(): void {
    if (this.token) window.google?.accounts.oauth2.revoke(this.token);
    this.token = "";
    this.expires = 0;
    this.consented = false;
    this.hint = "";
    save(null);
  }
}
