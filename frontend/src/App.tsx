import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "@/components/AppLayout";
import { RequireAuth, RequireRole } from "@/components/RequireAuth";
import { useAuth } from "@/features/auth/api";
import { LoginPage } from "@/features/auth/LoginPage";
import { DocumentViewPage } from "@/features/documents/DocumentViewPage";
import { InboxPage } from "@/features/documents/InboxPage";
import { ExtractorsPage } from "@/features/extractors/ExtractorsPage";
import { ReviewPage } from "@/features/review/ReviewPage";
import { TaxonomiesPage } from "@/features/taxonomies/TaxonomiesPage";
import { UsersPage } from "@/features/users/UsersPage";
import { WorkflowPage } from "@/features/workflow/WorkflowPage";

export default function App() {
  const authed = useAuth();

  return (
    <Routes>
      <Route path="/login" element={authed ? <Navigate to="/inbox" replace /> : <LoginPage />} />

      {/* Authed app shell */}
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/inbox" replace />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/inbox/:docId" element={<DocumentViewPage />} />
          <Route path="/workflow" element={<WorkflowPage />} />
          <Route path="/review" element={<ReviewPage />} />

          {/* Prompt authoring (prompt_author / admin) */}
          <Route element={<RequireRole anyOf={["prompt_author"]} />}>
            <Route path="/taxonomies" element={<TaxonomiesPage />} />
            <Route path="/extractors" element={<ExtractorsPage />} />
          </Route>

          {/* User management (admin) */}
          <Route element={<RequireRole anyOf={["admin"]} />}>
            <Route path="/users" element={<UsersPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/inbox" replace />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to={authed ? "/inbox" : "/login"} replace />} />
    </Routes>
  );
}
