import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";

import ConfigPage from "./routes/ConfigPage";
import RunDetailPage from "./routes/RunDetailPage";
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
        <Routes>
          <Route path="/" element={<ConfigPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
        </Routes>
      </SidecarReadyGate>
    </SidecarErrorBoundary>
  );
}
