/**
 * WebAuthn (passkey) browser ceremonies.
 *
 * The server speaks base64url JSON, the browser speaks ArrayBuffers, so every binary
 * field has to be converted in both directions. We do it explicitly rather than relying
 * on PublicKeyCredential.parseCreationOptionsFromJSON(), which is still missing in
 * plenty of shipping browsers.
 */

export const passkeySupported = () =>
  typeof window !== "undefined" &&
  !!window.PublicKeyCredential &&
  !!navigator.credentials?.create;

/**
 * Whether THIS device can actually enrol a passkey with its own screen lock or
 * biometrics. Only used to decide whether offering one is worth an interruption: a
 * desktop with no platform authenticator would just get a dialog it cannot satisfy.
 */
export async function platformPasskeyAvailable() {
  if (!passkeySupported() || !window.isSecureContext) return false;
  const pk = window.PublicKeyCredential;
  try {
    if (typeof pk.getClientCapabilities === "function") {
      const caps = await pk.getClientCapabilities();
      if (typeof caps?.passkeyPlatformAuthenticator === "boolean") {
        return caps.passkeyPlatformAuthenticator;
      }
    }
    if (typeof pk.isUserVerifyingPlatformAuthenticatorAvailable === "function") {
      return await pk.isUserVerifyingPlatformAuthenticatorAvailable();
    }
  } catch (e) {
    return false;
  }
  return false;
}

function b64uToBytes(s) {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

function bytesToB64u(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function toCreationOptions(o) {
  return {
    ...o,
    challenge: b64uToBytes(o.challenge),
    user: { ...o.user, id: b64uToBytes(o.user.id) },
    excludeCredentials: (o.excludeCredentials || []).map((c) => ({
      ...c,
      id: b64uToBytes(c.id),
    })),
  };
}

function toRequestOptions(o) {
  return {
    ...o,
    challenge: b64uToBytes(o.challenge),
    allowCredentials: (o.allowCredentials || []).map((c) => ({
      ...c,
      id: b64uToBytes(c.id),
    })),
  };
}

function credentialToJSON(c) {
  const r = c.response;
  const out = {
    id: c.id,
    rawId: bytesToB64u(c.rawId),
    type: c.type,
    response: { clientDataJSON: bytesToB64u(r.clientDataJSON) },
    clientExtensionResults: c.getClientExtensionResults ? c.getClientExtensionResults() : {},
  };
  if (r.attestationObject) out.response.attestationObject = bytesToB64u(r.attestationObject);
  if (r.authenticatorData) out.response.authenticatorData = bytesToB64u(r.authenticatorData);
  if (r.signature) out.response.signature = bytesToB64u(r.signature);
  if (r.userHandle) out.response.userHandle = bytesToB64u(r.userHandle);
  if (c.authenticatorAttachment) out.authenticatorAttachment = c.authenticatorAttachment;
  return out;
}

export async function createCredential(options) {
  const credential = await navigator.credentials.create({
    publicKey: toCreationOptions(options),
  });
  if (!credential) throw new Error("cancelled");
  return credentialToJSON(credential);
}

export async function getCredential(options) {
  const credential = await navigator.credentials.get({
    publicKey: toRequestOptions(options),
  });
  if (!credential) throw new Error("cancelled");
  return credentialToJSON(credential);
}
