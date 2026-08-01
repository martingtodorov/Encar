import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AppProvider } from "@/context/AppContext";
import SearchPage from "@/pages/SearchPage";
import CarDetailPage from "@/pages/CarDetailPage";
import SavedCarsPage from "@/pages/SavedCarsPage";
import HowItWorksPage from "@/pages/HowItWorksPage";

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/car/:id" element={<CarDetailPage />} />
          <Route path="/saved" element={<SavedCarsPage />} />
          <Route path="/how-it-works" element={<HowItWorksPage />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" />
    </AppProvider>
  );
}

export default App;
