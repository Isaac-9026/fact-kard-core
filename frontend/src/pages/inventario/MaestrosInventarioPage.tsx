import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import axios from 'axios'
import { Link } from 'react-router-dom'
import {
  Package,
  Boxes,
  Users,
  Warehouse,
  Plus,
  Search,
  CheckCircle2,
  AlertCircle,
  Pencil,
  Layers,
  X,
  Building2,
  Save,
  History,
} from 'lucide-react'
import { HistorialTerceroModal } from '../../components/finanzas/HistorialTerceroModal'
import { ConsultaRucBoton } from '../../components/consultaRuc/ConsultaRucBoton'
import { MAPA_TERCERO } from '../../utils/consultaRuc'
import { TIPOS_DOCUMENTO_IDENTIDAD, errorDocumentoIdentidad } from '../../utils/finanzas'
import { AFECTACIONES_IGV } from '../../utils/afectacionIgv'
import { formatearDecimal } from '../../utils/decimal'

import {
  createAlmacen,
  createProducto,
  createProductoUnidad,
  createTercero,
  getAlmacenes,
  getProductos,
  getProductoUnidades,
  getTerceros,
  getTiposExistencia,
  getUnidadesMedida,
  updateAlmacen,
  updateProducto,
  updateProductoUnidad,
  updateTercero,
  type Almacen,
  type EstadoMaestro,
  type FiltroTercero,
  type Producto,
  type ProductoUnidad,
  type Tercero,
  type TipoExistencia,
  type UnidadMedida,
} from '../../api/inventario'
import {
  obtenerEstablecimientos,
  type Establecimiento,
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
import { Modal } from '../../components/ui/modal'
import { diferirCarga } from '../../utils/efectos'

export type TabMaestros = 'productos' | 'terceros' | 'almacenes'
type TabId = TabMaestros

// Navegación por flujo: cada maestro tiene su opción de menú y reutiliza esta pantalla.
const TITULOS_VISTA: Record<TabId, { titulo: string; descripcion: string }> = {
  productos: { titulo: 'Productos y Unidades', descripcion: 'Catálogo de existencias y conversiones de unidades' },
  almacenes: { titulo: 'Almacenes', descripcion: 'Almacenes por establecimiento' },
  terceros: { titulo: 'Terceros', descripcion: 'Clientes y proveedores' },
}

const PRODUCTO_INICIAL = {
  codigo_interno: '',
  descripcion: '',
  tipo_existencia_codigo: '',
  unidad_base_codigo: '',
  estado: 'ACTIVO' as EstadoMaestro,
  // Bloque 16: sugerencias comerciales (no afectan costo, CPP ni Kardex).
  precio_venta_sugerido: '',
  afectacion_igv_defecto: '',
}

/** Campos comerciales del producto para la API ('' se envía como null). */
const comercialProducto = (f: typeof PRODUCTO_INICIAL) => ({
  precio_venta_sugerido: f.precio_venta_sugerido.trim() || null,
  afectacion_igv_defecto: f.afectacion_igv_defecto || null,
})

const etiquetaTipoDocumento = (codigo: string) =>
  TIPOS_DOCUMENTO_IDENTIDAD.find((t) => t.codigo === codigo)?.etiqueta ?? `Tipo ${codigo}`

const TERCERO_INICIAL = {
  tipo_documento: '6',
  numero_documento: '',
  razon_social: '',
  nombre_comercial: '',
  direccion: '',
  telefono: '',
  correo: '',
  es_cliente: true,
  es_proveedor: false,
  estado: 'ACTIVO' as EstadoMaestro,
}

const ALMACEN_INICIAL = {
  establecimiento: '',
  codigo: '',
  nombre: '',
  activo: true,
}

const UNIDAD_INICIAL = {
  unidad_codigo: '',
  factor_a_base: '',
  es_base: false,
}

const extraerError = (error: unknown) => {
  if (!axios.isAxiosError(error)) return 'No se pudo completar la operación.'
  const data = error.response?.data
  if (typeof data === 'string') return data
  if (!data || typeof data !== 'object') return 'No se pudo completar la operación.'

  return Object.entries(data)
    .map(([campo, detalle]) => {
      const texto = Array.isArray(detalle) ? detalle.join(' ') : String(detalle)
      return campo === 'detail' || campo === 'non_field_errors' ? texto : `${campo}: ${texto}`
    })
    .join(' ')
}

export interface MaestrosInventarioPageProps {
  /** Maestro fijo (sin pestañas). Sin valor se muestran las tres pestañas como antes. */
  vista?: TabId
}

export const MaestrosInventarioPage = ({ vista }: MaestrosInventarioPageProps = {}) => {
  const { empresaActiva } = useAuth()
  const esAdmin = empresaActiva?.rol === 'ADMIN'
  const [tab, setTab] = useState<TabId>(vista ?? 'productos')
  const [productos, setProductos] = useState<Producto[]>([])
  const [terceros, setTerceros] = useState<Tercero[]>([])
  const [almacenes, setAlmacenes] = useState<Almacen[]>([])
  const [tiposExistencia, setTiposExistencia] = useState<TipoExistencia[]>([])
  const [unidadesMedida, setUnidadesMedida] = useState<UnidadMedida[]>([])
  const [establecimientos, setEstablecimientos] = useState<Establecimiento[]>([])
  const [loading, setLoading] = useState(false)
  const [catalogosLoading, setCatalogosLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const [productoForm, setProductoForm] = useState(PRODUCTO_INICIAL)
  const [productoEditando, setProductoEditando] = useState<Producto | null>(null)
  const [productoFormVisible, setProductoFormVisible] = useState(false)
  const [productoUnidades, setProductoUnidades] = useState<ProductoUnidad[]>([])
  const [productoUnidadesActivo, setProductoUnidadesActivo] = useState<Producto | null>(null)
  const [unidadForm, setUnidadForm] = useState(UNIDAD_INICIAL)
  const [unidadEditando, setUnidadEditando] = useState<ProductoUnidad | null>(null)
  const [unidadesLoading, setUnidadesLoading] = useState(false)

  const [terceroForm, setTerceroForm] = useState(TERCERO_INICIAL)
  const [terceroEditando, setTerceroEditando] = useState<Tercero | null>(null)
  const [terceroFormVisible, setTerceroFormVisible] = useState(false)
  const [tipoTercero, setTipoTercero] = useState<'todos' | FiltroTercero>('todos')
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')

  const [almacenForm, setAlmacenForm] = useState(ALMACEN_INICIAL)
  const [almacenEditando, setAlmacenEditando] = useState<Almacen | null>(null)
  const [almacenFormVisible, setAlmacenFormVisible] = useState(false)
  const unidadesRequestRef = useRef(0)
  const productoUnidadesActivoIdRef = useRef<number | null>(null)

  const limpiarMensajes = () => {
    setError('')
    setSuccess('')
  }

  const cerrarProductoForm = () => {
    setProductoFormVisible(false)
  }

  const cerrarTerceroForm = () => {
    setTerceroFormVisible(false)
  }

  const cerrarAlmacenForm = () => {
    setAlmacenFormVisible(false)
  }

  const cerrarUnidades = () => {
    unidadesRequestRef.current += 1
    productoUnidadesActivoIdRef.current = null
    setProductoUnidadesActivo(null)
    setProductoUnidades([])
    setUnidadEditando(null)
    setUnidadForm(UNIDAD_INICIAL)
  }

  const cerrarFormularios = useCallback(() => {
    unidadesRequestRef.current += 1
    productoUnidadesActivoIdRef.current = null
    setProductoFormVisible(false)
    setProductoEditando(null)
    setProductoForm(PRODUCTO_INICIAL)
    setProductoUnidadesActivo(null)
    setProductoUnidades([])
    setUnidadEditando(null)
    setUnidadForm(UNIDAD_INICIAL)
    setTerceroFormVisible(false)
    setTerceroFormVisible(false)
    setTerceroEditando(null)
    setTerceroForm(TERCERO_INICIAL)
    setAlmacenFormVisible(false)
    setAlmacenEditando(null)
    setAlmacenForm(ALMACEN_INICIAL)
  }, [])

  const cargarProductos = useCallback(async () => setProductos(await getProductos()), [])
  const cargarTerceros = useCallback(async () => {
    setTerceros(
      await getTerceros({
        tipo: tipoTercero === 'todos' ? undefined : tipoTercero,
        search: search || undefined,
      })
    )
  }, [search, tipoTercero])
  const cargarAlmacenes = useCallback(async () => setAlmacenes(await getAlmacenes()), [])

  // Al cambiar de empresa se vacían los datos de la anterior.
  useEffect(() => {
    diferirCarga(() => {
      cerrarFormularios()
      setProductos([])
      setTerceros([])
      setAlmacenes([])
      setTiposExistencia([])
      setUnidadesMedida([])
      setEstablecimientos([])
      limpiarMensajes()
    })
  }, [cerrarFormularios, empresaActiva?.id])

  useEffect(() => {
    if (!empresaActiva) return
    let ignorar = false
    const cargarCatalogos = async () => {
      setCatalogosLoading(true)
      try {
        const [tipos, unidades, locales] = await Promise.all([
          getTiposExistencia(),
          getUnidadesMedida(),
          obtenerEstablecimientos(),
        ])
        if (!ignorar) {
          setTiposExistencia(tipos)
          setUnidadesMedida(unidades)
          setEstablecimientos(locales)
        }
      } catch (err) {
        if (!ignorar) setError(extraerError(err))
      } finally {
        if (!ignorar) setCatalogosLoading(false)
      }
    }
    void cargarCatalogos()
    return () => {
      ignorar = true
    }
  }, [empresaActiva])

  useEffect(() => {
    if (!empresaActiva) return
    let ignorar = false
    const cargarTab = async () => {
      setLoading(true)
      setError('')
      try {
        if (tab === 'productos') {
          const data = await getProductos()
          if (!ignorar) setProductos(data)
        } else if (tab === 'terceros') {
          const data = await getTerceros({
            tipo: tipoTercero === 'todos' ? undefined : tipoTercero,
            search: search || undefined,
          })
          if (!ignorar) setTerceros(data)
        } else {
          const data = await getAlmacenes()
          if (!ignorar) setAlmacenes(data)
        }
      } catch (err) {
        if (!ignorar) setError(extraerError(err))
      } finally {
        if (!ignorar) setLoading(false)
      }
    }
    void cargarTab()
    return () => {
      ignorar = true
    }
  }, [empresaActiva, search, tab, tipoTercero])

  const ejecutar = async (accion: () => Promise<void>, mensaje: string) => {
    setSaving(true)
    limpiarMensajes()
    try {
      await accion()
      setSuccess(mensaje)
      return true
    } catch (err) {
      setError(extraerError(err))
      return false
    } finally {
      setSaving(false)
    }
  }

  const refrescarDespuesDeGuardar = async (accion: () => Promise<void>) => {
    try {
      await accion()
    } catch {
      setError('El cambio se guardó, pero no se pudo actualizar la lista. Recarga la página para ver el resultado.')
    }
  }

  const abrirNuevo = () => {
    limpiarMensajes()
    if (tab === 'productos') {
      setProductoEditando(null)
      setProductoForm(PRODUCTO_INICIAL)
      setProductoFormVisible(true)
    } else if (tab === 'terceros') {
      setTerceroEditando(null)
      setTerceroForm(TERCERO_INICIAL)
      setTerceroFormVisible(true)
    } else {
      setAlmacenEditando(null)
      setAlmacenForm(ALMACEN_INICIAL)
      setAlmacenFormVisible(true)
    }
  }

  const editarProducto = (producto: Producto) => {
    setProductoEditando(producto)
    setProductoForm({
      codigo_interno: producto.codigo_interno,
      descripcion: producto.descripcion,
      tipo_existencia_codigo: producto.tipo_existencia_codigo,
      unidad_base_codigo: '',
      estado: producto.estado,
      precio_venta_sugerido: producto.precio_venta_sugerido ?? '',
      afectacion_igv_defecto: producto.afectacion_igv_defecto ?? '',
    })
    setProductoFormVisible(true)
  }

  const guardarProducto = (event: FormEvent) => {
    event.preventDefault()
    void (async () => {
      const guardado = await ejecutar(async () => {
        if (productoEditando) {
          await updateProducto(productoEditando.id, {
            codigo_interno: productoForm.codigo_interno,
            descripcion: productoForm.descripcion,
            tipo_existencia_codigo: productoForm.tipo_existencia_codigo,
            estado: productoForm.estado,
            ...comercialProducto(productoForm),
          })
        } else {
          await createProducto({ ...productoForm, ...comercialProducto(productoForm) })
        }
      }, productoEditando ? 'Producto actualizado.' : 'Producto creado con su unidad base.')
      if (!guardado) return
      cerrarProductoForm()
      setProductoEditando(null)
      setProductoForm(PRODUCTO_INICIAL)
      await refrescarDespuesDeGuardar(cargarProductos)
    })()
  }

  const gestionarUnidades = async (producto: Producto) => {
    const requestId = ++unidadesRequestRef.current
    productoUnidadesActivoIdRef.current = producto.id
    setProductoUnidadesActivo(producto)
    setProductoUnidades([])
    setUnidadEditando(null)
    setUnidadForm(UNIDAD_INICIAL)
    setUnidadesLoading(true)
    limpiarMensajes()
    try {
      const unidades = await getProductoUnidades(producto.id)
      if (requestId === unidadesRequestRef.current) setProductoUnidades(unidades)
    } catch (err) {
      if (requestId === unidadesRequestRef.current) setError(extraerError(err))
    } finally {
      if (requestId === unidadesRequestRef.current) setUnidadesLoading(false)
    }
  }

  const editarUnidad = (unidad: ProductoUnidad) => {
    setUnidadEditando(unidad)
    setUnidadForm({
      unidad_codigo: unidad.unidad_codigo,
      factor_a_base: unidad.factor_a_base,
      es_base: unidad.es_base,
    })
  }

  const guardarUnidad = (event: FormEvent) => {
    event.preventDefault()
    if (!productoUnidadesActivo) return
    const productoId = productoUnidadesActivo.id
    const requestId = ++unidadesRequestRef.current
    void (async () => {
      const guardado = await ejecutar(async () => {
        if (unidadEditando) {
          await updateProductoUnidad(productoId, unidadEditando.id, unidadForm)
        } else {
          await createProductoUnidad(productoId, { ...unidadForm, es_base: false })
        }
      }, unidadEditando ? 'Presentación actualizada.' : 'Presentación agregada.')
      if (!guardado) return
      if (productoUnidadesActivoIdRef.current === productoId) {
        setUnidadEditando(null)
        setUnidadForm(UNIDAD_INICIAL)
      }
      await refrescarDespuesDeGuardar(async () => {
        const [unidades] = await Promise.all([getProductoUnidades(productoId), cargarProductos()])
        if (requestId === unidadesRequestRef.current && productoUnidadesActivoIdRef.current === productoId) {
          setProductoUnidades(unidades)
        }
      })
    })()
  }

  const editarTercero = (tercero: Tercero) => {
    setTerceroEditando(tercero)
    setTerceroForm({
      tipo_documento: tercero.tipo_documento,
      numero_documento: tercero.numero_documento,
      razon_social: tercero.razon_social,
      nombre_comercial: tercero.nombre_comercial ?? '',
      direccion: tercero.direccion ?? '',
      telefono: tercero.telefono ?? '',
      correo: tercero.correo ?? '',
      es_cliente: tercero.es_cliente,
      es_proveedor: tercero.es_proveedor,
      estado: tercero.estado,
    })
    setTerceroFormVisible(true)
  }

  const terceroSinRol = !terceroForm.es_cliente && !terceroForm.es_proveedor
  // Bloque 16: catálogo 06 y RUC con dígito verificador (el backend vuelve a validar).
  const errorDocTercero = terceroForm.numero_documento
    ? errorDocumentoIdentidad(terceroForm.tipo_documento, terceroForm.numero_documento)
    : null
  const [historialTercero, setHistorialTercero] = useState<Tercero | null>(null)
  const guardarTercero = (event: FormEvent) => {
    event.preventDefault()
    if (terceroSinRol || errorDocTercero) return
    void (async () => {
      const guardado = await ejecutar(async () => {
        if (terceroEditando) await updateTercero(terceroEditando.id, terceroForm)
        else await createTercero(terceroForm)
      }, terceroEditando ? 'Tercero actualizado.' : 'Tercero creado.')
      if (!guardado) return
      cerrarTerceroForm()
      setTerceroEditando(null)
      setTerceroForm(TERCERO_INICIAL)
      await refrescarDespuesDeGuardar(cargarTerceros)
    })()
  }

  const editarAlmacen = (almacen: Almacen) => {
    setAlmacenEditando(almacen)
    setAlmacenForm({
      establecimiento: String(almacen.establecimiento),
      codigo: almacen.codigo,
      nombre: almacen.nombre,
      activo: almacen.activo,
    })
    setAlmacenFormVisible(true)
  }

  const guardarAlmacen = (event: FormEvent) => {
    event.preventDefault()
    void (async () => {
      const payload = {
        establecimiento: Number(almacenForm.establecimiento),
        codigo: almacenForm.codigo,
        nombre: almacenForm.nombre,
        activo: almacenForm.activo,
      }
      const guardado = await ejecutar(async () => {
        if (almacenEditando) await updateAlmacen(almacenEditando.id, payload)
        else await createAlmacen(payload)
      }, almacenEditando ? 'Almacén actualizado.' : 'Almacén creado.')
      if (!guardado) return
      cerrarAlmacenForm()
      setAlmacenEditando(null)
      setAlmacenForm(ALMACEN_INICIAL)
      await refrescarDespuesDeGuardar(cargarAlmacenes)
    })()
  }

  if (!empresaActiva) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center bg-white rounded-xl border border-slate-200">
        <div className="h-12 w-12 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 mb-4">
          <Building2 className="h-6 w-6" />
        </div>
        <h2 className="text-lg font-bold text-slate-900 mb-1">Selecciona una Empresa Activa</h2>
        <p className="text-xs text-slate-500 mb-4 max-w-sm">
          Los maestros de inventario, productos y almacenes operan bajo aislamiento multi-tenant estricto.
        </p>
        <Link to="/empresas">
          <Button variant="primary">Ir al Selector de Empresas</Button>
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={vista ? TITULOS_VISTA[vista].titulo : 'Maestros de Inventario'}
        description={
          vista
            ? `${TITULOS_VISTA[vista].descripcion} de ${empresaActiva.razon_social} (RUC: ${empresaActiva.ruc}).`
            : `Gestión de catálogo de existencias, conversiones de unidades y terceros comerciales para ${empresaActiva.razon_social} (RUC: ${empresaActiva.ruc}).`
        }
        icon={<Package className="h-5 w-5" />}
        badge={
          <Badge variant={esAdmin ? 'info' : 'neutral'}>
            {esAdmin ? 'Edición Habilitada (ADMIN)' : 'Modo Consulta (Lectura)'}
          </Badge>
        }
        actions={
          <Button
            variant="primary"
            onClick={abrirNuevo}
            disabled={!esAdmin || (tab === 'almacenes' && catalogosLoading)}
          >
            <Plus className="h-4 w-4 mr-1.5" />
            Nuevo {tab === 'productos' ? 'Producto' : tab === 'terceros' ? 'Tercero' : 'Almacén'}
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

      {/* Tabs */}
      <Tabs
        value={tab}
        onValueChange={(val) => {
          setTab(val as TabId)
          cerrarFormularios()
          limpiarMensajes()
        }}
      >
        <TabsList className={vista ? 'hidden' : undefined}>
          <TabsTrigger value="productos" icon={<Boxes className="h-3.5 w-3.5" />}>
            Productos y Conversiones ({productos.length})
          </TabsTrigger>
          <TabsTrigger value="terceros" icon={<Users className="h-3.5 w-3.5" />}>
            Terceros Clientes/Proveedores ({terceros.length})
          </TabsTrigger>
          <TabsTrigger value="almacenes" icon={<Warehouse className="h-3.5 w-3.5" />}>
            Almacenes ({almacenes.length})
          </TabsTrigger>
        </TabsList>

        {/* TAB 1: PRODUCTOS */}
        <TabsContent value="productos" className="space-y-6">
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="flex items-center justify-center p-12 text-slate-400 text-xs">
                  Cargando catálogo de productos…
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-32">Cód. Interno</TableHead>
                      <TableHead>Descripción del Producto</TableHead>
                      <TableHead className="w-48">Tipo Existencia (SUNAT)</TableHead>
                      <TableHead className="w-56">Unidad Base Obligatoria</TableHead>
                      <TableHead className="w-24">Estado</TableHead>
                      <TableHead className="text-right">Acciones</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {productos.map((producto) => (
                      <TableRow key={producto.id}>
                        <TableCell numeric className="font-bold text-slate-900">
                          {producto.codigo_interno}
                        </TableCell>
                        <TableCell className="font-medium text-slate-800">
                          {producto.descripcion}
                          {producto.precio_venta_sugerido && (
                            <span className="block font-mono text-[10px] font-normal text-slate-400">
                              P. venta sug. {formatearDecimal(producto.precio_venta_sugerido, { min: 2, max: 8 })}
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-mono text-xs font-semibold text-slate-800">
                              {producto.tipo_existencia_codigo}
                            </span>
                            <span className="text-[10px] text-slate-400 truncate max-w-xs">
                              {producto.tipo_existencia_descripcion}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell>
                          {producto.unidad_base ? (
                            <Badge variant="info" className="gap-1 font-mono text-xs">
                              UND BASE: {producto.unidad_base.codigo} (1.00000000)
                            </Badge>
                          ) : (
                            <Badge variant="destructive">Sin unidad base</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge variant={producto.estado === 'ACTIVO' ? 'success' : 'neutral'} dot>
                            {producto.estado}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <Button
                              type="button"
                              size="xs"
                              variant="outline"
                              onClick={() => void gestionarUnidades(producto)}
                            >
                              <Layers className="h-3 w-3 mr-1 text-indigo-600" /> Unidades
                            </Button>
                            {esAdmin && (
                              <Button
                                type="button"
                                size="xs"
                                variant="ghost"
                                onClick={() => editarProducto(producto)}
                              >
                                <Pencil className="h-3 w-3 mr-1 text-slate-500" /> Editar
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Panel de Gestión de Unidades de Medida */}
          {productoUnidadesActivo && (
            <Card className="border-indigo-200 bg-indigo-50/20 shadow-sm animate-in fade-in">
              <CardHeader className="flex flex-row items-center justify-between pb-3">
                <div className="flex items-center gap-2.5">
                  <div className="h-8 w-8 rounded-lg bg-indigo-600 text-white flex items-center justify-center">
                    <Layers className="h-4 w-4" />
                  </div>
                  <div>
                    <CardTitle className="text-base">
                      Presentaciones y Conversiones · {productoUnidadesActivo.codigo_interno}
                    </CardTitle>
                    <CardDescription>{productoUnidadesActivo.descripcion}</CardDescription>
                  </div>
                </div>
                <Button variant="ghost" size="icon-sm" onClick={cerrarUnidades}>
                  <X className="h-4 w-4" />
                </Button>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  {/* Tabla de Presentaciones */}
                  <div className="lg:col-span-2">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Unidad</TableHead>
                          <TableHead numeric>Factor a Base</TableHead>
                          <TableHead>Nivel</TableHead>
                          <TableHead className="text-right">Acción</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {productoUnidades.map((u) => (
                          <TableRow key={u.id}>
                            <TableCell className="font-semibold text-slate-900">
                              {u.unidad_codigo} — {u.unidad_descripcion}
                            </TableCell>
                            <TableCell numeric className="font-bold text-slate-800 text-sm">
                              {u.factor_a_base}
                            </TableCell>
                            <TableCell>
                              {u.es_base ? (
                                <Badge variant="info">Unidad Base (1.00000000)</Badge>
                              ) : (
                                <Badge variant="neutral">Presentación Secundaria</Badge>
                              )}
                            </TableCell>
                            <TableCell className="text-right">
                              {esAdmin && !u.es_base && (
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="outline"
                                  onClick={() => editarUnidad(u)}
                                >
                                  Editar
                                </Button>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    {unidadesLoading && (
                      <p className="text-xs text-slate-400 py-3 text-center">Cargando unidades…</p>
                    )}
                  </div>

                  {/* Formulario Agregar Presentación */}
                  {esAdmin && (
                    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs space-y-3">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
                        {unidadEditando ? 'Editar Presentación' : 'Agregar Presentación Secundaria'}
                      </h4>
                      <form onSubmit={guardarUnidad} className="space-y-3">
                        <div className="space-y-1">
                          <Label required>Unidad de Medida (Tabla 6 SUNAT)</Label>
                          <Select
                            required
                            value={unidadForm.unidad_codigo}
                            onChange={(e) => setUnidadForm({ ...unidadForm, unidad_codigo: e.target.value })}
                          >
                            <option value="">Seleccionar Unidad</option>
                            {unidadesMedida.map((u) => (
                              <option key={u.codigo} value={u.codigo}>
                                {u.codigo} — {u.descripcion}
                              </option>
                            ))}
                          </Select>
                        </div>

                        <div className="space-y-1">
                          <Label required>Factor de Conversión a Unidad Base</Label>
                          <Input
                            required
                            inputMode="decimal"
                            pattern="^\d+(\.\d{1,8})?$"
                            placeholder="Ej. 6.00000000 (Caja x6)"
                            value={unidadForm.factor_a_base}
                            disabled={unidadForm.es_base}
                            onChange={(e) => setUnidadForm({ ...unidadForm, factor_a_base: e.target.value })}
                            className="font-mono tabular-nums"
                          />
                          <p className="text-[10px] text-slate-400">
                            Equivalencia exacta en unidades base (hasta 8 decimales).
                          </p>
                        </div>

                        <div className="flex gap-2 pt-2">
                          <Button type="submit" variant="primary" size="sm" isLoading={saving} className="flex-1">
                            {unidadEditando ? 'Guardar' : 'Agregar'}
                          </Button>
                          {unidadEditando && (
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                setUnidadEditando(null)
                                setUnidadForm(UNIDAD_INICIAL)
                              }}
                            >
                              Cancelar
                            </Button>
                          )}
                        </div>
                      </form>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* TAB 2: TERCEROS */}
        <TabsContent value="terceros" className="space-y-4">
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <div className="flex rounded-lg border border-slate-200 bg-slate-100 p-0.5">
                {(['todos', 'cliente', 'proveedor'] as const).map((tipo) => (
                  <button
                    key={tipo}
                    type="button"
                    onClick={() => setTipoTercero(tipo)}
                    className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors cursor-pointer ${
                      tipoTercero === tipo
                        ? 'bg-white text-slate-900 shadow-2xs'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    {tipo === 'todos' ? 'Todos' : tipo === 'cliente' ? 'Clientes' : 'Proveedores'}
                  </button>
                ))}
              </div>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                setSearch(searchDraft.trim())
              }}
              className="flex items-center gap-2 w-full sm:w-80"
            >
              <Input
                placeholder="RUC, DNI o Razón Social..."
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
                leftIcon={<Search className="h-4 w-4" />}
              />
              <Button type="submit" variant="secondary" size="sm">
                Buscar
              </Button>
              {(search || searchDraft) && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSearchDraft('')
                    setSearch('')
                  }}
                >
                  Limpiar
                </Button>
              )}
            </form>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-40">Documento Identidad</TableHead>
                    <TableHead>Razón Social / Nombre</TableHead>
                    <TableHead className="w-40">Relación Comercial</TableHead>
                    <TableHead className="w-48">Contacto</TableHead>
                    <TableHead className="w-24">Estado</TableHead>
                    <TableHead className="text-right">Acción</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {terceros.map((tercero) => (
                    <TableRow key={tercero.id}>
                      <TableCell numeric className="font-bold text-slate-900">
                        <span className="text-[10px] text-slate-400 block font-normal">{etiquetaTipoDocumento(tercero.tipo_documento)}</span>
                        {tercero.numero_documento}
                      </TableCell>
                      <TableCell>
                        <div className="font-semibold text-slate-900">{tercero.razon_social}</div>
                        {tercero.nombre_comercial && (
                          <div className="text-xs text-slate-400">{tercero.nombre_comercial}</div>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1.5 flex-wrap">
                          {tercero.es_cliente && <Badge variant="success">CLIENTE</Badge>}
                          {tercero.es_proveedor && <Badge variant="info">PROVEEDOR</Badge>}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-slate-600">
                        <div>{tercero.telefono || '—'}</div>
                        <div className="text-slate-400 truncate max-w-xs">{tercero.correo}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={tercero.estado === 'ACTIVO' ? 'success' : 'neutral'} dot>
                          {tercero.estado}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            type="button"
                            size="xs"
                            variant="ghost"
                            title="Historial de comprobantes"
                            onClick={() => setHistorialTercero(tercero)}
                          >
                            <History className="h-3.5 w-3.5" /> Historial
                          </Button>
                          {esAdmin && (
                            <Button
                              type="button"
                              size="xs"
                              variant="outline"
                              onClick={() => editarTercero(tercero)}
                            >
                              Editar
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 3: ALMACENES */}
        <TabsContent value="almacenes" className="space-y-4">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-32">Cód. Almacén</TableHead>
                    <TableHead>Nombre del Almacén</TableHead>
                    <TableHead>Establecimiento Anexo SUNAT</TableHead>
                    <TableHead className="w-28">Estado</TableHead>
                    <TableHead className="text-right">Acción</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {almacenes.map((almacen) => (
                    <TableRow key={almacen.id}>
                      <TableCell numeric className="font-bold text-slate-900">
                        {almacen.codigo}
                      </TableCell>
                      <TableCell className="font-semibold text-slate-800">{almacen.nombre}</TableCell>
                      <TableCell>
                        <span className="font-mono text-xs text-slate-700 font-medium">
                          {almacen.establecimiento_codigo} — {almacen.establecimiento_nombre}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge variant={almacen.activo ? 'success' : 'neutral'} dot>
                          {almacen.activo ? 'ACTIVO' : 'INACTIVO'}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        {esAdmin && (
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            onClick={() => editarAlmacen(almacen)}
                          >
                            Editar
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Modal: Crear / Editar Producto */}
      {productoFormVisible && (
        <Modal
          isOpen={productoFormVisible}
          onClose={cerrarProductoForm}
          title={productoEditando ? 'Editar Producto' : 'Nuevo Producto en Catálogo'}
          description={
            productoEditando
              ? productoEditando.codigo_interno
              : 'Se asociará con su unidad base obligatoria (factor = 1.00000000).'
          }
          icon={<Boxes className="h-5 w-5" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={cerrarProductoForm}>
                Cancelar
              </Button>
              <Button variant="primary" onClick={guardarProducto} isLoading={saving}>
                <Save className="h-4 w-4 mr-1.5" />
                {productoEditando ? 'Guardar Cambios' : 'Crear Producto'}
              </Button>
            </div>
          }
        >
          <form onSubmit={guardarProducto} className="space-y-4">
            <div className="space-y-1.5">
              <Label required>Código Interno</Label>
              <Input
                required
                maxLength={50}
                placeholder="PROD-001"
                className="font-mono tabular-nums"
                value={productoForm.codigo_interno}
                onChange={(e) => setProductoForm({ ...productoForm, codigo_interno: e.target.value })}
              />
            </div>

            <div className="space-y-1.5">
              <Label required>Descripción del Producto</Label>
              <Input
                required
                maxLength={250}
                placeholder="Descripción detallada de la mercancía"
                value={productoForm.descripcion}
                onChange={(e) => setProductoForm({ ...productoForm, descripcion: e.target.value })}
              />
            </div>

            <div className="space-y-1.5">
              <Label required>Tipo de Existencia (Tabla 5 SUNAT)</Label>
              <Select
                required
                value={productoForm.tipo_existencia_codigo}
                onChange={(e) => setProductoForm({ ...productoForm, tipo_existencia_codigo: e.target.value })}
              >
                <option value="">Seleccionar Tipo</option>
                {tiposExistencia.map((t) => (
                  <option key={t.codigo} value={t.codigo}>
                    {t.codigo} — {t.descripcion}
                  </option>
                ))}
              </Select>
            </div>

            {!productoEditando && (
              <div className="space-y-1.5">
                <Label required>Unidad de Medida Base (Tabla 6 SUNAT)</Label>
                <Select
                  required
                  value={productoForm.unidad_base_codigo}
                  onChange={(e) => setProductoForm({ ...productoForm, unidad_base_codigo: e.target.value })}
                >
                  <option value="">Seleccionar Unidad Base</option>
                  {unidadesMedida.map((u) => (
                    <option key={u.codigo} value={u.codigo}>
                      {u.codigo} — {u.descripcion}
                    </option>
                  ))}
                </Select>
                <p className="text-[10px] text-slate-400">
                  Esta unidad representará el factor estándar 1.00000000 para costeo en Kardex.
                </p>
              </div>
            )}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="producto-precio-sugerido">Precio de venta sugerido</Label>
                <Input
                  id="producto-precio-sugerido"
                  type="number"
                  inputMode="decimal"
                  step="any"
                  min="0"
                  placeholder="Opcional"
                  className="font-mono tabular-nums"
                  value={productoForm.precio_venta_sugerido}
                  onChange={(e) => setProductoForm({ ...productoForm, precio_venta_sugerido: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="producto-afectacion">Afectación IGV por defecto</Label>
                <Select
                  id="producto-afectacion"
                  value={productoForm.afectacion_igv_defecto}
                  onChange={(e) => setProductoForm({ ...productoForm, afectacion_igv_defecto: e.target.value })}
                >
                  <option value="">Sin preferencia</option>
                  {AFECTACIONES_IGV.filter((a) => a.valor !== 'GRATUITO').map((a) => (
                    <option key={a.valor} value={a.valor}>{a.etiqueta}</option>
                  ))}
                </Select>
              </div>
              <p className="text-[10px] text-slate-400 sm:col-span-2">
                Solo se sugieren al registrar una venta; no intervienen en el costo, el CPP ni el Kardex.
              </p>
            </div>

            <div className="space-y-1.5">
              <Label>Estado de la Existencia</Label>
              <Select
                value={productoForm.estado}
                onChange={(e) => setProductoForm({ ...productoForm, estado: e.target.value as EstadoMaestro })}
              >
                <option value="ACTIVO">Activo</option>
                <option value="INACTIVO">Inactivo</option>
              </Select>
            </div>
          </form>
        </Modal>
      )}

      {historialTercero && <HistorialTerceroModal tercero={historialTercero} onClose={() => setHistorialTercero(null)} />}

      {/* Modal: Crear / Editar Tercero */}
      {terceroFormVisible && (
        <Modal
          isOpen={terceroFormVisible}
          onClose={cerrarTerceroForm}
          title={terceroEditando ? 'Editar Tercero Comercial' : 'Nuevo Tercero Comercial'}
          description="Cliente, proveedor o relación combinada."
          icon={<Users className="h-5 w-5" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={cerrarTerceroForm}>
                Cancelar
              </Button>
              <Button
                variant="primary"
                onClick={guardarTercero}
                isLoading={saving}
                disabled={terceroSinRol || Boolean(errorDocTercero)}
              >
                <Save className="h-4 w-4 mr-1.5" />
                {terceroEditando ? 'Guardar Cambios' : 'Crear Tercero'}
              </Button>
            </div>
          }
        >
          <form onSubmit={guardarTercero} className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label required htmlFor="tercero-tipo-documento">Tipo de documento</Label>
                <Select
                  id="tercero-tipo-documento"
                  required
                  value={terceroForm.tipo_documento}
                  onChange={(e) => setTerceroForm({ ...terceroForm, tipo_documento: e.target.value })}
                >
                  {!TIPOS_DOCUMENTO_IDENTIDAD.some((t) => t.codigo === terceroForm.tipo_documento) && (
                    <option value={terceroForm.tipo_documento}>{terceroForm.tipo_documento} (no válido)</option>
                  )}
                  {TIPOS_DOCUMENTO_IDENTIDAD.map((t) => (
                    <option key={t.codigo} value={t.codigo}>{t.codigo} — {t.etiqueta}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label required>Número de Documento</Label>
                <Input
                  required
                  maxLength={20}
                  value={terceroForm.numero_documento}
                  onChange={(e) => setTerceroForm({ ...terceroForm, numero_documento: e.target.value })}
                  className="font-mono tabular-nums"
                  aria-invalid={Boolean(errorDocTercero)}
                />
              </div>
            </div>
            {errorDocTercero && (
              <p className="text-xs text-rose-600" role="alert" data-testid="error-documento-tercero">{errorDocTercero}</p>
            )}
            {/* Bloque 17C: con RUC se pueden traer razón social, nombre comercial y dirección. */}
            {terceroForm.tipo_documento === '6' && (
              <ConsultaRucBoton ruc={terceroForm.numero_documento} formulario={terceroForm} campos={MAPA_TERCERO} onAplicar={setTerceroForm} />
            )}

            <div className="space-y-1.5">
              <Label required>Razón Social / Nombre Completo</Label>
              <Input
                required
                maxLength={200}
                value={terceroForm.razon_social}
                onChange={(e) => setTerceroForm({ ...terceroForm, razon_social: e.target.value })}
              />
            </div>

            <div className="space-y-1.5">
              <Label>Nombre Comercial</Label>
              <Input
                maxLength={200}
                value={terceroForm.nombre_comercial}
                onChange={(e) => setTerceroForm({ ...terceroForm, nombre_comercial: e.target.value })}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Teléfono</Label>
                <Input
                  maxLength={50}
                  value={terceroForm.telefono}
                  onChange={(e) => setTerceroForm({ ...terceroForm, telefono: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Correo Electrónico</Label>
                <Input
                  type="email"
                  maxLength={254}
                  value={terceroForm.correo}
                  onChange={(e) => setTerceroForm({ ...terceroForm, correo: e.target.value })}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Dirección Fiscal</Label>
              <Input
                maxLength={300}
                value={terceroForm.direccion}
                onChange={(e) => setTerceroForm({ ...terceroForm, direccion: e.target.value })}
              />
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
              <Label required>Relación Comercial</Label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 text-xs font-medium cursor-pointer">
                  <input
                    type="checkbox"
                    checked={terceroForm.es_cliente}
                    onChange={(e) => setTerceroForm({ ...terceroForm, es_cliente: e.target.checked })}
                    className="rounded text-indigo-600 cursor-pointer"
                  />
                  Cliente
                </label>
                <label className="flex items-center gap-2 text-xs font-medium cursor-pointer">
                  <input
                    type="checkbox"
                    checked={terceroForm.es_proveedor}
                    onChange={(e) => setTerceroForm({ ...terceroForm, es_proveedor: e.target.checked })}
                    className="rounded text-indigo-600 cursor-pointer"
                  />
                  Proveedor
                </label>
              </div>
              {terceroSinRol && (
                <p className="text-[11px] text-rose-600 font-medium">Selecciona al menos una relación comercial.</p>
              )}
            </div>
          </form>
        </Modal>
      )}

      {/* Modal: Crear / Editar Almacén */}
      {almacenFormVisible && (
        <Modal
          isOpen={almacenFormVisible}
          onClose={cerrarAlmacenForm}
          title={almacenEditando ? 'Editar Almacén' : 'Nuevo Almacén Físico'}
          description="Vinculado obligatoriamente a un establecimiento SUNAT de la empresa."
          icon={<Warehouse className="h-5 w-5" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={cerrarAlmacenForm}>
                Cancelar
              </Button>
              <Button variant="primary" onClick={guardarAlmacen} isLoading={saving}>
                <Save className="h-4 w-4 mr-1.5" />
                {almacenEditando ? 'Guardar Cambios' : 'Crear Almacén'}
              </Button>
            </div>
          }
        >
          <form onSubmit={guardarAlmacen} className="space-y-4">
            <div className="space-y-1.5">
              <Label required>Establecimiento SUNAT</Label>
              <Select
                required
                value={almacenForm.establecimiento}
                onChange={(e) => setAlmacenForm({ ...almacenForm, establecimiento: e.target.value })}
              >
                <option value="">Seleccionar Establecimiento</option>
                {establecimientos
                  .filter((e) => e.activo || Number(almacenForm.establecimiento) === e.id)
                  .map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.codigo_sunat} — {e.nombre}
                    </option>
                  ))}
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label required>Código del Almacén</Label>
              <Input
                required
                maxLength={50}
                placeholder="ALM-01"
                className="font-mono tabular-nums"
                value={almacenForm.codigo}
                onChange={(e) => setAlmacenForm({ ...almacenForm, codigo: e.target.value })}
              />
            </div>

            <div className="space-y-1.5">
              <Label required>Nombre del Almacén</Label>
              <Input
                required
                maxLength={150}
                placeholder="ALMACÉN PRINCIPAL DE MATERIAS PRIMAS"
                value={almacenForm.nombre}
                onChange={(e) => setAlmacenForm({ ...almacenForm, nombre: e.target.value })}
              />
            </div>

            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="alm-activo"
                checked={almacenForm.activo}
                onChange={(e) => setAlmacenForm({ ...almacenForm, activo: e.target.checked })}
                className="rounded text-indigo-600 cursor-pointer"
              />
              <Label htmlFor="alm-activo" className="cursor-pointer">
                Almacén Activo para Operaciones
              </Label>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}

export default MaestrosInventarioPage
