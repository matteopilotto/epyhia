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
  const { isLoading, isAuthenticated, loginWithRedirect, getAccessTokenSilently } = useAuth0();

  useEffect(() => {
    setTokenGetter(() => getAccessTokenSilently({ authorizationParams: { audience } }));
  }, [getAccessTokenSilently]);

  if (isLoading) return <p className="p-6 text-ink-muted">Loading…</p>;
  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center">
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
    >
      <QueryClientProvider client={queryClient}>
        <Gate />
      </QueryClientProvider>
    </Auth0Provider>
  </React.StrictMode>,
);
