import React, { useCallback, useEffect, useState, type FormEvent } from 'react'
import axios from 'axios'
import {
  Building2,
  MapPin,
  Sliders,
  Plus,
  X,
  CheckCircle2,
  AlertCircle,
  Save,
  Check,
  Hash,
  FileBadge,
  Palette,
  UploadCloud,
  Trash2,
  Sparkles,
  Eye,
} from 'lucide-react'
import {
  PALETAS_EJECUTIVAS,
  generarThemingSidebar,
  obtenerFiltroLogo,
  obtenerInicialesEmpresa,
  procesarImagenLogo,
  resolverUrlMedia,
  esHexValido,
} from '../../utils/identidadEmpresa'
import { DatosFiscalesPanel } from '../../components/tributario/DatosFiscalesPanel'
import { ConsultaRucBoton } from '../../components/consultaRuc/ConsultaRucBoton'
import { MAPA_EMPRESA_NUEVA, puedeConsultarRuc } from '../../utils/consultaRuc'
import { SeriesComprobantePanel } from '../../components/finanzas/SeriesComprobantePanel'
import {
  actualizarConfigEmpresa,
  actualizarEstablecimiento,
  actualizarIdentidadEmpresaApi,
  crearEmpresa,
  crearEstablecimiento,
  obtenerConfigEmpresa,
  obtenerEstablecimientos,
  obtenerMonedas,
  type ConfigEmpresa,
  type Establecimiento,
  type Moneda,
} from '../../api/empresas'
import { useAuth } from '../../context/useAuth'
import { PageHeader } from '../../components/ui/page-header'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Label } from '../../components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs'
import { diferirCarga } from '../../utils/efectos'

const mensajeError = (error: unknown) => {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data
    if (typeof data === 'string') return data
    if (data && typeof data === 'object') return Object.values(data).flat().join(' ')
  }
  return 'No se pudo completar la operación.'
}

// Bloque 17A: dirección y ubigeo del establecimiento (el principal es ConfigEmpresa).
const ESTABLECIMIENTO_INICIAL = { codigo_sunat: '', nombre: '', activo: true, direccion: '', ubigeo: '' }

export const EmpresasPage: React.FC = () => {
  const {
    empresaActiva,
    empresasDisponibles,
    registrarEmpresaDisponible,
    refrescarEmpresasDisponibles,
    seleccionarEmpresa,
    usuario,
    actualizarIdentidadEmpresa,
  } = useAuth()
  const esAdminActiva = Boolean(usuario?.es_admin_global || empresaActiva?.rol === 'ADMIN')
  const [monedas, setMonedas] = useState<Moneda[]>([])
  const [establecimientos, setEstablecimientos] = useState<Establecimiento[]>([])
  const [config, setConfig] = useState<ConfigEmpresa | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [mostrarEmpresa, setMostrarEmpresa] = useState(false)
  const [editando, setEditando] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState('empresas')

  const [empresaForm, setEmpresaForm] = useState({
    ruc: '',
    razon_social: '',
    nombre_comercial: '',
    direccion: '',
    moneda_base_codigo: 'PEN',
  })
  const [establecimientoForm, setEstablecimientoForm] = useState(ESTABLECIMIENTO_INICIAL)
  const [configForm, setConfigForm] = useState({
    tolerancia_residuo_pen: '0.05000000',
    decimales_calculo: 6,
    establecimiento_principal: '',
  })

  // Identidad Visual Multiempresa
  const [identidadColor, setIdentidadColor] = useState<string | null>(empresaActiva?.color_tema ?? null)
  const [identidadLogoFile, setIdentidadLogoFile] = useState<File | null>(null)
  const [identidadLogoPreview, setIdentidadLogoPreview] = useState<string | null>(empresaActiva?.logo || null)
  const [quitarLogoPendiente, setQuitarLogoPendiente] = useState(false)
  const [procesandoLogo, setProcesandoLogo] = useState(false)
  const [colorSugeridoExtraido, setColorSugeridoExtraido] = useState<string | null>(null)
  const logoPreviewUrl = React.useMemo(() => resolverUrlMedia(identidadLogoPreview), [identidadLogoPreview])
  // Se recuerda QUÉ URL de vista previa falló: otra vista previa vuelve a mostrarse sin resetear en un efecto.
  const [previewLogoFallido, setPreviewLogoFallido] = useState<string | null>(null)
  const previewLogoError = logoPreviewUrl !== null && previewLogoFallido === logoPreviewUrl

  // Al cambiar la empresa activa se restablece el formulario de identidad durante el render
  // (patrón "ajustar estado cuando cambia una prop" de React), sin un efecto que encadene renders.
  const [identidadDeEmpresa, setIdentidadDeEmpresa] = useState(empresaActiva)
  if (identidadDeEmpresa !== empresaActiva) {
    setIdentidadDeEmpresa(empresaActiva)
    setIdentidadColor(empresaActiva?.color_tema ?? null)
    setIdentidadLogoPreview(empresaActiva?.logo || null)
    setIdentidadLogoFile(null)
    setQuitarLogoPendiente(false)
    setColorSugeridoExtraido(null)
    setPreviewLogoFallido(null)
  }

  const tokensPreview = React.useMemo(() => {
    return generarThemingSidebar(identidadColor)
  }, [identidadColor])

  const handleLogoSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 2 * 1024 * 1024) {
      setError('El archivo seleccionado no debe exceder 2 MB.')
      return
    }
    setProcesandoLogo(true)
    setError('')
    try {
      const { archivoWebp, colorDominante, previewUrl } = await procesarImagenLogo(file)
      setIdentidadLogoFile(archivoWebp)
      setIdentidadLogoPreview(previewUrl)
      setQuitarLogoPendiente(false)
      if (colorDominante) {
        setColorSugeridoExtraido(colorDominante)
        if (!empresaActiva?.color_tema || empresaActiva.color_tema === '#4F46E5') {
          setIdentidadColor(colorDominante)
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error al procesar la imagen del logo.')
    } finally {
      setProcesandoLogo(false)
    }
  }

  const handleQuitarLogo = () => {
    setIdentidadLogoFile(null)
    setIdentidadLogoPreview(null)
    setQuitarLogoPendiente(true)
    setColorSugeridoExtraido(null)
  }

  const guardarIdentidad = (event: FormEvent) => {
    event.preventDefault()
    if (!empresaActiva) return
    if (identidadColor && !esHexValido(identidadColor)) {
      setError('El color de tema debe ser un formato hexadecimal válido (ej. #4F46E5).')
      return
    }
    void ejecutar(async () => {
      const res = await actualizarIdentidadEmpresaApi(empresaActiva.id, {
        color_tema: identidadColor ? identidadColor : null,
        logo: quitarLogoPendiente ? null : identidadLogoFile,
        quitar_logo: quitarLogoPendiente,
      })
      actualizarIdentidadEmpresa?.(empresaActiva.id, {
        logo: res.logo,
        color_tema: res.color_tema,
      })
      setIdentidadLogoFile(null)
      setQuitarLogoPendiente(false)
      setIdentidadLogoPreview(res.logo || null)
    }, 'Identidad visual actualizada exitosamente.')
  }

  const cargarDatosEmpresa = useCallback(async () => {
    if (!empresaActiva) {
      setEstablecimientos([])
      setConfig(null)
      return
    }
    const [lista, configuracion] = await Promise.all([obtenerEstablecimientos(), obtenerConfigEmpresa()])
    setEstablecimientos(lista)
    setConfig(configuracion)
    setConfigForm({
      tolerancia_residuo_pen: configuracion.tolerancia_residuo_pen,
      decimales_calculo: configuracion.decimales_calculo,
      establecimiento_principal: configuracion.establecimiento_principal?.toString() ?? '',
    })
  }, [empresaActiva])

  useEffect(() => {
    const cargar = async () => {
      setLoading(true)
      setError('')
      try {
        const [, listaMonedas] = await Promise.all([refrescarEmpresasDisponibles(), obtenerMonedas()])
        setMonedas(listaMonedas)
      } catch (err) {
        setError(mensajeError(err))
      } finally {
        setLoading(false)
      }
    }
    void cargar()
  }, [refrescarEmpresasDisponibles])

  useEffect(() => {
    const cargar = async () => {
      if (!empresaActiva) {
        setEstablecimientos([])
        setConfig(null)
        return
      }
      setError('')
      try {
        await cargarDatosEmpresa()
      } catch (err) {
        setError(mensajeError(err))
      }
    }
    diferirCarga(cargar)
  }, [cargarDatosEmpresa, empresaActiva])

  const ejecutar = async (accion: () => Promise<void>, mensaje: string) => {
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      await accion()
      setSuccess(mensaje)
    } catch (err) {
      setError(mensajeError(err))
    } finally {
      setSaving(false)
    }
  }

  const guardarEmpresa = (event: FormEvent) => {
    event.preventDefault()
    void ejecutar(async () => {
      const nueva = await crearEmpresa(empresaForm)
      registrarEmpresaDisponible(nueva)
      setEmpresaForm({ ruc: '', razon_social: '', nombre_comercial: '', direccion: '', moneda_base_codigo: 'PEN' })
      setMostrarEmpresa(false)
    }, 'Empresa creada y configurada correctamente.')
  }

  const guardarEstablecimiento = (event: FormEvent) => {
    event.preventDefault()
    void ejecutar(async () => {
      const payload = {
        ...establecimientoForm,
        direccion: establecimientoForm.direccion.trim() || null,
        ubigeo: establecimientoForm.ubigeo.trim() || null,
      }
      if (editando) await actualizarEstablecimiento(editando, payload)
      else await crearEstablecimiento(payload)
      setEstablecimientoForm(ESTABLECIMIENTO_INICIAL)
      setEditando(null)
      setEstablecimientos(await obtenerEstablecimientos())
    }, editando ? 'Establecimiento actualizado.' : 'Establecimiento creado.')
  }

  const guardarConfig = (event: FormEvent) => {
    event.preventDefault()
    void ejecutar(async () => {
      const actualizada = await actualizarConfigEmpresa({
        tolerancia_residuo_pen: configForm.tolerancia_residuo_pen,
        decimales_calculo: configForm.decimales_calculo,
        establecimiento_principal: configForm.establecimiento_principal ? Number(configForm.establecimiento_principal) : null,
      })
      setConfig(actualizada)
    }, 'Configuración contable actualizada exitosamente.')
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-400 text-sm">
        Cargando empresas y configuración…
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Empresas y Configuración"
        description="Administra organizaciones multi-tenant, establecimientos anexos SUNAT y parámetros de motor contable."
        icon={<Building2 className="h-5 w-5" />}
        actions={
          <Button
            variant={mostrarEmpresa ? 'secondary' : 'primary'}
            onClick={() => setMostrarEmpresa((v) => !v)}
          >
            {mostrarEmpresa ? (
              <>
                <X className="h-4 w-4 mr-1.5" /> Cancelar
              </>
            ) : (
              <>
                <Plus className="h-4 w-4 mr-1.5" /> Nueva Empresa
              </>
            )}
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

      {success && (
        <div
          role="status"
          className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50/90 p-3.5 text-xs text-emerald-700 animate-in fade-in"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{success}</span>
        </div>
      )}

      {mostrarEmpresa && (
        <Card className="border-indigo-200/80 shadow-md">
          <CardHeader>
            <CardTitle>Registrar Nueva Empresa</CardTitle>
            <CardDescription>Crea una nueva organización con aislamiento estricto en base de datos.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={guardarEmpresa} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div className="space-y-1.5">
                  <Label required>RUC (11 dígitos)</Label>
                  <Input
                    required
                    minLength={11}
                    maxLength={11}
                    className="font-mono tabular-nums"
                    placeholder="20100000001"
                    value={empresaForm.ruc}
                    onChange={(e) => setEmpresaForm({ ...empresaForm, ruc: e.target.value })}
                  />
                  {/* Bloque 17C: ayuda opcional, solo para ADMIN de la empresa activa (lo que exige el
                      endpoint); sin ese permiso el registro es manual, como siempre. */}
                  {puedeConsultarRuc(empresaActiva, usuario?.es_admin_global) && (
                    <ConsultaRucBoton ruc={empresaForm.ruc} formulario={empresaForm} campos={MAPA_EMPRESA_NUEVA} onAplicar={setEmpresaForm} />
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label required>Razón Social</Label>
                  <Input
                    required
                    placeholder="EMPRESA MODELO S.A.C."
                    value={empresaForm.razon_social}
                    onChange={(e) => setEmpresaForm({ ...empresaForm, razon_social: e.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Nombre Comercial</Label>
                  <Input
                    placeholder="NOMBRE COMERCIAL"
                    value={empresaForm.nombre_comercial}
                    onChange={(e) => setEmpresaForm({ ...empresaForm, nombre_comercial: e.target.value })}
                  />
                </div>
                <div className="space-y-1.5 md:col-span-2">
                  <Label>Dirección Fiscal</Label>
                  <Input
                    placeholder="AV. EJEMPLO 123, LIMA"
                    value={empresaForm.direccion}
                    onChange={(e) => setEmpresaForm({ ...empresaForm, direccion: e.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Moneda Base</Label>
                  <Select
                    value={empresaForm.moneda_base_codigo}
                    onChange={(e) => setEmpresaForm({ ...empresaForm, moneda_base_codigo: e.target.value })}
                  >
                    {monedas.map((m) => (
                      <option key={m.codigo} value={m.codigo}>
                        {m.codigo} — {m.nombre}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>
              <div className="flex justify-end pt-2">
                <Button type="submit" variant="primary" isLoading={saving}>
                  <Save className="h-4 w-4 mr-1.5" /> Registrar Empresa
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Tabs Layout */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="empresas" icon={<Building2 className="h-3.5 w-3.5" />}>
            Empresas Asignadas ({empresasDisponibles.length})
          </TabsTrigger>
          <TabsTrigger value="establecimientos" icon={<MapPin className="h-3.5 w-3.5" />}>
            Establecimientos SUNAT ({establecimientos.length})
          </TabsTrigger>
          <TabsTrigger value="fiscal" icon={<FileBadge className="h-3.5 w-3.5" />}>
            Datos fiscales
          </TabsTrigger>
          <TabsTrigger value="series" icon={<Hash className="h-3.5 w-3.5" />}>
            Series de comprobantes
          </TabsTrigger>
          <TabsTrigger value="configuracion" icon={<Sliders className="h-3.5 w-3.5" />}>
            Parámetros del Motor (ConfigEmpresa)
          </TabsTrigger>
          <TabsTrigger value="identidad" icon={<Palette className="h-3.5 w-3.5" />}>
            Identidad visual
          </TabsTrigger>
        </TabsList>

        {/* TAB 1: EMPRESAS ASIGNADAS */}
        <TabsContent value="empresas" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Empresas Asignadas</CardTitle>
              <CardDescription>
                Empresas a las que tu usuario tiene acceso mediante <code className="font-mono text-slate-700">usuario_empresa</code>.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {empresasDisponibles.length === 0 ? (
                <p className="text-xs text-slate-500 py-4">No tienes empresas asignadas.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>RUC</TableHead>
                      <TableHead>Razón Social</TableHead>
                      <TableHead>Rol Asignado</TableHead>
                      <TableHead>Estado</TableHead>
                      <TableHead className="text-right">Acción</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {empresasDisponibles.map((e) => {
                      const esActiva = empresaActiva?.id === e.id
                      return (
                        <TableRow key={e.id} className={esActiva ? 'bg-indigo-50/40' : undefined}>
                          <TableCell numeric className="font-semibold text-slate-900">{e.ruc}</TableCell>
                          <TableCell className="font-medium text-slate-900">{e.razon_social}</TableCell>
                          <TableCell>
                            <Badge variant={e.rol === 'ADMIN' ? 'info' : 'neutral'}>{e.rol}</Badge>
                          </TableCell>
                          <TableCell>
                            <Badge variant="success" dot>ACTIVA</Badge>
                          </TableCell>
                          <TableCell className="text-right">
                            <Button
                              type="button"
                              size="sm"
                              variant={esActiva ? 'secondary' : 'outline'}
                              disabled={esActiva}
                              onClick={() => seleccionarEmpresa(e.id)}
                            >
                              {esActiva ? (
                                <>
                                  <Check className="h-3.5 w-3.5 mr-1 text-emerald-600" /> Activa
                                </>
                              ) : (
                                'Seleccionar'
                              )}
                            </Button>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 2: ESTABLECIMIENTOS ANEXOS SUNAT */}
        <TabsContent value="establecimientos" className="space-y-6">
          {!empresaActiva ? (
            <div className="p-8 text-center text-sm text-slate-500 rounded-xl border border-slate-200 bg-white">
              Selecciona una empresa activa para administrar sus establecimientos SUNAT.
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Formulario */}
              <Card className="lg:col-span-1">
                <CardHeader>
                  <CardTitle>{editando ? 'Editar Establecimiento' : 'Nuevo Establecimiento SUNAT'}</CardTitle>
                  <CardDescription>Código de 4 dígitos (0000 = Principal).</CardDescription>
                </CardHeader>
                <CardContent>
                  <form onSubmit={guardarEstablecimiento} className="space-y-4">
                    <div className="space-y-1.5">
                      <Label required>Código SUNAT (ej. 0000, 0001)</Label>
                      <Input
                        required
                        maxLength={20}
                        placeholder="0000"
                        className="font-mono tabular-nums"
                        value={establecimientoForm.codigo_sunat}
                        onChange={(e) => setEstablecimientoForm({ ...establecimientoForm, codigo_sunat: e.target.value })}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label required>Nombre del Establecimiento</Label>
                      <Input
                        required
                        maxLength={150}
                        placeholder="OFICINA PRINCIPAL / PLANTA"
                        value={establecimientoForm.nombre}
                        onChange={(e) => setEstablecimientoForm({ ...establecimientoForm, nombre: e.target.value })}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="est-direccion">Dirección</Label>
                      <Input
                        id="est-direccion"
                        maxLength={300}
                        placeholder="Dirección del establecimiento"
                        value={establecimientoForm.direccion}
                        onChange={(e) => setEstablecimientoForm({ ...establecimientoForm, direccion: e.target.value })}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="est-ubigeo">Ubigeo (INEI)</Label>
                      <Input
                        id="est-ubigeo"
                        maxLength={6}
                        placeholder="150101"
                        className="font-mono tabular-nums"
                        value={establecimientoForm.ubigeo}
                        onChange={(e) => setEstablecimientoForm({ ...establecimientoForm, ubigeo: e.target.value })}
                      />
                    </div>
                    <div className="flex items-center gap-2 pt-1">
                      <input
                        type="checkbox"
                        id="est-activo"
                        className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                        checked={establecimientoForm.activo}
                        onChange={(e) => setEstablecimientoForm({ ...establecimientoForm, activo: e.target.checked })}
                      />
                      <Label htmlFor="est-activo" className="cursor-pointer">
                        Establecimiento Activo
                      </Label>
                    </div>
                    <div className="flex gap-2 pt-2">
                      <Button type="submit" variant="primary" isLoading={saving} className="flex-1">
                        {editando ? 'Actualizar' : 'Crear'}
                      </Button>
                      {editando && (
                        <Button
                          type="button"
                          variant="secondary"
                          onClick={() => {
                            setEditando(null)
                            setEstablecimientoForm(ESTABLECIMIENTO_INICIAL)
                          }}
                        >
                          Cancelar
                        </Button>
                      )}
                    </div>
                  </form>
                </CardContent>
              </Card>

              {/* Lista */}
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle>Establecimientos Registrados ({establecimientos.length})</CardTitle>
                  <CardDescription>Puntos de venta y sucursales declaradas ante SUNAT.</CardDescription>
                </CardHeader>
                <CardContent>
                  {establecimientos.length === 0 ? (
                    <p className="text-xs text-slate-500 py-4">Aún no hay establecimientos registrados.</p>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Código SUNAT</TableHead>
                          <TableHead>Nombre</TableHead>
                          <TableHead>Dirección / Ubigeo</TableHead>
                          <TableHead>Estado</TableHead>
                          <TableHead className="text-right">Acción</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {establecimientos.map((e) => (
                          <TableRow key={e.id}>
                            <TableCell numeric className="font-semibold text-slate-900">{e.codigo_sunat}</TableCell>
                            <TableCell className="font-medium text-slate-900">
                              {e.nombre}
                              {e.es_principal && <Badge variant="info" size="xs" className="ml-2">PRINCIPAL</Badge>}
                            </TableCell>
                            <TableCell className="text-xs text-slate-600">
                              <div>{e.direccion || '—'}</div>
                              <div className="font-mono text-slate-400">{e.ubigeo || ''}</div>
                            </TableCell>
                            <TableCell>
                              <Badge variant={e.activo ? 'success' : 'neutral'} dot>
                                {e.activo ? 'ACTIVO' : 'INACTIVO'}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  setEditando(e.id)
                                  setEstablecimientoForm({
                                    codigo_sunat: e.codigo_sunat,
                                    nombre: e.nombre,
                                    activo: e.activo,
                                    direccion: e.direccion ?? '',
                                    ubigeo: e.ubigeo ?? '',
                                  })
                                }}
                              >
                                Editar
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        {/* Bloque 17A: datos fiscales del emisor electrónico */}
        <TabsContent value="fiscal" className="space-y-4">
          {!empresaActiva ? (
            <div className="p-8 text-center text-sm text-slate-500 rounded-xl border border-slate-200 bg-white">
              Selecciona una empresa activa para revisar sus datos fiscales.
            </div>
          ) : (
            <DatosFiscalesPanel key={empresaActiva.id} esAdmin={esAdminActiva} />
          )}
        </TabsContent>

        {/* Bloque 16: series y correlativos de venta */}
        <TabsContent value="series" className="space-y-4">
          {!empresaActiva ? (
            <div className="p-8 text-center text-sm text-slate-500 rounded-xl border border-slate-200 bg-white">
              Selecciona una empresa activa para administrar sus series.
            </div>
          ) : (
            <SeriesComprobantePanel key={empresaActiva.id} establecimientos={establecimientos} esAdmin={esAdminActiva} />
          )}
        </TabsContent>

        {/* TAB 3: PARÁMETROS DEL MOTOR (ConfigEmpresa) */}
        <TabsContent value="configuracion" className="space-y-4">
          {!empresaActiva ? (
            <div className="p-8 text-center text-sm text-slate-500 rounded-xl border border-slate-200 bg-white">
              Selecciona una empresa activa para consultar su configuración contable.
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle>Parámetros de Cálculo Contable y Kardex</CardTitle>
                  <CardDescription>
                    Políticas matemáticas del motor CPP y tolerancia de residuos según R.S. N.° 234-2006.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <form onSubmit={guardarConfig} className="space-y-5">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <Label required>Tolerancia de Residuo PEN</Label>
                        <Input
                          required
                          inputMode="decimal"
                          pattern="^\d+(\.\d{1,8})?$"
                          className="font-mono tabular-nums"
                          value={configForm.tolerancia_residuo_pen}
                          onChange={(e) => setConfigForm({ ...configForm, tolerancia_residuo_pen: e.target.value })}
                        />
                        <p className="text-[10px] text-slate-400">Residuo contable absorbible (máx. S/ 0.05000000).</p>
                      </div>

                      <div className="space-y-1.5">
                        <Label required>Decimales de Cálculo (Operativos)</Label>
                        <Input
                          required
                          type="number"
                          min={2}
                          max={8}
                          className="font-mono tabular-nums"
                          value={configForm.decimales_calculo}
                          onChange={(e) => setConfigForm({ ...configForm, decimales_calculo: Number(e.target.value) })}
                        />
                        <p className="text-[10px] text-slate-400">Estándar nacional: 6 decimales para CPP.</p>
                      </div>

                      <div className="space-y-1.5 sm:col-span-2">
                        <Label>Establecimiento Principal (Receptor de Ajustes de Redondeo)</Label>
                        <Select
                          value={configForm.establecimiento_principal}
                          onChange={(e) => setConfigForm({ ...configForm, establecimiento_principal: e.target.value })}
                        >
                          <option value="">Sin asignar</option>
                          {establecimientos.map((e) => (
                            <option key={e.id} value={e.id}>
                              {e.codigo_sunat} — {e.nombre}
                            </option>
                          ))}
                        </Select>
                      </div>
                    </div>

                    <div className="flex justify-end pt-2">
                      <Button type="submit" variant="primary" isLoading={saving}>
                        <Save className="h-4 w-4 mr-1.5" /> Guardar Configuración
                      </Button>
                    </div>
                  </form>
                </CardContent>
              </Card>

              {/* Panel de Políticas Inmutables */}
              <Card className="lg:col-span-1 bg-slate-50/50">
                <CardHeader>
                  <CardTitle className="text-sm">Reglas Inmutables del Motor</CardTitle>
                  <CardDescription>Políticas fijas impuestas por la normativa fiscal.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3.5">
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white border border-slate-200">
                    <span className="text-xs text-slate-600">Método de Valuación:</span>
                    <Badge variant="info" className="font-mono">{config?.metodo_valuacion ?? 'CPP'}</Badge>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white border border-slate-200">
                    <span className="text-xs text-slate-600">Regla de Redondeo:</span>
                    <Badge variant="neutral" className="font-mono">{config?.regla_redondeo ?? 'ROUND_HALF_UP'}</Badge>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white border border-slate-200">
                    <span className="text-xs text-slate-600">Almacenamiento en BD:</span>
                    <Badge variant="neutral" className="font-mono">8 DECIMALES</Badge>
                  </div>
                  <div className="flex items-center justify-between p-2.5 rounded-lg bg-white border border-slate-200">
                    <span className="text-xs text-slate-600">Triggers de Modificación:</span>
                    <Badge variant="success" dot>ACTIVOS</Badge>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        {/* TAB 6: IDENTIDAD VISUAL MULTIEMPRESA */}
        <TabsContent value="identidad" className="space-y-6">
          {!empresaActiva ? (
            <div className="flex items-center justify-center p-12 text-slate-400 text-sm">
              Selecciona una empresa para gestionar su identidad visual.
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* Formulario de Configuración (7 cols) */}
              <div className="lg:col-span-7 space-y-6">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Palette className="h-5 w-5 text-indigo-600" />
                      Identidad Periférica de Marca
                    </CardTitle>
                    <CardDescription>
                      Personaliza el logo y los colores de navegación de{' '}
                      <span className="font-semibold text-slate-800">{empresaActiva.razon_social}</span>.
                      Las áreas contables (comprobantes, Kardex y reportes SUNAT) se mantienen neutras por normativa.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <form onSubmit={guardarIdentidad} className="space-y-6">
                      {/* Sección 1: Logo */}
                      <div className="space-y-3">
                        <Label className="text-xs font-bold uppercase tracking-wider text-slate-600">
                          Logo de la Empresa
                        </Label>
                        <div className="flex flex-col sm:flex-row items-center gap-4 p-4 rounded-xl border border-slate-200/80 bg-slate-50/50">
                          <div className="relative flex h-20 w-20 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white p-2 shadow-2xs overflow-hidden">
                            {logoPreviewUrl && !previewLogoError ? (
                              <img
                                src={logoPreviewUrl}
                                alt="Logo Empresa"
                                onError={() => setPreviewLogoFallido(logoPreviewUrl)}
                                className="h-full w-full object-contain"
                              />
                            ) : (
                              <div
                                className="flex h-full w-full items-center justify-center rounded-lg text-white font-bold text-lg shadow-2xs select-none"
                                style={{ backgroundColor: tokensPreview ? tokensPreview['--tenant-sidebar-accent'] : '#4F46E5' }}
                              >
                                {obtenerInicialesEmpresa(empresaActiva.razon_social)}
                              </div>
                            )}
                          </div>

                          <div className="flex-1 space-y-2 text-center sm:text-left">
                            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2">
                              <label
                                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-colors shadow-2xs ${
                                  esAdminActiva && !procesandoLogo
                                    ? 'bg-indigo-600 text-white hover:bg-indigo-700'
                                    : 'bg-slate-200 text-slate-400 cursor-not-allowed'
                                }`}
                              >
                                <UploadCloud className="h-4 w-4" />
                                {procesandoLogo ? 'Optimizando...' : 'Subir nuevo logo'}
                                <input
                                  type="file"
                                  accept="image/png,image/jpeg,image/webp"
                                  className="hidden"
                                  disabled={!esAdminActiva || procesandoLogo}
                                  onChange={handleLogoSelect}
                                />
                              </label>

                              {(identidadLogoPreview || identidadLogoFile) && esAdminActiva && (
                                <Button
                                  type="button"
                                  variant="secondary"
                                  size="sm"
                                  className="text-xs text-rose-600 hover:text-rose-700 hover:bg-rose-50"
                                  onClick={handleQuitarLogo}
                                >
                                  <Trash2 className="h-3.5 w-3.5 mr-1" />
                                  Quitar logo
                                </Button>
                              )}
                            </div>
                            <p className="text-[11px] text-slate-500 leading-relaxed">
                              PNG, JPG o WebP (máx. 512 KB). Se optimiza automáticamente en el cliente a WebP 256×256 con protección binaria anti-spoofing en el servidor.
                            </p>
                            {colorSugeridoExtraido && (
                              <div className="flex items-center gap-2 pt-1 text-xs text-slate-700">
                                <Sparkles className="h-3.5 w-3.5 text-amber-500" />
                                <span>Color dominante extraído:</span>
                                <span
                                  className="inline-block h-3.5 w-3.5 rounded-full border border-slate-300 shadow-2xs"
                                  style={{ backgroundColor: colorSugeridoExtraido }}
                                />
                                <code className="font-mono font-semibold text-[11px]">{colorSugeridoExtraido}</code>
                                <button
                                  type="button"
                                  onClick={() => setIdentidadColor(colorSugeridoExtraido)}
                                  className="text-[11px] font-medium text-indigo-600 hover:underline cursor-pointer ml-1"
                                >
                                  Aplicar
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Sección 2: Color de Tema y Paletas */}
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <Label className="text-xs font-bold uppercase tracking-wider text-slate-600">
                            Tema de Navegación del Sidebar
                          </Label>
                          <span className="text-[11px] text-slate-500 font-mono">
                            {identidadColor ? identidadColor.toUpperCase() : 'BLANCO (ESTÁNDAR)'}
                          </span>
                        </div>

                        {/* Presets Ejecutivos + Predeterminado Blanco */}
                        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                          {/* Opción 1: Predeterminado Blanco */}
                          <button
                            type="button"
                            onClick={() => setIdentidadColor(null)}
                            disabled={!esAdminActiva}
                            className={`flex items-center gap-2 p-2 rounded-lg border text-left text-xs transition-all cursor-pointer ${
                              identidadColor === null || identidadColor === ''
                                ? 'border-indigo-600 bg-indigo-50/60 font-semibold text-slate-900 ring-2 ring-indigo-500/20'
                                : 'border-slate-200/80 bg-white hover:border-slate-300 text-slate-700'
                            }`}
                          >
                            <span className="h-4 w-4 shrink-0 rounded-full border border-slate-300 bg-white shadow-2xs flex items-center justify-center">
                              {(identidadColor === null || identidadColor === '') && (
                                <Check className="h-2.5 w-2.5 text-indigo-600" strokeWidth={3} />
                              )}
                            </span>
                            <span className="truncate text-[11px]">Predeterminado (Blanco)</span>
                          </button>

                          {/* 9 Paletas Ejecutivas */}
                          {PALETAS_EJECUTIVAS.map((p) => {
                            const isSelected = identidadColor?.toUpperCase() === p.hex.toUpperCase()
                            return (
                              <button
                                key={p.hex}
                                type="button"
                                onClick={() => setIdentidadColor(p.hex)}
                                disabled={!esAdminActiva}
                                className={`flex items-center gap-2 p-2 rounded-lg border text-left text-xs transition-all cursor-pointer ${
                                  isSelected
                                    ? 'border-indigo-600 bg-indigo-50/50 font-semibold text-slate-900 ring-2 ring-indigo-500/20'
                                    : 'border-slate-200/80 bg-white hover:border-slate-300 text-slate-700'
                                }`}
                              >
                                <span
                                  className="h-4 w-4 shrink-0 rounded-full border border-black/10 shadow-2xs flex items-center justify-center"
                                  style={{ backgroundColor: p.hex }}
                                >
                                  {isSelected && <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />}
                                </span>
                                <span className="truncate text-[11px]">{p.nombre}</span>
                              </button>
                            )
                          })}
                        </div>

                        {/* Selector Manual */}
                        <div className="flex items-center gap-3 pt-2">
                          <div className="relative">
                            <input
                              type="color"
                              value={identidadColor || '#4F46E5'}
                              disabled={!esAdminActiva}
                              onChange={(e) => setIdentidadColor(e.target.value.toUpperCase())}
                              className="h-9 w-12 cursor-pointer rounded-lg border border-slate-200 bg-white p-0.5 shadow-2xs"
                              title="Seleccionar color personalizado"
                            />
                          </div>
                          <div className="flex-1">
                            <Input
                              value={identidadColor || ''}
                              disabled={!esAdminActiva}
                              placeholder="Color hex (#RRGGBB) o blanco por defecto"
                              className="font-mono uppercase text-xs"
                              onChange={(e) => {
                                const val = e.target.value.trim()
                                setIdentidadColor(val ? val.toUpperCase() : null)
                              }}
                            />
                          </div>
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            disabled={!esAdminActiva}
                            onClick={() => setIdentidadColor(null)}
                            className="text-xs"
                            title="Restablecer al diseño blanco por defecto"
                          >
                            Restablecer a Blanco
                          </Button>
                        </div>
                      </div>

                      {/* Botón Guardar */}
                      <div className="flex items-center justify-between pt-4 border-t border-slate-200/80">
                        <span className="text-xs text-slate-500">
                          {!esAdminActiva
                            ? 'Solo administradores pueden guardar cambios de identidad.'
                            : 'Los cambios se reflejarán instantáneamente en la interfaz.'}
                        </span>
                        <Button
                          type="submit"
                          variant="primary"
                          isLoading={saving || procesandoLogo}
                          disabled={!esAdminActiva}
                        >
                          <Save className="h-4 w-4 mr-1.5" /> Guardar Identidad Visual
                        </Button>
                      </div>
                    </form>
                  </CardContent>
                </Card>
              </div>

              {/* Previsualización en Vivo de la Periferia (5 cols) */}
              <div className="lg:col-span-5 space-y-4">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Eye className="h-4 w-4 text-slate-500" />
                      Previsualización en Vivo (Sidebar)
                    </CardTitle>
                    <CardDescription>
                      Simulación en tiempo real del menú lateral con contrastes WCAG 2.1 calculados.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Mock Sidebar Container */}
                    {tokensPreview ? (
                      <div
                        className="rounded-xl border shadow-md p-3.5 space-y-4 transition-all duration-300 relative overflow-hidden"
                        style={{
                          backgroundColor: tokensPreview['--tenant-sidebar-bg'],
                          backgroundImage: tokensPreview['--tenant-sidebar-mesh-bg'],
                          borderColor: tokensPreview['--tenant-sidebar-border'],
                          color: tokensPreview['--tenant-sidebar-text'],
                        }}
                      >
                        {/* Mock Header - Emblema Corporativo Vertical */}
                        <div
                          className="flex flex-col items-center text-center gap-2 pb-3.5 border-b"
                          style={{ borderColor: tokensPreview['--tenant-sidebar-border'] }}
                        >
                          {logoPreviewUrl && !previewLogoError ? (
                            <div className="flex items-center justify-center w-full min-h-[44px] max-h-12 px-1">
                              <img
                                src={logoPreviewUrl}
                                alt="Logo preview"
                                onError={() => setPreviewLogoFallido(logoPreviewUrl)}
                                style={{
                                  filter: obtenerFiltroLogo(true),
                                }}
                                className="max-h-11 max-w-[190px] w-auto h-auto object-contain transition-all duration-200"
                              />
                            </div>
                          ) : (
                            <div
                              className="flex h-11 w-11 items-center justify-center rounded-xl text-white font-bold text-sm shadow-xs select-none shrink-0"
                              style={{ backgroundColor: tokensPreview['--tenant-sidebar-accent'] }}
                            >
                              {obtenerInicialesEmpresa(empresaActiva.razon_social)}
                            </div>
                          )}
                          <div className="flex flex-col items-center w-full min-w-0 space-y-0.5">
                            <span
                              className="text-[13px] font-bold leading-snug line-clamp-2 px-1 text-center"
                              style={{ color: tokensPreview['--tenant-sidebar-text'] }}
                            >
                              {empresaActiva.razon_social}
                            </span>
                            <span
                              className="text-[11px] font-mono font-medium tabular-nums tracking-tight leading-tight text-center"
                              style={{ color: tokensPreview['--tenant-sidebar-text-muted'] }}
                            >
                              RUC {empresaActiva.ruc}
                            </span>
                          </div>
                        </div>

                        {/* Mock Nav Group */}
                        <div className="space-y-1.5 relative z-10">
                          <span
                            className="text-[10.5px] font-bold tracking-wider uppercase block px-2"
                            style={{ color: tokensPreview['--tenant-sidebar-text-muted'] }}
                          >
                            OPERACIONES
                          </span>

                          {/* Active Item */}
                          <div
                            className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-semibold shadow-2xs relative border before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-1 before:rounded-r transition-colors duration-150"
                            style={{
                              backgroundColor: 'rgba(255, 255, 255, 0.08)',
                              backdropFilter: 'blur(8px)',
                              WebkitBackdropFilter: 'blur(8px)',
                              borderColor: 'rgba(255, 255, 255, 0.14)',
                              boxShadow: 'inset 0 1px 0 0 rgba(255, 255, 255, 0.12)',
                              color: tokensPreview['--tenant-sidebar-text'],
                            }}
                          >
                            <span
                              className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r"
                              style={{ backgroundColor: tokensPreview['--tenant-sidebar-accent'] }}
                            />
                            <Building2 className="h-4 w-4 shrink-0" />
                            <span>Empresas y Configuración</span>
                          </div>

                          {/* Inactive Items */}
                          <div
                            className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium"
                            style={{ color: tokensPreview['--tenant-sidebar-text-muted'] }}
                          >
                            <MapPin className="h-4 w-4 shrink-0" />
                            <span>Establecimientos</span>
                          </div>
                          <div
                            className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium"
                            style={{ color: tokensPreview['--tenant-sidebar-text-muted'] }}
                          >
                            <Sliders className="h-4 w-4 shrink-0" />
                            <span>Parámetros Contables</span>
                          </div>
                        </div>

                        {/* Mock Footer */}
                        <div
                          className="flex items-center gap-2.5 rounded-lg p-2 border transition-colors duration-150 relative z-10"
                          style={{
                            backgroundColor: 'rgba(255, 255, 255, 0.06)',
                            backdropFilter: 'blur(8px)',
                            WebkitBackdropFilter: 'blur(8px)',
                            borderColor: 'rgba(255, 255, 255, 0.10)',
                          }}
                        >
                          <div
                            className="flex h-7 w-7 items-center justify-center rounded-full text-white font-semibold text-xs shadow-2xs select-none shrink-0"
                            style={{ backgroundColor: tokensPreview['--tenant-sidebar-accent'] }}
                          >
                            {usuario?.username?.charAt(0).toUpperCase() || 'U'}
                          </div>
                          <div className="flex flex-col min-w-0 leading-tight">
                            <span
                              className="text-xs font-semibold truncate"
                              style={{ color: tokensPreview['--tenant-sidebar-text'] }}
                            >
                              {usuario?.username || 'Usuario'}
                            </span>
                            <span
                              className="text-[10px] font-medium mt-0.5"
                              style={{ color: tokensPreview['--tenant-sidebar-text-muted'] }}
                            >
                              {esAdminActiva ? 'Administrador' : 'Operador'}
                            </span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      /* Classic White Mock Sidebar */
                      <div className="rounded-xl border border-slate-200 bg-white shadow-md p-3.5 space-y-4 transition-colors duration-300">
                        {/* Mock Header - Emblema Corporativo Vertical */}
                        <div className="flex flex-col items-center text-center gap-2 pb-3.5 border-b border-slate-100">
                          {logoPreviewUrl && !previewLogoError ? (
                            <div className="flex items-center justify-center w-full min-h-[44px] max-h-12 px-1">
                              <img
                                src={logoPreviewUrl}
                                alt="Logo preview"
                                onError={() => setPreviewLogoFallido(logoPreviewUrl)}
                                style={{
                                  filter: obtenerFiltroLogo(false),
                                }}
                                className="max-h-11 max-w-[190px] w-auto h-auto object-contain transition-all duration-200"
                              />
                            </div>
                          ) : (
                            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-600 text-white font-bold text-sm shadow-xs select-none shrink-0">
                              {obtenerInicialesEmpresa(empresaActiva.razon_social)}
                            </div>
                          )}
                          <div className="flex flex-col items-center w-full min-w-0 space-y-0.5">
                            <span className="text-[13px] font-bold leading-snug line-clamp-2 px-1 text-center text-slate-900">
                              {empresaActiva.razon_social}
                            </span>
                            <span className="text-[11px] font-mono font-medium tabular-nums tracking-tight leading-tight text-center text-slate-500">
                              RUC {empresaActiva.ruc}
                            </span>
                          </div>
                        </div>

                        {/* Mock Nav Group */}
                        <div className="space-y-1.5">
                          <span className="text-[10.5px] font-bold tracking-wider uppercase block px-2 text-slate-400">
                            OPERACIONES
                          </span>

                          {/* Active Item */}
                          <div className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-semibold shadow-2xs border bg-indigo-50 border-indigo-100/70 text-indigo-700">
                            <Building2 className="h-4 w-4 shrink-0 text-indigo-600" />
                            <span>Empresas y Configuración</span>
                          </div>

                          {/* Inactive Items */}
                          <div className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-slate-600 hover:text-slate-900">
                            <MapPin className="h-4 w-4 shrink-0" />
                            <span>Establecimientos</span>
                          </div>
                          <div className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-slate-600 hover:text-slate-900">
                            <Sliders className="h-4 w-4 shrink-0" />
                            <span>Parámetros Contables</span>
                          </div>
                        </div>

                        {/* Mock Footer */}
                        <div className="flex items-center gap-2.5 rounded-lg p-2 border border-slate-200/80 bg-slate-50/50">
                          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-indigo-50 border border-indigo-100/80 text-indigo-700 font-semibold text-xs shadow-2xs select-none shrink-0">
                            {usuario?.username?.charAt(0).toUpperCase() || 'U'}
                          </div>
                          <div className="flex flex-col min-w-0 leading-tight">
                            <span className="text-xs font-semibold truncate text-slate-800">
                              {usuario?.username || 'Usuario'}
                            </span>
                            <span className="text-[10px] font-medium mt-0.5 text-slate-500">
                              {esAdminActiva ? 'Administrador' : 'Operador'}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* WCAG Compliance Badge / Predeterminado Badge */}
                    {tokensPreview ? (
                      <div className="rounded-lg border border-emerald-200/80 bg-emerald-50/70 p-3 space-y-2 text-xs text-emerald-800">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 font-bold text-emerald-900">
                            <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                            <span>Garantía de Contraste WCAG 2.1 (AAA / AA)</span>
                          </div>
                          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-900 border border-emerald-300">
                            ✨ Gradient Mesh
                          </span>
                        </div>
                        <p className="text-[11px] leading-relaxed text-emerald-700">
                          Fondo profundo con malla de gradientes radiales continuos (Gradient Mesh) y contraste certificado &gt;= 7.0:1.
                        </p>
                        <div className="grid grid-cols-2 gap-2 pt-1 text-[10px] font-mono">
                          <div className="rounded bg-white/80 p-1.5 border border-emerald-200">
                            <span className="text-slate-500 block">Fondo Sólido:</span>
                            <span className="font-bold text-slate-800">{tokensPreview['--tenant-sidebar-bg']}</span>
                          </div>
                          <div className="rounded bg-white/80 p-1.5 border border-emerald-200">
                            <span className="text-slate-500 block">Acento Marca:</span>
                            <span className="font-bold text-slate-800">{tokensPreview['--tenant-sidebar-accent']}</span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="rounded-lg border border-slate-200 bg-slate-50/80 p-3 space-y-2 text-xs text-slate-700">
                        <div className="flex items-center gap-1.5 font-bold text-slate-900">
                          <CheckCircle2 className="h-4 w-4 text-indigo-600 shrink-0" />
                          <span>Diseño Predeterminado (Blanco Neutro)</span>
                        </div>
                        <p className="text-[11px] leading-relaxed text-slate-600">
                          El menú lateral se visualiza con el fondo blanco estándar de FACT-KARD, garantizando máxima claridad visual y preservando el logo corporativo.
                        </p>
                        <div className="grid grid-cols-2 gap-2 pt-1 text-[10px] font-mono">
                          <div className="rounded bg-white p-1.5 border border-slate-200">
                            <span className="text-slate-500 block">Fondo Sidebar:</span>
                            <span className="font-bold text-slate-800">#FFFFFF (Blanco)</span>
                          </div>
                          <div className="rounded bg-white p-1.5 border border-slate-200">
                            <span className="text-slate-500 block">Superficie Activa:</span>
                            <span className="font-bold text-indigo-700">#EEF2FF (Índigo Claro)</span>
                          </div>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default EmpresasPage
