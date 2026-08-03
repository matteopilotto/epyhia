import { Link, Outlet } from "@tanstack/react-router";
import { useAuth0 } from "@auth0/auth0-react";
import { Button } from "@/components/ui/button";

export function RootLayout() {
  const { user, logout } = useAuth0();

  return (
    <div className="min-h-screen">
      <header className="flex items-center gap-6 border-b border-line px-6 py-3">
        <span className="font-semibold tracking-tight">EPYHIA</span>
        <nav className="flex gap-4 text-sm text-ink-muted">
          <Link to="/runs" className="hover:text-ink [&.active]:text-ink">
            Runs
          </Link>
          <Link to="/approvals" className="hover:text-ink [&.active]:text-ink">
            Approvals
          </Link>
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm text-ink-muted">
          <span>{user?.email ?? user?.sub}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => logout({ logoutParams: { returnTo: window.location.origin } })}
          >
            Sign out
          </Button>
        </div>
      </header>
      <main className="px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
