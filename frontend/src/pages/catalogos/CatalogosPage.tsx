import React, { useCallback, useEffect, useState, useMemo } from 'react'
import { diferirCarga } from '../../utils/efectos'
import {
  Globe,
  RotateCcw,
  DollarSign,
  FileText,
  Zap,
  Boxes,
  Scale,
  Coins,
  Search,
  Plus,
  CalendarSearch,
  AlertCircle,
} from 'lucide-react'
import {
  obtenerMonedas,
  obtenerTiposComprobante,
  obtenerTiposOperacion,
  obtenerTiposExistencia,
  obtenerUnidadesMedida,
  obtenerTiposCambio,
  crearTipoCambio,
  resolverTipoCambio,
  type Moneda,
  type TipoComprobante,
  type TipoOperacion,
  type TipoExistencia,
  type UnidadMedida,
  type TipoCambio,
  type TipoCambioResolverResult,
} from '../../api/catalogos'
import { PageHeader } from '../../components/ui/page-header'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Label } from '../../components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs'
import { Modal } from '../../components/ui/modal'
import { fechaCalendarioLocal } from '../../utils/date'
import {
  nuevoTipoCambioInicial,
  payloadTipoCambio,
  type NuevoTipoCambioForm,
} from '../../utils/tipoCambioForm'

export const CatalogosPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('tc')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')

  // Data states
  const [monedas, setMonedas] = useState<Moneda[]>([])
  const [comprobantes, setComprobantes] = useState<TipoComprobante[]>([])
  const [operaciones, setOperaciones] = useState<TipoOperacion[]>([])
  const [existencias, setExistencias] = useState<TipoExistencia[]>([])
  const [unidades, setUnidades] = useState<UnidadMedida[]>([])
  const [tiposCambio, setTiposCambio] = useState<TipoCambio[]>([])

  // Resolver tester state
  const [testMoneda, setTestMoneda] = useState('USD')
  const [testFecha, setTestFecha] = useState(() => fechaCalendarioLocal())
  const [resolviendo, setResolviendo] = useState(false)
  const [resolverError, setResolverError] = useState<string | null>(null)
  const [resolverResult, setResolverResult] = useState<TipoCambioResolverResult | null>(null)

  // New TC modal/form state
  const [modalTcOpen, setModalTcOpen] = useState(false)
  const [nuevoTc, setNuevoTc] = useState<NuevoTipoCambioForm>(() => nuevoTipoCambioInicial())
  const [guardandoTc, setGuardandoTc] = useState(false)

  const cargarDatos = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [m, c, o, e, u, tc] = await Promise.all([
        obtenerMonedas(),
        obtenerTiposComprobante(),
        obtenerTiposOperacion(),
        obtenerTiposExistencia(),
        obtenerUnidadesMedida(),
        obtenerTiposCambio(),
      ])
      setMonedas(m)
      setComprobantes(c)
      setOperaciones(o)
      setExistencias(e)
      setUnidades(u)
      setTiposCambio(tc)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Error al conectar con el servidor de catálogos.')
    } finally {
      setLoading(false)
    }
  }, [])

  // Carga inicial
  useEffect(() => {
    diferirCarga(cargarDatos)
  }, [cargarDatos])

  const handleResolver = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!testFecha) return
    setResolviendo(true)
    setResolverError(null)
    setResolverResult(null)
    try {
      const res = await resolverTipoCambio(testMoneda, testFecha)
      setResolverResult(res)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string; fecha?: string[] } } })?.response?.data?.detail ||
        (err as { response?: { data?: { fecha?: string[] } } })?.response?.data?.fecha?.[0]
      setResolverError(msg || 'No se encontró un tipo de cambio aplicable para esta fecha.')
    } finally {
      setResolviendo(false)
    }
  }

  const handleCrearTc = async (e: React.FormEvent) => {
    e.preventDefault()
    if (guardandoTc) return
    let payload
    try {
      payload = payloadTipoCambio(nuevoTc)
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Fecha de publicación inválida.')
      return
    }
    setGuardandoTc(true)
    setError(null)
    try {
      const creado = await crearTipoCambio(payload)
      setTiposCambio((prev) => [creado, ...prev])
      setModalTcOpen(false)
      setNuevoTc(nuevoTipoCambioInicial())
    } catch (err: unknown) {
      const respData = (err as { response?: { data?: Record<string, string[] | string> } })?.response?.data
      let msg = 'Error al registrar el tipo de cambio.'
      if (respData) {
        msg = Object.entries(respData)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : v}`)
          .join(' | ')
      }
      alert(msg)
    } finally {
      setGuardandoTc(false)
    }
  }

  // Filtered views
  const filteredComprobantes = useMemo(() => {
    const q = searchTerm.toLowerCase()
    return comprobantes.filter(
      (c) => c.codigo_sunat.toLowerCase().includes(q) || c.descripcion.toLowerCase().includes(q)
    )
  }, [comprobantes, searchTerm])

  const filteredOperaciones = useMemo(() => {
    const q = searchTerm.toLowerCase()
    return operaciones.filter(
      (o) =>
        o.codigo_interno.toLowerCase().includes(q) ||
        (o.codigo_sunat && o.codigo_sunat.toLowerCase().includes(q)) ||
        o.descripcion.toLowerCase().includes(q) ||
        o.naturaleza.toLowerCase().includes(q)
    )
  }, [operaciones, searchTerm])

  const filteredExistencias = useMemo(() => {
    const q = searchTerm.toLowerCase()
    return existencias.filter(
      (e) => e.codigo.toLowerCase().includes(q) || e.descripcion.toLowerCase().includes(q)
    )
  }, [existencias, searchTerm])

  const filteredUnidades = useMemo(() => {
    const q = searchTerm.toLowerCase()
    return unidades.filter(
      (u) => u.codigo.toLowerCase().includes(q) || u.descripcion.toLowerCase().includes(q)
    )
  }, [unidades, searchTerm])

  const filteredTc = useMemo(() => {
    const q = searchTerm.toLowerCase()
    return tiposCambio.filter(
      (tc) =>
        tc.fecha_publicacion.includes(q) ||
        tc.moneda_codigo.toLowerCase().includes(q) ||
        tc.fuente.toLowerCase().includes(q)
    )
  }, [tiposCambio, searchTerm])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Catálogos SUNAT y Tipo de Cambio"
        description="Administración centralizada de Tablas 5, 6, 10 y 12 de SUNAT, resolución de Tipo de Cambio SBS/SUNAT y soporte de feriados bancarios."
        icon={<Globe className="h-5 w-5" />}
        badge={<Badge variant="info">SUNAT • Tablas Oficiales</Badge>}
        actions={
          <Button variant="outline" size="sm" onClick={cargarDatos} isLoading={loading}>
            <RotateCcw className="h-4 w-4 mr-1.5" /> Actualizar
          </Button>
        }
      />

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50/90 p-3.5 text-xs text-rose-700 animate-in fade-in"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{error}</span>
        </div>
      )}

      {/* Tabs navigation */}
      <Tabs
        value={activeTab}
        onValueChange={(val) => {
          setActiveTab(val)
          setSearchTerm('')
        }}
      >
        <TabsList className="flex-wrap h-auto p-1.5 gap-1">
          <TabsTrigger value="tc" icon={<DollarSign className="h-3.5 w-3.5" />}>
            Tipo de Cambio SBS ({tiposCambio.length})
          </TabsTrigger>
          <TabsTrigger value="comprobantes" icon={<FileText className="h-3.5 w-3.5" />}>
            Comprobantes (Tabla 10)
          </TabsTrigger>
          <TabsTrigger value="operaciones" icon={<Zap className="h-3.5 w-3.5" />}>
            Operaciones (Tabla 12)
          </TabsTrigger>
          <TabsTrigger value="existencias" icon={<Boxes className="h-3.5 w-3.5" />}>
            Existencias (Tabla 5)
          </TabsTrigger>
          <TabsTrigger value="unidades" icon={<Scale className="h-3.5 w-3.5" />}>
            Unidades (Tabla 6)
          </TabsTrigger>
          <TabsTrigger value="monedas" icon={<Coins className="h-3.5 w-3.5" />}>
            Monedas ({monedas.length})
          </TabsTrigger>
        </TabsList>

        {/* TAB: TIPO DE CAMBIO SBS */}
        <TabsContent value="tc" className="space-y-6">
          {/* Probador interactivo de resolución TC */}
          <Card className="border-indigo-100 bg-linear-to-b from-indigo-50/30 to-white shadow-xs">
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-2xs">
                  <CalendarSearch className="h-4 w-4" />
                </div>
                <div>
                  <CardTitle className="text-base">Probador de Tipo de Cambio Contable Oficial</CardTitle>
                  <CardDescription>
                    Aplica la regla oficial: busca la fecha exacta o, en fines de semana y feriados bancarios, hereda el último tipo de cambio publicado previo.
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <form onSubmit={handleResolver} className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
                <div className="space-y-1.5">
                  <Label>Moneda Extranjera</Label>
                  <Select value={testMoneda} onChange={(e) => setTestMoneda(e.target.value)}>
                    <option value="USD">USD — Dólares Americanos</option>
                    <option value="EUR">EUR — Euros</option>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Fecha del Documento</Label>
                  <Input
                    type="date"
                    value={testFecha}
                    onChange={(e) => setTestFecha(e.target.value)}
                    required
                    className="font-mono tabular-nums"
                  />
                </div>
                <Button type="submit" variant="primary" isLoading={resolviendo}>
                  <CalendarSearch className="h-4 w-4 mr-1.5" /> Resolver Tipo de Cambio
                </Button>
              </form>

              {resolverError && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 font-medium">
                  {resolverError}
                </div>
              )}

              {resolverResult && (
                <div className="rounded-xl border border-indigo-200/80 bg-white p-4 shadow-xs space-y-3 animate-in fade-in">
                  <div className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-slate-100">
                    <Badge variant={resolverResult.es_fecha_exacta ? 'success' : 'warning'} dot>
                      {resolverResult.es_fecha_exacta
                        ? 'Fecha Exacta Publicada'
                        : 'Fin de Semana / Feriado (Último TC publicado previo)'}
                    </Badge>
                    <span className="text-xs text-slate-500 font-medium">
                      Fuente Oficial: <strong className="text-slate-800">{resolverResult.fuente}</strong>
                    </span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
                    <div>
                      <span className="text-slate-500 block">Fecha Consultada:</span>
                      <strong className="font-mono tabular-nums text-slate-900 text-sm">
                        {resolverResult.fecha_consultada}
                      </strong>
                    </div>
                    <div>
                      <span className="text-slate-500 block">Fecha Publicación:</span>
                      <strong className="font-mono tabular-nums text-slate-900 text-sm">
                        {resolverResult.fecha_publicacion}
                      </strong>
                    </div>
                    <div className="rounded-lg bg-emerald-50 border border-emerald-200/80 p-2 text-center">
                      <span className="text-emerald-700 text-[11px] font-semibold block">TC Compra:</span>
                      <strong className="font-mono tabular-nums text-emerald-800 text-base">
                        S/ {resolverResult.compra}
                      </strong>
                    </div>
                    <div className="rounded-lg bg-indigo-50 border border-indigo-200/80 p-2 text-center">
                      <span className="text-indigo-700 text-[11px] font-semibold block">TC Venta:</span>
                      <strong className="font-mono tabular-nums text-indigo-800 text-base">
                        S/ {resolverResult.venta}
                      </strong>
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* List Header & Action */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="w-full sm:w-80">
              <Input
                type="text"
                placeholder="Buscar por fecha, moneda o fuente..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                leftIcon={<Search className="h-4 w-4" />}
              />
            </div>
            <Button variant="primary" onClick={() => setModalTcOpen(true)}>
              <Plus className="h-4 w-4 mr-1.5" /> Registrar Tipo de Cambio
            </Button>
          </div>

          {/* Exchange Rates Table */}
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Moneda</TableHead>
                    <TableHead>Fecha Publicación</TableHead>
                    <TableHead numeric>Compra (S/)</TableHead>
                    <TableHead numeric>Venta (S/)</TableHead>
                    <TableHead>Fuente</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredTc.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center py-8 text-slate-400">
                        No hay tipos de cambio registrados con este criterio.
                      </TableCell>
                    </TableRow>
                  ) : (
                    filteredTc.map((tc) => (
                      <TableRow key={tc.id}>
                        <TableCell>
                          <Badge variant="neutral" className="font-mono font-bold">
                            {tc.moneda_codigo}
                          </Badge>
                        </TableCell>
                        <TableCell numeric className="text-slate-700">
                          {tc.fecha_publicacion}
                        </TableCell>
                        <TableCell numeric className="text-emerald-700 font-semibold text-sm">
                          {tc.compra ?? '—'}
                        </TableCell>
                        <TableCell numeric className="text-indigo-700 font-semibold text-sm">
                          {tc.venta ?? '—'}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="font-mono text-[10px]">
                            {tc.fuente}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB: COMPROBANTES (Tabla 10) */}
        <TabsContent value="comprobantes" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="w-full sm:w-80">
              <Input
                type="text"
                placeholder="Buscar código SUNAT o descripción..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                leftIcon={<Search className="h-4 w-4" />}
              />
            </div>
            <Badge variant="neutral" className="font-mono">
              {filteredComprobantes.length} tipos de comprobante
            </Badge>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-24">Cód. SUNAT</TableHead>
                    <TableHead>Descripción</TableHead>
                    <TableHead>Clasificación</TableHead>
                    <TableHead>Efecto Contable</TableHead>
                    <TableHead>Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredComprobantes.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell numeric className="font-bold text-slate-900">
                        {c.codigo_sunat}
                      </TableCell>
                      <TableCell className="font-medium text-slate-800">{c.descripcion}</TableCell>
                      <TableCell>
                        <Badge variant={c.es_nota ? 'info' : 'neutral'}>
                          {c.es_nota ? 'Nota Oficial' : 'Comprobante Base'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            c.efecto_nota === 'CREDITO'
                              ? 'destructive'
                              : c.efecto_nota === 'DEBITO'
                              ? 'info'
                              : 'neutral'
                          }
                        >
                          {c.efecto_nota || 'NINGUNO'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={c.activo ? 'success' : 'neutral'} dot>
                          {c.activo ? 'ACTIVO' : 'INACTIVO'}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB: OPERACIONES (Tabla 12) */}
        <TabsContent value="operaciones" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="w-full sm:w-80">
              <Input
                type="text"
                placeholder="Buscar por código interno, SUNAT o naturaleza..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                leftIcon={<Search className="h-4 w-4" />}
              />
            </div>
            <Badge variant="neutral" className="font-mono">
              {filteredOperaciones.length} operaciones
            </Badge>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-24">Cód. Interno</TableHead>
                    <TableHead className="w-24">Cód. SUNAT</TableHead>
                    <TableHead>Descripción</TableHead>
                    <TableHead>Naturaleza</TableHead>
                    <TableHead>Origen Requerido</TableHead>
                    <TableHead>Afecta Kardex</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredOperaciones.map((o) => (
                    <TableRow key={o.id}>
                      <TableCell numeric className="font-bold text-slate-900">
                        {o.codigo_interno}
                      </TableCell>
                      <TableCell numeric className="text-slate-600">
                        {o.codigo_sunat || '—'}
                      </TableCell>
                      <TableCell className="font-medium text-slate-800">{o.descripcion}</TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            o.naturaleza === 'ENTRADA'
                              ? 'info'
                              : o.naturaleza === 'SALIDA'
                              ? 'warning'
                              : 'destructive'
                          }
                        >
                          {o.naturaleza}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <code className="text-[11px] font-mono text-slate-600">
                          {o.origen_requerido || 'NINGUNO'}
                        </code>
                      </TableCell>
                      <TableCell>
                        <Badge variant={o.afecta_kardex ? 'success' : 'neutral'} dot>
                          {o.afecta_kardex ? 'AFECTA' : 'NO AFECTA'}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB: EXISTENCIAS (Tabla 5) */}
        <TabsContent value="existencias" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="w-full sm:w-80">
              <Input
                type="text"
                placeholder="Buscar código o descripción de existencia..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                leftIcon={<Search className="h-4 w-4" />}
              />
            </div>
            <Badge variant="neutral" className="font-mono">
              {filteredExistencias.length} tipos (Tabla 5 SUNAT)
            </Badge>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-28">Código</TableHead>
                    <TableHead>Descripción Oficial Tabla 5 SUNAT</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredExistencias.map((e) => (
                    <TableRow key={e.codigo}>
                      <TableCell numeric className="font-bold text-slate-900 text-sm">
                        {e.codigo}
                      </TableCell>
                      <TableCell className="font-medium text-slate-800">{e.descripcion}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB: UNIDADES (Tabla 6) */}
        <TabsContent value="unidades" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div className="w-full sm:w-80">
              <Input
                type="text"
                placeholder="Buscar código o unidad..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                leftIcon={<Search className="h-4 w-4" />}
              />
            </div>
            <Badge variant="neutral" className="font-mono">
              {filteredUnidades.length} unidades (Tabla 6 SUNAT)
            </Badge>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-32">Código SUNAT</TableHead>
                    <TableHead>Descripción Oficial de Unidad de Medida</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredUnidades.map((u) => (
                    <TableRow key={u.codigo}>
                      <TableCell>
                        <Badge variant="info" className="font-mono font-bold">
                          {u.codigo}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium text-slate-800">{u.descripcion}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB: MONEDAS */}
        <TabsContent value="monedas" className="space-y-4">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-28">Código ISO</TableHead>
                    <TableHead>Nombre Oficial de la Moneda</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {monedas.map((m) => (
                    <TableRow key={m.codigo}>
                      <TableCell>
                        <Badge variant="neutral" className="font-mono font-bold text-xs">
                          {m.codigo}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium text-slate-800">{m.nombre}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Modal Registrar Tipo de Cambio */}
      {modalTcOpen && (
        <Modal
          isOpen={modalTcOpen}
          onClose={() => setModalTcOpen(false)}
          title="Registrar Tipo de Cambio Oficial"
          description="Publicación oficial SBS/SUNAT para valorización contable."
          icon={<DollarSign className="h-5 w-5" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setModalTcOpen(false)}>
                Cancelar
              </Button>
              <Button variant="primary" onClick={handleCrearTc} isLoading={guardandoTc}>
                Guardar Tipo de Cambio
              </Button>
            </div>
          }
        >
          <form onSubmit={handleCrearTc} className="space-y-4">
            <div className="space-y-1.5">
              <Label required>Moneda</Label>
              <Select
                value={nuevoTc.moneda_codigo}
                onChange={(e) => {
                  const valor = e.target.value
                  setNuevoTc((prev) => ({ ...prev, moneda_codigo: valor }))
                }}
                required
              >
                <option value="USD">USD — Dólares Americanos</option>
                <option value="EUR">EUR — Euros</option>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label required>Fecha de Publicación</Label>
              <Input
                type="date"
                value={nuevoTc.fecha_publicacion}
                onChange={(e) => {
                  const valor = e.target.value
                  setNuevoTc((prev) => ({ ...prev, fecha_publicacion: valor }))
                }}
                required
                className="font-mono tabular-nums"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label required>Compra (S/)</Label>
                <Input
                  type="number"
                  step="0.00000001"
                  min="0.00000001"
                  placeholder="3.74200000"
                  value={nuevoTc.compra}
                  onChange={(e) => {
                    const valor = e.target.value
                    setNuevoTc((prev) => ({ ...prev, compra: valor }))
                  }}
                  className="font-mono tabular-nums"
                  required
                />
              </div>

              <div className="space-y-1.5">
                <Label required>Venta (S/)</Label>
                <Input
                  type="number"
                  step="0.00000001"
                  min="0.00000001"
                  placeholder="3.75100000"
                  value={nuevoTc.venta}
                  onChange={(e) => {
                    const valor = e.target.value
                    setNuevoTc((prev) => ({ ...prev, venta: valor }))
                  }}
                  className="font-mono tabular-nums"
                  required
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label required>Fuente Oficial</Label>
              <Input
                type="text"
                value={nuevoTc.fuente}
                onChange={(e) => {
                  const valor = e.target.value
                  setNuevoTc((prev) => ({ ...prev, fuente: valor }))
                }}
                placeholder="SBS / SUNAT"
                required
              />
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}

export default CatalogosPage
