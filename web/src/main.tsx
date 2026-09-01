import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import { StreamProvider } from "./api/stream";
import { Shell } from "./components/Shell";
import Overview from "./pages/Overview";
import Gpu from "./pages/Gpu";
import Containers from "./pages/Containers";
import Storage from "./pages/Storage";
import Models from "./pages/Models";
import Services from "./pages/Services";
import Network from "./pages/Network";
import Settings from "./pages/Settings";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StreamProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<Overview />} />
            <Route path="gpu" element={<Gpu />} />
            <Route path="containers" element={<Containers />} />
            <Route path="storage" element={<Storage />} />
            <Route path="models" element={<Models />} />
            <Route path="services" element={<Services />} />
            <Route path="network" element={<Network />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </StreamProvider>
  </StrictMode>,
);
