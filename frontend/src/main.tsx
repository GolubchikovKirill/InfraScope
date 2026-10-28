import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider, MutationCache } from "@tanstack/react-query";
import { AuthProvider } from "./auth";
import App from "./App";
import { initDensityMode, initThemeMode } from "./theme";
import { apiErrorMessage } from "./lib/apiError";
import { showToast } from "./lib/toastBus";
import ToastContainer from "./components/ToastContainer";
import { ConfirmProvider } from "./components/ConfirmDialog";
// Self-hosted, variable weight, split by unicode-range so only the latin and
// cyrillic subsets are fetched - and from this server, not fonts.googleapis.com:
// that stylesheet blocked the first paint for as long as the corporate gateway
// took to answer (or time out) on every cold load.
import "@fontsource-variable/inter";
// RegStaer-M display face: a free stand-in for the brand's licensed Sang Bleu.
// Headings and the wordmark only - tables and labels stay in Inter.
import "@fontsource/cormorant-garamond/500.css";
import "@fontsource/cormorant-garamond/500-italic.css";
import "./index.css";

initThemeMode();
initDensityMode();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 20_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
    },
    mutations: {
      retry: 0,
    },
  },
  // Individual mutations keep their own onSuccess/onError for query
  // invalidation and local state - this just adds a visible toast for any
  // mutation that fails, since most call sites had no user-facing feedback
  // at all when a click silently failed.
  mutationCache: new MutationCache({
    onError: (error) => {
      showToast(apiErrorMessage(error), "error");
    },
  }),
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ConfirmProvider>
            <App />
            <ToastContainer />
          </ConfirmProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
