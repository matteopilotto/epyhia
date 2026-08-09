import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { RootLayout } from "@/routes/root";
import { RunsRoute, RunDetailRoute } from "@/routes/runs";
import { ApprovalsRoute } from "@/routes/approvals";
import { ArtifactsRoute } from "@/routes/artifacts";
import { BrandDocRoute } from "@/routes/brand-doc";

const rootRoute = createRootRoute({ component: RootLayout });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: RunsRoute,
});

const runsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs",
  component: RunsRoute,
});

const runDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$runId",
  component: RunDetailRoute,
});

const runArtifactsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$runId/artifacts",
  component: ArtifactsRoute,
});

const runBrandDocRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/runs/$runId/brand-doc",
  component: BrandDocRoute,
});

const approvalsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/approvals",
  component: ApprovalsRoute,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  runsRoute,
  runDetailRoute,
  runArtifactsRoute,
  runBrandDocRoute,
  approvalsRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
