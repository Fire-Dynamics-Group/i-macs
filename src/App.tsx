import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";

import BatchProgressPage from "./routes/BatchProgressPage";
import ConfigPage from "./routes/ConfigPage";
import RunDetailPage from "./routes/RunDetailPage";
import RunsDashboardPage from "./routes/RunsDashboardPage";
import { AppShell } from "./components/AppShell";
import { SidecarErrorBoundary } from "./components/SidecarErrorScreen";
import { SidecarReadyGate } from "./components/SidecarReadyGate";
import { checkForUpdates } from "./lib/updater";

export default function App() {
  // Silent update check on launch. Failures are swallowed — the user can
  // re-run via the manual "Check for updates" trigger that lives on the
  // config page (slice 5 polish will pull this into a settings sheet).
  useEffect(() => {
    checkForUpdates({ silent: true });
  }, []);

  return (
    <SidecarErrorBoundary>
      <SidecarReadyGate>
        <AppShell>
          <Routes>
            <Route path="/" element={<ConfigPage />} />
            <Route path="/runs" element={<RunsDashboardPage />} />
            <Route path="/runs/:id" element={<RunDetailPage />} />
            <Route path="/batches/:batch_id" element={<BatchProgressPage />} />
          </Routes>
        </AppShell>
      </SidecarReadyGate>
    </SidecarErrorBoundary>
  );
}
