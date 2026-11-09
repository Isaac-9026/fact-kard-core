import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { MainLayout } from './layouts/MainLayout';
import { RutaProtegida } from './components/auth/RutaProtegida';
import { LoginPage } from './pages/auth/LoginPage';
import { EmpresasPage } from './pages/empresas/EmpresasPage';
import { DashboardPage } from './pages/dashboard/DashboardPage';
import { RUTA_INICIAL, RUTAS_ANTERIORES, destinoRedireccion } from './navegacion';

// Bloque 6: code splitting. Login, Dashboard y Empresas (pantallas de entrada) van en el
// bundle principal; el resto de módulos se descarga al visitarlos por primera vez.
const AuditoriaPage = lazy(() => import('./pages/auditoria/AuditoriaPage').then((m) => ({ default: m.AuditoriaPage })));
const CatalogosPage = lazy(() => import('./pages/catalogos/CatalogosPage').then((m) => ({ default: m.CatalogosPage })));
const PeriodosPage = lazy(() => import('./pages/periodos/PeriodosPage').then((m) => ({ default: m.PeriodosPage })));
const MaestrosInventarioPage = lazy(() => import('./pages/inventario/MaestrosInventarioPage').then((m) => ({ default: m.MaestrosInventarioPage })));
const DocumentosPage = lazy(() => import('./pages/documentos/DocumentosPage').then((m) => ({ default: m.DocumentosPage })));
const StockActualPage = lazy(() => import('./pages/inventario/StockActualPage').then((m) => ({ default: m.StockActualPage })));
const OperacionesInternasPage = lazy(() => import('./pages/operaciones/OperacionesInternasPage').then((m) => ({ default: m.OperacionesInternasPage })));
const TransferenciasPage = lazy(() => import('./pages/transferencias/TransferenciasPage').then((m) => ({ default: m.TransferenciasPage })));
const IncidenciasPage = lazy(() => import('./pages/incidencias/IncidenciasPage').then((m) => ({ default: m.IncidenciasPage })));
const KardexPage = lazy(() => import('./pages/kardex/KardexPage').then((m) => ({ default: m.KardexPage })));
const CierresPage = lazy(() => import('./pages/cierres/CierresPage').then((m) => ({ default: m.CierresPage })));
const CapturaHomologacionPage = lazy(() => import('./pages/captura/CapturaHomologacionPage').then((m) => ({ default: m.CapturaHomologacionPage })));
const CuentasPage = lazy(() => import('./pages/finanzas/CuentasPage').then((m) => ({ default: m.CuentasPage })));
const RegistroComercialPage = lazy(() => import('./pages/finanzas/RegistroComercialPage').then((m) => ({ default: m.RegistroComercialPage })));
const Formato131Page = lazy(() => import('./pages/formato131/Formato131Page').then((m) => ({ default: m.Formato131Page })));

const CargandoModulo: React.FC = () => (
  <div className="py-20 text-center text-sm text-slate-500" role="status">Cargando módulo...</div>
);

const diferido = (Componente: React.ComponentType) => (
  <Suspense fallback={<CargandoModulo />}>
    <Componente />
  </Suspense>
);

// Comprobantes (con pestañas Todos | Compras | Ventas) y Notas reutilizan DocumentosPage;
// Productos, Almacenes y Terceros reutilizan MaestrosInventarioPage. La `key` fuerza un
// estado limpio al cambiar de opción.
const vistaDocumentos = (vista: 'COMPROBANTES' | 'NOTAS') => (
  <Suspense fallback={<CargandoModulo />}>
    <DocumentosPage key={vista} vista={vista} />
  </Suspense>
);
const vistaMaestro = (vista: 'productos' | 'almacenes' | 'terceros') => (
  <Suspense fallback={<CargandoModulo />}>
    <MaestrosInventarioPage key={vista} vista={vista} />
  </Suspense>
);

// Bloque 16: Cuentas por cobrar y por pagar comparten pantalla.
const vistaCuentas = (tipo: 'cobrar' | 'pagar') => (
  <Suspense fallback={<CargandoModulo />}>
    <CuentasPage key={tipo} tipo={tipo} />
  </Suspense>
);

// Rutas antiguas: redirigen conservando los parámetros (/compras?nuevo=1 sigue abriendo el formulario).
const RedireccionAnterior: React.FC<{ hacia: string }> = ({ hacia }) => {
  const { search } = useLocation();
  return <Navigate to={destinoRedireccion(hacia, search)} replace />;
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Ruta de autenticación */}
          <Route path="/login" element={<LoginPage />} />

          {/* Rutas principales protegidas por MainLayout */}
          <Route element={<RutaProtegida />}>
            <Route path="/" element={<MainLayout />}>
              <Route index element={<Navigate to={RUTA_INICIAL} replace />} />
              {/* INICIO */}
              <Route path="dashboard" element={<DashboardPage />} />
              {/* CONFIGURACIÓN */}
              <Route path="empresas" element={<EmpresasPage />} />
              <Route path="periodos" element={diferido(PeriodosPage)} />
              <Route path="catalogos" element={diferido(CatalogosPage)} />
              {/* MAESTROS */}
              <Route path="productos" element={vistaMaestro('productos')} />
              <Route path="almacenes" element={vistaMaestro('almacenes')} />
              <Route path="terceros" element={vistaMaestro('terceros')} />
              {/* INVENTARIO INICIAL */}
              <Route path="saldo-inicial" element={diferido(OperacionesInternasPage)} />
              <Route path="inventario" element={diferido(StockActualPage)} />
              {/* OPERACIONES */}
              <Route path="comprobantes" element={vistaDocumentos('COMPROBANTES')} />
              <Route path="notas" element={vistaDocumentos('NOTAS')} />
              <Route path="transferencias" element={diferido(TransferenciasPage)} />
              <Route path="captura-homologacion" element={diferido(CapturaHomologacionPage)} />
              {/* KARDEX */}
              <Route path="cuentas-por-cobrar" element={vistaCuentas('cobrar')} />
              <Route path="cuentas-por-pagar" element={vistaCuentas('pagar')} />

              <Route path="kardex" element={diferido(KardexPage)} />
              <Route path="incidencias" element={diferido(IncidenciasPage)} />
              {/* CIERRE Y REPORTES */}
              <Route path="cierres" element={diferido(CierresPage)} />
              <Route path="formato-13-1" element={diferido(Formato131Page)} />
              <Route path="registro-ventas-compras" element={diferido(RegistroComercialPage)} />
              {/* SEGURIDAD */}
              <Route path="auditoria" element={diferido(AuditoriaPage)} />
              {/* Rutas anteriores (enlaces guardados) */}
              {Object.entries(RUTAS_ANTERIORES).map(([desde, hacia]) => (
                <Route key={desde} path={desde.slice(1)} element={<RedireccionAnterior hacia={hacia} />} />
              ))}
            </Route>
          </Route>

          {/* Redirección wildcard */}
          <Route path="*" element={<Navigate to={RUTA_INICIAL} replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
