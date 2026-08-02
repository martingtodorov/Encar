import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AppProvider } from "@/context/AppContext";
import { AuthProvider } from "@/context/AuthContext";
import { LangLayout, LangRedirect } from "@/components/LangLayout";
import SearchPage from "@/pages/SearchPage";
import CarDetailPage from "@/pages/CarDetailPage";
import SavedCarsPage from "@/pages/SavedCarsPage";
import SavedSearchesPage from "@/pages/SavedSearchesPage";
import HowItWorksPage from "@/pages/HowItWorksPage";
import LoginPage from "@/pages/LoginPage";
import AccountPage from "@/pages/AccountPage";
import AdminPage from "@/pages/AdminPage";

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Each language has its own address so all three can be indexed. */}
            <Route path="/:lang" element={<LangLayout />}>
              <Route index element={<SearchPage />} />
              <Route path="car/:id" element={<CarDetailPage />} />
              <Route path="saved" element={<SavedCarsPage />} />
              <Route path="searches" element={<SavedSearchesPage />} />
              <Route path="how-it-works" element={<HowItWorksPage />} />
              <Route path="login" element={<LoginPage />} />
              <Route path="account" element={<AccountPage />} />
              <Route path="admin" element={<AdminPage />} />
            </Route>
            {/* Bare and legacy URLs keep working: same page, language added. */}
            <Route path="*" element={<LangRedirect />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
      <Toaster position="bottom-right" />
    </AppProvider>
  );
}

export default App;
