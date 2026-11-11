import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/guards'
import AppLayout from './components/AppLayout'
import { applyFont, loadFontChoice } from './lib/fonts'
import { setBoardKey } from './lib/session'
import AccountPage from './pages/AccountPage'
import DealFormPage from './pages/DealFormPage'
import DealsPage from './pages/DealsPage'
import ClientsPage from './pages/admin/ClientsPage'
import FlagsPage from './pages/admin/FlagsPage'
import ItemsPage from './pages/admin/ItemsPage'
import MonthsPage from './pages/admin/MonthsPage'
import NamesPage from './pages/admin/NamesPage'
import QuotasPage from './pages/admin/QuotasPage'
import RepsPage from './pages/admin/RepsPage'
import SettingsPage from './pages/admin/SettingsPage'
import SheetPage from './pages/admin/SheetPage'
import UsersPage from './pages/admin/UsersPage'
import BoardPage from './pages/BoardPage'
import LoginPage from './pages/LoginPage'
import ReportsClientsPage from './pages/reports/ClientsPage'
import ReportsOverviewPage from './pages/reports/OverviewPage'
import ReportsProductsPage from './pages/reports/ProductsPage'
import ReportsLayout from './pages/reports/ReportsLayout'
import ReportsRepsPage from './pages/reports/RepsPage'
import ReportsTrendsPage from './pages/reports/TrendsPage'
import './index.css'
import './app.css'

// Restore this device's font choice before first render.
applyFont(loadFontChoice(), false)

// A TV link (/board?key=...) saves the read-only key on this device, then drops it from the address bar.
const url = new URL(window.location.href)
const key = url.searchParams.get('key')
if (key) {
  setBoardKey(key)
  url.searchParams.delete('key')
  window.history.replaceState(null, '', url.pathname + url.search + url.hash)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          {/* /board always follows the current month, so the TV never needs changing. */}
          <Route path="/board" element={<RequireAuth need="viewer"><BoardPage /></RequireAuth>} />
          <Route path="/board/:periodId" element={<RequireAuth need="viewer"><BoardPage /></RequireAuth>} />
          {/* Read-only pages: open to TV displays too. */}
          <Route element={<RequireAuth need="viewer"><AppLayout /></RequireAuth>}>
            <Route path="/reports" element={<ReportsLayout />}>
              <Route index element={<ReportsOverviewPage />} />
              <Route path="reps" element={<ReportsRepsPage />} />
              <Route path="products" element={<ReportsProductsPage />} />
              <Route path="clients" element={<ReportsClientsPage />} />
              <Route path="trends" element={<ReportsTrendsPage />} />
            </Route>
          </Route>
          <Route element={<RequireAuth need="user"><AppLayout /></RequireAuth>}>
            <Route path="/account" element={<AccountPage />} />
            <Route path="/deals" element={<DealsPage />} />
            <Route path="/deals/new" element={<DealFormPage />} />
            <Route path="/deals/:dealId" element={<DealFormPage key="edit" />} />
          </Route>
          <Route path="/admin" element={<RequireAuth need="admin"><AppLayout /></RequireAuth>}>
            <Route index element={<Navigate to="months" replace />} />
            <Route path="months" element={<MonthsPage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="reps" element={<RepsPage />} />
            <Route path="quotas" element={<QuotasPage />} />
            <Route path="items" element={<ItemsPage />} />
            <Route path="clients" element={<ClientsPage />} />
            <Route path="client-names" element={<NamesPage key="client" kind="client" />} />
            <Route path="item-names" element={<NamesPage key="item" kind="item" />} />
            <Route path="sheet" element={<SheetPage />} />
            <Route path="flags" element={<FlagsPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/board" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
