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
  requestAccessToken(opts?: { prompt?: string }): void;
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

export class GoogleAuth {
  private client: TokenClient | null = null;
  private clientId = "";
  private token = "";
  private expires = 0;
  private consented = false;

  get signedIn(): boolean {
    return !!this.token && Date.now() < this.expires;
  }

  /** A valid access token, asking Google for one if needed. Call from a click so the sign-in popup is allowed. */
  async getToken(clientId: string, fresh = false): Promise<string> {
    if (!fresh && this.signedIn && clientId === this.clientId) return this.token;
    await loadGis();
    if (!this.client || clientId !== this.clientId) {
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
        resolve(this.token);
      };
      client.error_callback = (e) => reject(new Error(e.type === "popup_closed" ? "Sign-in was closed." : e.message || `Google sign-in failed (${e.type}).`));
      client.requestAccessToken({ prompt: this.consented ? "" : undefined });
    });
  }

  signOut(): void {
    if (this.token) window.google?.accounts.oauth2.revoke(this.token);
    this.token = "";
    this.expires = 0;
    this.consented = false;
  }
}
