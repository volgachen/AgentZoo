import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import "./index.css";
import App from "./App.tsx";
import AgentRegistry from "./pages/AgentRegistry.tsx";
import SessionDashboard from "./pages/SessionDashboard.tsx";
import LiveConsole from "./pages/LiveConsole.tsx";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <AgentRegistry /> },
      { path: "sessions", element: <SessionDashboard /> },
      { path: "console/:sessionId", element: <LiveConsole /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
