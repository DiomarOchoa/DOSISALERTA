import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// Punto de entrada de la aplicacion. StrictMode ayuda a detectar
// efectos con problemas durante el desarrollo; no cambia el
// comportamiento en produccion.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
