import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AppProvider } from "@/context/AppContext";
import { AuthProvider } from "@/context/AuthContext";
import { LangLayout, LangRedirect } from "@/components/LangLayout";
import { PasskeyPrompt } from "@/components/PasskeyPrompt";
import SearchPage from "@/pages/SearchPage";
import CarDetailPage from "@/pages/CarDetailPage";
import SavedCarsPage from "@/pages/SavedCarsPage";
import SavedSearchesPage from "@/pages/SavedSearchesPage";
import HowItWorksPage from "@/pages/HowItWorksPage";
import TrackPage from "@/pages/TrackPage";
import LoginPage from "@/pages/LoginPage";
import AccountPage from "@/pages/AccountPage";
import AdminPage from "@/pages/AdminPage";
import LegalPage from "@/pages/LegalPage";
import PaymentResultPage from "@/pages/PaymentResultPage";
import MyPurchasesPage from "@/pages/MyPurchasesPage";

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
              <Route path="track" element={<TrackPage />} />
              <Route path="login" element={<LoginPage />} />
              <Route path="account" element={<AccountPage />} />
              <Route path="admin" element={<AdminPage />} />
              <Route path="terms" element={<LegalPage slug="terms" />} />
              <Route path="privacy" element={<LegalPage slug="privacy" />} />
              <Route path="cookies" element={<LegalPage slug="cookies" />} />
              <Route path="contact" element={<LegalPage slug="contact" />} />
              <Route path="faq" element={<LegalPage slug="faq" />} />
              <Route path="fees" element={<LegalPage slug="fees" />} />
              <Route path="purchases" element={<MyPurchasesPage />} />
              <Route path="payment/success" element={<PaymentResultPage outcome="success" />} />
              <Route path="payment/cancel" element={<PaymentResultPage outcome="cancel" />} />
            </Route>
            {/* Bare and legacy URLs keep working: same page, language added. */}
            <Route path="*" element={<LangRedirect />} />
          </Routes>
          <PasskeyPrompt />
        </AuthProvider>
      </BrowserRouter>
      <Toaster position="bottom-right" />
    </AppProvider>
  );
}

export default App;
