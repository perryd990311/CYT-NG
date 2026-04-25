# Synology DSM OAuth2 SSO

CYT-NG supports single sign-on through your Synology NAS using DSM's built-in OAuth2 provider. This lets you log in with your NAS account instead of a separate CYT-NG password.

> SSO is **optional**. CYT-NG always has local username/password login via bcrypt as a fallback.

## Prerequisites

- Synology DSM 7.0+ with **Web Station** or direct Docker port access
- HTTPS enabled on DSM (required for OAuth2)
- A DSM user account

## Step 1: Register an OAuth2 Application in DSM

1. Log into DSM as an administrator
2. Open **Control Panel → Sign-in Service → OAuth Service**
   - If you don't see this, go to **Control Panel → Application Portal → OAuth**
3. Click **Add** to register a new application
4. Fill in the details:

| Field | Value |
|-------|-------|
| **Application Name** | `CYT-NG` |
| **Redirect URI** | `https://your-cyt-ng-url/auth/sso/callback` |

5. After saving, DSM will generate a **Client ID** and **Client Secret**

> The redirect URI must exactly match your CYT-NG deployment URL, including the scheme (`https://`) and path (`/auth/sso/callback`).

## Step 2: Configure CYT-NG

Add the OAuth2 credentials to your `.env` file:

```env
SYNOLOGY_DSM_URL=https://your-nas-ip:5001
SYNOLOGY_OAUTH_CLIENT_ID=your-client-id-from-dsm
SYNOLOGY_OAUTH_CLIENT_SECRET=your-client-secret-from-dsm
```

Restart the container:

```bash
docker compose restart cyt-web
```

## Step 3: Test It

1. Open CYT-NG in your browser
2. The login page now shows a **"Sign in with Synology"** button
3. Click it — you'll be redirected to DSM to authorize the app
4. After authorization, DSM redirects you back to CYT-NG, now logged in
5. Your DSM username is automatically registered as a CYT-NG user

## How It Works

```
Browser → CYT-NG /auth/sso/login
    → Redirect to DSM /webman/sso/SSOOauth.cgi (authorization endpoint)
    → User authorizes in DSM
    → Redirect back to CYT-NG /auth/sso/callback with auth code
    → CYT-NG exchanges code for access token (server-to-server)
    → CYT-NG fetches user info from DSM
    → User is created/matched in CYT-NG database
    → Session established via Flask-Login
```

CYT-NG uses the `authlib` library for the OAuth2 flow. The implementation lives in `web/auth/synology_oauth.py`.

## User Matching

When an SSO user logs in:

- If a CYT-NG user with the same username exists, it's linked to their SSO identity
- If no matching user exists, a new account is created automatically
- SSO users are marked with `auth_provider = "synology_sso"` in the database
- SSO users can still set a local password as a backup

## Disabling SSO

To disable SSO, remove or blank out the Synology environment variables:

```env
SYNOLOGY_DSM_URL=
SYNOLOGY_OAUTH_CLIENT_ID=
SYNOLOGY_OAUTH_CLIENT_SECRET=
```

Restart the container. The login page will only show the local login form.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Sign in with Synology" button missing | Check that all 3 env vars are set and non-empty |
| Redirect loop after authorization | Verify the redirect URI in DSM matches exactly |
| "OAuth error: invalid_client" | Double-check the Client ID and Secret in `.env` |
| SSL certificate error during token exchange | If using self-signed certs on DSM, the `cyt-web` container needs to trust them |
| User created but wrong permissions | SSO users get the same access as local users — no separate role system currently |
