import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import { Auth0Provider, useAuth0 } from "@auth0/auth0-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { router } from "@/router";
import { setTokenGetter } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import "./index.css";

const queryClient = new QueryClient();

const audience = import.meta.env.VITE_AUTH0_AUDIENCE;

function Gate() {
  const { isLoading, isAuthenticated, error, loginWithRedirect, getAccessTokenSilently } =
    useAuth0();

  useEffect(() => {
    setTokenGetter(() => getAccessTokenSilently({ authorizationParams: { audience } }));
  }, [getAccessTokenSilently]);

  if (isLoading) return <p className="p-6 text-ink-muted">Loading…</p>;
  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4">
        {/* A login the Auth0 Action denied — an unapproved access request, say — comes back
            here with the deny message in `error`. Without it a requester cannot tell
            "pending approval" from "login broken". */}
        {error && <p className="max-w-sm text-center text-sm text-ink-muted">{error.message}</p>}
        <Button onClick={() => loginWithRedirect()}>Sign in</Button>
      </div>
    );
  }
  return <RouterProvider router={router} />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Auth0Provider
      domain={import.meta.env.VITE_AUTH0_DOMAIN}
      clientId={import.meta.env.VITE_AUTH0_CLIENT_ID}
      authorizationParams={{ redirect_uri: window.location.origin, audience }}
      // The SDK caches in memory by default and re-authenticates on reload through a hidden
      // iframe, which needs third-party cookies — blocked by default in current browsers, so
      // every refresh lands back on the sign-in button. Persisting the session and refreshing
      // it with a rotating refresh token is what survives a reload without that iframe.
      // Requires "Allow Offline Access" on the Auth0 API, or no refresh token is issued.
      cacheLocation="localstorage"
      useRefreshTokens
    >
      <QueryClientProvider client={queryClient}>
        <Gate />
      </QueryClientProvider>
    </Auth0Provider>
  </React.StrictMode>,
);
