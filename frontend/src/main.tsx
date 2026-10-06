import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import { createDemoApi } from "./api/demo";
import "./styles.css";
import { httpApi } from "./api/http";
const api = import.meta.env.VITE_DEMO === "true" ? createDemoApi() : httpApi();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App api={api} />
    </BrowserRouter>
  </StrictMode>,
);
