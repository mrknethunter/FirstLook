import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./i18n";
import "./style.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: 0, retry: 1 } } });
ReactDOM.createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={queryClient}>
    <BrowserRouter><App /></BrowserRouter>
  </QueryClientProvider>,
);
