import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  CONFIG_VISTAS, TABS_COMPROBANTES, claseDeTab, claseInicialNuevo, filtrosApiDocumentos, queryConTab, tabDesdeQuery,
  tiposComprobanteDeVista, type TabComprobantes, type VistaDocumentos,
} from '../../utils/vistaDocumentos'
import { Tabs, TabsList, TabsTrigger } from '../../components/ui/tabs'
import {
  FileSpreadsheet,
  Plus,
  Eye,
  CheckCheck,
  CheckCircle2,
  Ban,
  Search,
  AlertCircle,
  Trash2,
  Receipt,
} from 'lucide-react'
import {
  obtenerDocumentos,
  obtenerDocumentosPaginados,
  obtenerDocumento,
  crearDocumento,
  revisarDocumento,
  confirmarDocumento,
  anularDocumento,
} from '../../api/documentos'
import type {
  Documento,
  ClaseDocumento,
  EstadoDocumental,
  EstadoRevision,
  CrearDocumentoPayload,
} from '../../api/documentos'
import { obtenerPeriodos } from '../../api/periodos'
import type { Periodo } from '../../api/periodos'
import {
  obtenerTiposComprobante,
  obtenerTiposOperacion,
  resolverTipoCambio,
} from '../../api/catalogos'
import type {
  TipoComprobante,
  TipoOperacion,
  TipoCambioResolverResult,
} from '../../api/catalogos'
import {
  getProductos,
  getProductoUnidades,
  getAlmacenes,
  getTerceros,
} from '../../api/inventario'
import type {
  Producto,
  ProductoUnidad,
  Almacen,
  Tercero,
} from '../../api/inventario'
import { useAuth } from '../../context/useAuth'
import { obtenerSeries, type SerieComprobante } from '../../api/finanzas'
import { CondicionPagoCampos } from '../../components/finanzas/CondicionPagoCampos'
import { PagosDocumento } from '../../components/finanzas/PagosDocumento'
import { obtenerCatalogo07, obtenerMotivosNota, type CodigoAfectacionIgv, type MotivoNota } from '../../api/catalogos'
import { CodigoAfectacionLinea } from '../../components/tributario/CodigoAfectacionLinea'
import { catalogoMotivo } from '../../utils/tributario'
import { CONDICION_INICIAL, errorCondicionPago, numeroComprobante, type CondicionPagoValor } from '../../utils/finanzas'
import { fechaCalendarioLocal } from '../../utils/date'
import { PageHeader } from '../../components/ui/page-header'
import { Button } from '../../components/ui/button'
import { Card, CardContent } from '../../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Badge } from '../../components/ui/badge'
import { cantidadBase, importeLinea, totalesDocumento } from '../../utils/documentoCalculo'
import { esMayorQueCero, formatearDecimal } from '../../utils/decimal'
import {
  AFECTACIONES_IGV, TASA_IGV_POR_DEFECTO_PCT, codigoAfectacionParaEnviar, codigosGratuitos, errorCodigoGratuito, igvEditable,
  igvSugerido, reconciliarCodigoAfectacion, tasaVigente, type AfectacionIgv, type TasaIgvVigencia,
} from '../../utils/afectacionIgv'
import { obtenerConfigEmpresa } from '../../api/empresas'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Label } from '../../components/ui/label'
import { Modal } from '../../components/ui/modal'
import { AlertaFormulario } from '../../components/ui/alerta-formulario'
import { mensajesDeErrorApi } from '../../utils/errores'
import { contraparteDocumento } from '../../utils/contraparteDocumento'
import {
  disponibleEnUnidad, errorLineasNota, esDevolucionFisica, etiquetaLineaOrigen, lineasOrigenElegibles, type LineaOrigen,
} from '../../utils/devolucionNota'
import { errorDeOperaciones, operacionesPermitidas, operacionPorDefecto, reconciliarOperaciones } from '../../utils/operacionesComerciales'
import { Paginacion } from '../../components/ui/paginacion'
import { diferirCarga } from '../../utils/efectos'
import { useValorDiferido } from '../../utils/useValorDiferido'
import {
  PAGE_SIZE_DEFECTO, claveConsulta, irAPagina, paginaVigente, paramsPaginacion, type EstadoPagina,
} from '../../utils/paginacion'

interface LineaFormulario {
  tempId: string
  productoId: number | ''
  productoUnidadId: number | ''
  almacenId: number | ''
  tipoOperacionId: number | ''
  cantidadOriginal: string
  precioUnitario: string
  igv: string
  afectacionIgv: AfectacionIgv
  /** B17A-QA-001: código del Catálogo 07; solo en líneas gratuitas ('' = sin elegir). */
  codigoAfectacionIgv: string
  esBonificacion: boolean
  descripcionOriginal: string
  detalleOrigenId?: number | ''
  unidadesDisponibles: ProductoUnidad[]
  /** Texto decimal tal como lo entrega la API (sin pasar por float). */
  factorConversion: string
}

export interface DocumentosPageProps {
  /**
   * Navegación por flujo: Compras, Ventas y Notas reutilizan esta misma pantalla con
   * filtros fijos (utils/vistaDocumentos.ts). 'TODOS' = Comprobantes, sin cambios.
   */
  vista?: VistaDocumentos
}

// Bloque 10: inputs numéricos del detalle — texto completo a la derecha, sin las flechas del
// navegador (le quitaban ~16 px), y step="any" para aceptar los decimales que el backend admite.
const CLASE_INPUT_NUMERICO =
  'w-full h-8.5 rounded-md border border-slate-200 bg-white px-2.5 text-right font-mono tabular-nums text-xs ' +
  'focus:ring-1 focus:ring-slate-900 focus:border-slate-900 disabled:bg-slate-50 disabled:text-slate-400 ' +
  '[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none transition-colors'

const CLASE_SELECT_TABLA =
  'w-full h-8.5 rounded-md border border-slate-200 bg-white px-2.5 text-xs text-slate-800 ' +
  'focus:ring-1 focus:ring-slate-900 focus:border-slate-900 disabled:bg-slate-50 disabled:text-slate-400 transition-colors'

// Bloque 10: los errores de un formulario en modal se muestran DENTRO de ese modal (antes
// iban a `errorGlobal`, que se pinta en la página de atrás, tapada por el modal).
type ModalConError = 'nuevo' | 'revision' | 'anulacion'
interface ErrorModal {
  modal: ModalConError
  titulo: string
  mensajes: string[]
  /** Valores del formulario cuando ocurrió: si el usuario los corrige, el aviso se oculta. */
  firma: string
}

export const DocumentosPage: React.FC<DocumentosPageProps> = ({ vista = 'COMPROBANTES' }) => {
  const { empresaActiva, usuario } = useAuth()
  const esAdmin = Boolean(usuario?.es_admin_global || empresaActiva?.rol === 'ADMIN')
  const configVista = CONFIG_VISTAS[vista]
  const [searchParams, setSearchParams] = useSearchParams()

  // Master Data
  const [documentos, setDocumentos] = useState<Documento[]>([])
  const [periodos, setPeriodos] = useState<Periodo[]>([])
  const [tiposComprobante, setTiposComprobante] = useState<TipoComprobante[]>([])
  const [tiposOperacion, setTiposOperacion] = useState<TipoOperacion[]>([])
  const [productos, setProductos] = useState<Producto[]>([])
  const [almacenes, setAlmacenes] = useState<Almacen[]>([])
  const [terceros, setTerceros] = useState<Tercero[]>([])
  // Bloque 4: tasa del IGV configurada para la empresa (solo para sugerir; valida el backend)
  const [tasaIgvActual, setTasaIgvActual] = useState<string>(TASA_IGV_POR_DEFECTO_PCT)
  const [tasasIgv, setTasasIgv] = useState<TasaIgvVigencia[]>([])

  // Filters
  // Bloque 13: en Comprobantes la clase es la pestaña (Todos | Compras | Ventas), guardada en
  // la URL (?clase=COMPRA); en Notas sigue siendo el selector de la barra de filtros.
  const tabComprobantes: TabComprobantes | null = vista === 'COMPROBANTES' ? tabDesdeQuery(searchParams.get('clase')) : null
  const [filtroClaseNotas, setFiltroClaseNotas] = useState<ClaseDocumento | ''>('')
  const filtroClase: ClaseDocumento | '' = tabComprobantes ? (claseDeTab(tabComprobantes) ?? '') : filtroClaseNotas
  const cambiarTab = (tab: string) => setSearchParams(queryConTab(searchParams, tab as TabComprobantes))
  const [filtroPeriodo, setFiltroPeriodo] = useState<number | ''>('')
  const [filtroEstado, setFiltroEstado] = useState<EstadoDocumental | ''>('')
  const [filtroRevision, setFiltroRevision] = useState<EstadoRevision | ''>('')
  const [filtroBusqueda, setFiltroBusqueda] = useState('')
  const busqueda = useValorDiferido(filtroBusqueda.trim())

  // Bloque 7: los filtros se aplican en el servidor y la lista llega por páginas.
  // Cambiar de empresa o de filtro vuelve a la página 1.
  const empresaId = empresaActiva?.id
  const [totalDocumentos, setTotalDocumentos] = useState(0)
  const [estadoPagina, setEstadoPagina] = useState<EstadoPagina>({ clave: '', page: 1 })
  const claveFiltros = claveConsulta(empresaId, vista, filtroClase, filtroPeriodo, filtroEstado, filtroRevision, busqueda)
  const page = paginaVigente(estadoPagina, claveFiltros)
  // Comprobantes que pueden ser origen de una nota (lista completa, solo al registrar una nota).
  const [documentosOrigen, setDocumentosOrigen] = useState<Documento[]>([])

  // UI States
  const [cargando, setCargando] = useState(false)
  const [catalogosCargados, setCatalogosCargados] = useState(false)
  // B17A-QA-001: Catálogo 07 (fuente canónica en el backend) para las líneas gratuitas.
  const [catalogo07, setCatalogo07] = useState<CodigoAfectacionIgv[]>([])
  const opcionesGratuitas = useMemo(() => codigosGratuitos(catalogo07), [catalogo07])
  const [errorGlobal, setErrorGlobal] = useState<string | null>(null)
  const [exitoGlobal, setExitoGlobal] = useState<string | null>(null)
  const [errorModal, setErrorModal] = useState<ErrorModal | null>(null)
  const alertaModalRef = useRef<HTMLDivElement>(null)

  // Modals
  const [modalNuevoAbierto, setModalNuevoAbierto] = useState(false)
  const [modalDetalleDocumento, setModalDetalleDocumento] = useState<Documento | null>(null)
  const [modalRevisionDoc, setModalRevisionDoc] = useState<Documento | null>(null)
  const [modalAnulacionDoc, setModalAnulacionDoc] = useState<Documento | null>(null)

  // Form State (New Document)
  const [formClase, setFormClase] = useState<ClaseDocumento>('COMPRA')
  const [formPeriodo, setFormPeriodo] = useState<number | ''>('')
  const [formTipoComprobante, setFormTipoComprobante] = useState<number | ''>('')
  const [formTercero, setFormTercero] = useState<number | ''>('')
  const [formSerie, setFormSerie] = useState('')
  const [formNumero, setFormNumero] = useState('')
  const [formFechaEmision, setFormFechaEmision] = useState(fechaCalendarioLocal)
  const [formMoneda, setFormMoneda] = useState<'PEN' | 'USD'>('PEN')
  const [formDocOrigen, setFormDocOrigen] = useState<number | ''>('')
  // Bloque 16: condición de pago y serie con correlativo automático (solo ventas).
  const [formCondicion, setFormCondicion] = useState<CondicionPagoValor>(CONDICION_INICIAL)
  const [seriesDisponibles, setSeriesDisponibles] = useState<SerieComprobante[]>([])
  const [formSerieId, setFormSerieId] = useState<number | ''>('')
  // Bloque 17A: motivo tributario de la nota (catálogo 09 NC / 10 ND).
  const [formMotivoNota, setFormMotivoNota] = useState('')
  const [motivosNota, setMotivosNota] = useState<MotivoNota[]>([])
  // QA-001: líneas del comprobante de origen de la nota (para elegir `detalle_origen`).
  const [origenDetalles, setOrigenDetalles] = useState<LineaOrigen[]>([])
  const [tcResuelto, setTcResuelto] = useState<TipoCambioResolverResult | null>(null)
  const [cargandoTc, setCargandoTc] = useState(false)
  const [guardandoDoc, setGuardandoDoc] = useState(false)

  // Detail Lines
  const [lineas, setLineas] = useState<LineaFormulario[]>([])

  // Revision Modal Action
  const [revEstadoSeleccionado, setRevEstadoSeleccionado] = useState<EstadoRevision>('REVISADO')
  const [revMotivo, setRevMotivo] = useState('')
  const [anulacionMotivo, setAnulacionMotivo] = useState('')

  // Firma de cada formulario: el aviso solo se muestra mientras los datos sigan iguales a los
  // que produjeron el error (al corregir un campo desaparece; al reenviar se recalcula).
  const firmaNuevo = JSON.stringify([
    formClase, formPeriodo, formTipoComprobante, formTercero, formSerie, formNumero, formFechaEmision, formMoneda, formDocOrigen,
    formSerieId, formCondicion, formMotivoNota,
    lineas.map((l) => [l.productoId, l.productoUnidadId, l.almacenId, l.tipoOperacionId, l.cantidadOriginal, l.precioUnitario, l.igv, l.afectacionIgv, l.codigoAfectacionIgv, l.esBonificacion, l.detalleOrigenId]),
  ])
  const firmaRevision = JSON.stringify([modalRevisionDoc?.id, revEstadoSeleccionado, revMotivo])
  const firmaAnulacion = JSON.stringify([modalAnulacionDoc?.id, anulacionMotivo])
  const firmas: Record<ModalConError, string> = { nuevo: firmaNuevo, revision: firmaRevision, anulacion: firmaAnulacion }
  const alertaDe = (modal: ModalConError) =>
    errorModal && errorModal.modal === modal && errorModal.firma === firmas[modal] ? errorModal : null
  const mostrarErrorModal = (modal: ModalConError, titulo: string, mensajes: string[]) =>
    setErrorModal({ modal, titulo, mensajes, firma: firmas[modal] })

  // El aviso queda arriba del cuerpo del modal: si el usuario estaba abajo (líneas), se lleva a la vista.
  useEffect(() => {
    if (errorModal) alertaModalRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [errorModal])

  // Página actual de documentos con los filtros vigentes.
  const cargarDocumentos = useCallback(async () => {
    if (!empresaId) return
    setCargando(true)
    try {
      const data = await obtenerDocumentosPaginados(
        filtrosApiDocumentos(vista, {
          clase: filtroClase || undefined,
          periodo: filtroPeriodo || undefined,
          estado: filtroEstado || undefined,
          estado_revision: filtroRevision || undefined,
          search: busqueda || undefined,
        }),
        paramsPaginacion(page),
      )
      setDocumentos(data.results)
      setTotalDocumentos(data.count)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setErrorGlobal(axiosErr.response?.data?.detail || 'Error al cargar los datos del sistema.')
    } finally {
      setCargando(false)
    }
  }, [empresaId, vista, filtroClase, filtroPeriodo, filtroEstado, filtroRevision, busqueda, page])

  useEffect(() => {
    diferirCarga(cargarDocumentos)
  }, [cargarDocumentos])

  // Cargar catálogos
  const cargarCatalogosYDocumentos = useCallback(async () => {
    setCargando(true)
    setErrorGlobal(null)
    try {
      const [pers, comps, ops, prods, alms, tercs, cat07] = await Promise.all([
        obtenerPeriodos(),
        obtenerTiposComprobante(),
        obtenerTiposOperacion(),
        getProductos(),
        getAlmacenes(),
        getTerceros(),
        obtenerCatalogo07().catch(() => [] as CodigoAfectacionIgv[]),
      ])
      setCatalogo07(cat07)
      setPeriodos(pers)
      setTiposComprobante(comps.filter((c) => c.activo))
      setTiposOperacion(ops.filter((o) => o.activo))
      setProductos(prods.filter((p) => p.estado === 'ACTIVO'))
      setAlmacenes(alms.filter((a) => a.activo))
      setTerceros(tercs.filter((t) => t.estado === 'ACTIVO'))

      const periodoAbierto = pers.find((p) => p.estado === 'ABIERTO')
      if (periodoAbierto) {
        setFormPeriodo(periodoAbierto.id)
      }
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setErrorGlobal(axiosErr.response?.data?.detail || 'Error al cargar los datos del sistema.')
    } finally {
      setCargando(false)
      setCatalogosCargados(true)
    }
  }, [])

  useEffect(() => {
    diferirCarga(cargarCatalogosYDocumentos)
  }, [cargarCatalogosYDocumentos, empresaActiva?.id])

  useEffect(() => {
    obtenerConfigEmpresa()
      .then((config) => {
        setTasaIgvActual(config.tasa_igv_pct || TASA_IGV_POR_DEFECTO_PCT)
        setTasasIgv(config.tasas_igv ?? [])
      })
      .catch(() => setTasaIgvActual(TASA_IGV_POR_DEFECTO_PCT))
  }, [empresaActiva?.id])

  // Resolver Tipo de Cambio automáticamente cuando la moneda sea USD y cambie la fecha
  useEffect(() => {
    diferirCarga(() => {
      if (formMoneda === 'USD' && formFechaEmision) {
        setCargandoTc(true)
        resolverTipoCambio('USD', formFechaEmision)
          .then((res) => {
            setTcResuelto(res)
          })
          .catch(() => {
            setTcResuelto(null)
          })
          .finally(() => {
            setCargandoTc(false)
          })
      } else {
        setTcResuelto(null)
      }
    })
  }, [formMoneda, formFechaEmision])

  const tipoCompSeleccionado = useMemo(() => {
    return tiposComprobante.find((c) => c.id === formTipoComprobante)
  }, [tiposComprobante, formTipoComprobante])

  const esNota = Boolean(tipoCompSeleccionado?.es_nota)

  // Bloque 16: series activas del tipo elegido (solo ventas). El número lo asigna el backend.
  useEffect(() => {
    if (!modalNuevoAbierto || formClase !== 'VENTA' || !formTipoComprobante) {
      diferirCarga(() => { setSeriesDisponibles([]); setFormSerieId('') })
      return
    }
    let vigente = true
    obtenerSeries({ tipo_comprobante: Number(formTipoComprobante), activo: true })
      .then((series) => {
        if (!vigente) return
        setSeriesDisponibles(series)
        setFormSerieId(series[0]?.id ?? '')
      })
      .catch(() => { if (vigente) { setSeriesDisponibles([]); setFormSerieId('') } })
    return () => { vigente = false }
  }, [modalNuevoAbierto, formClase, formTipoComprobante])

  const serieSeleccionada = seriesDisponibles.find((x) => x.id === formSerieId)

  // Bloque 17A: motivos del catálogo que corresponde a la nota elegida.
  const catalogoMotivoForm = catalogoMotivo(tipoCompSeleccionado?.codigo_sunat)
  useEffect(() => {
    if (!modalNuevoAbierto || !catalogoMotivoForm) {
      diferirCarga(() => { setMotivosNota([]); setFormMotivoNota('') })
      return
    }
    let vigente = true
    obtenerMotivosNota(catalogoMotivoForm)
      .then((m) => { if (vigente) { setMotivosNota(m); setFormMotivoNota((actual) => (m.some((x) => x.codigo === actual) ? actual : '')) } })
      .catch(() => { if (vigente) setMotivosNota([]) })
    return () => { vigente = false }
  }, [modalNuevoAbierto, catalogoMotivoForm])

  const rucEmisorDisplay = useMemo(() => {
    if (formClase === 'VENTA') {
      return empresaActiva?.ruc || 'RUC Empresa Activa'
    }
    const t = terceros.find((ter) => ter.id === formTercero)
    return t ? t.numero_documento : 'Pendiente de selección'
  }, [formClase, formTercero, empresaActiva?.ruc, terceros])

  // Bloque 12: la operación por defecto sale de la clase y el comprobante (COMPRA → COMPRA,
  // VENTA → VENTA), buscada por código: el catálogo viene en orden alfabético y su primer
  // elemento (AJUSTE_INGRESO) quedaba antes en todas las líneas.
  const lineaVacia = useCallback((clase: ClaseDocumento = formClase): LineaFormulario => ({
    tempId: Math.random().toString(36).substring(2, 9),
    productoId: '',
    productoUnidadId: '',
    almacenId: almacenes[0]?.id || '',
    tipoOperacionId: operacionPorDefecto(tiposOperacion, clase, tipoCompSeleccionado),
    cantidadOriginal: '1.00000000',
    precioUnitario: '0.00000000',
    igv: '0.00000000',
    afectacionIgv: 'GRAVADO',
    codigoAfectacionIgv: '',
    esBonificacion: false,
    descripcionOriginal: '',
    unidadesDisponibles: [],
    factorConversion: '1',
  }), [almacenes, tiposOperacion, formClase, tipoCompSeleccionado])

  // Operaciones que ofrece el selector de cada línea (sin internas, de motor ni incompatibles).
  const operacionesLinea = useMemo(
    () => operacionesPermitidas(tiposOperacion, formClase, tipoCompSeleccionado),
    [tiposOperacion, formClase, tipoCompSeleccionado],
  )

  const agregarLinea = () => {
    setLineas((prev) => [...prev, lineaVacia()])
  }

  const eliminarLinea = (tempId: string) => {
    setLineas((prev) => prev.filter((l) => l.tempId !== tempId))
  }

  // Bloque 9: IGV sugerido en decimal exacto (= igv_esperado del backend), con la naturaleza
  // de la operación (un ajuste de valor sin cantidad usa el precio como base).
  const sugerirIgvLinea = (linea: LineaFormulario, tasaPct: string) => {
    const naturaleza = tiposOperacion.find((t) => t.id === linea.tipoOperacionId)?.naturaleza
    return igvSugerido(linea.afectacionIgv, linea.cantidadOriginal, linea.precioUnitario, tasaPct, naturaleza)
  }

  // Al cambiar la fecha puede cambiar la tasa vigente (Bloque 5): se vuelve a sugerir el IGV.
  const cambiarFechaEmision = (fecha: string) => {
    setFormFechaEmision(fecha)
    const tasa = tasaVigente(tasasIgv, fecha, tasaIgvActual)
    setLineas((prev) => prev.map((l) => {
      if (l.esBonificacion) return l
      const sugerido = sugerirIgvLinea(l, tasa)
      return sugerido === null ? l : { ...l, igv: sugerido }
    }))
  }

  // Bloque 12: al cambiar la clase o el comprobante, las líneas con una operación incompatible
  // pasan a la operación por defecto (COMPRA ↔ VENTA) y su IGV sugerido se recalcula.
  const ajustarOperacionesLineas = (clase: ClaseDocumento, comprobante: TipoComprobante | undefined) => {
    const tasa = tasaVigente(tasasIgv, formFechaEmision, tasaIgvActual)
    setLineas((prev) => reconciliarOperaciones(prev, tiposOperacion, clase, comprobante).map((l, i) => {
      if (l === prev[i] || l.esBonificacion) return l
      const sugerido = sugerirIgvLinea(l, tasa)
      return sugerido === null ? l : { ...l, igv: sugerido }
    }))
  }

  const cambiarClase = (clase: ClaseDocumento) => {
    if (clase === formClase) return
    setFormClase(clase)
    ajustarOperacionesLineas(clase, tipoCompSeleccionado)
    // Un proveedor que no es cliente (o al revés) no se arrastra a la otra clase.
    const tercero = terceros.find((t) => t.id === formTercero)
    if (tercero && !(clase === 'COMPRA' ? tercero.es_proveedor : tercero.es_cliente)) setFormTercero('')
    // El documento de origen de una nota es de la misma clase (el backend lo exige).
    if (formDocOrigen) {
      setFormDocOrigen('')
      setLineas((prev) => prev.map((l) => (l.detalleOrigenId ? { ...l, detalleOrigenId: '' } : l)))
    }
  }

  const cambiarTipoComprobante = (id: number | '') => {
    setFormTipoComprobante(id)
    ajustarOperacionesLineas(formClase, tiposComprobante.find((c) => c.id === id))
  }

  const actualizarLinea = async (tempId: string, campo: string, valor: unknown) => {
    setLineas((prev) =>
      prev.map((l) => {
        if (l.tempId !== tempId) return l
        const actualizada = { ...l, [campo]: valor }

        // Bloque 16: el producto sugiere su afectación de IGV y, en ventas, su precio de venta
        // (solo si la línea aún no tiene precio). Es una sugerencia editable; no toca el costo.
        if (campo === 'productoId' && valor && !actualizada.esBonificacion) {
          const prod = productos.find((p) => p.id === Number(valor))
          if (prod?.afectacion_igv_defecto && prod.afectacion_igv_defecto !== 'GRATUITO') {
            actualizada.afectacionIgv = prod.afectacion_igv_defecto
          }
          if (formClase === 'VENTA' && prod?.precio_venta_sugerido && !esMayorQueCero(actualizada.precioUnitario)) {
            actualizada.precioUnitario = prod.precio_venta_sugerido
          }
          const sugerido = sugerirIgvLinea(actualizada, tasaVigente(tasasIgv, formFechaEmision, tasaIgvActual))
          if (sugerido !== null) actualizada.igv = sugerido
        }

        if (campo === 'precioUnitario' || campo === 'cantidadOriginal' || campo === 'afectacionIgv' || campo === 'tipoOperacionId') {
          if (!actualizada.esBonificacion) {
            const sugerido = sugerirIgvLinea(actualizada, tasaVigente(tasasIgv, formFechaEmision, tasaIgvActual))
            if (sugerido !== null) actualizada.igv = sugerido
          }
        }

        if (campo === 'esBonificacion') {
          // Una bonificación es una transferencia gratuita (el backend lo exige).
          actualizada.afectacionIgv = valor === true ? 'GRATUITO' : 'GRAVADO'
          if (valor === true) {
            actualizada.precioUnitario = '0.00000000'
            actualizada.igv = '0.00000000'
          }
        }

        // B17A-QA-001: el código del Catálogo 07 solo se conserva si la línea sigue gratuita y es compatible.
        actualizada.codigoAfectacionIgv = reconciliarCodigoAfectacion(
          actualizada.afectacionIgv, actualizada.codigoAfectacionIgv, catalogo07)

        return actualizada
      })
    )

    if (campo === 'productoId' && valor) {
      try {
        const unidades = await getProductoUnidades(Number(valor))
        const unidadBase = unidades.find((u) => u.es_base) || unidades[0]
        setLineas((prev) =>
          prev.map((l) => {
            if (l.tempId !== tempId) return l
            return {
              ...l,
              unidadesDisponibles: unidades,
              productoUnidadId: unidadBase ? unidadBase.id : '',
              factorConversion: unidadBase ? unidadBase.factor_a_base : '1',
            }
          })
        )
      } catch {
        // Fallback silently
      }
    }

    if (campo === 'productoUnidadId' && valor) {
      setLineas((prev) =>
        prev.map((l) => {
          if (l.tempId !== tempId) return l
          const u = l.unidadesDisponibles.find((unit) => unit.id === Number(valor))
          return {
            ...l,
            factorConversion: u ? u.factor_a_base : '1',
          }
        })
      )
    }
  }

  // Totales en vivo
  // Los importes del formulario están en la moneda del comprobante (no se convierten a PEN aquí).
  const simboloMoneda = formMoneda === 'USD' ? 'US$' : 'S/'

  // Bloque 9: mismos totales que guardará el backend (decimal exacto, ROUND_HALF_UP).
  const totalesCalculados = useMemo(() => {
    const t = totalesDocumento(lineas.map((l) => ({ cantidad: l.cantidadOriginal, precio: l.precioUnitario, igv: l.igv })))
    return { subtotal: formatearDecimal(t.subtotal), igv: formatearDecimal(t.igv), total: formatearDecimal(t.total) }
  }, [lineas])

  const handleGuardarDocumento = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorGlobal(null)
    setExitoGlobal(null)
    setErrorModal(null)
    const falta = (mensaje: string) => mostrarErrorModal('nuevo', 'No se pudo registrar el comprobante', [mensaje])

    if (!formPeriodo) {
      falta('Debe seleccionar un período contable.')
      return
    }
    if (!formTipoComprobante) {
      falta('Debe seleccionar el tipo de comprobante.')
      return
    }
    if (!serieSeleccionada && !formSerie.trim()) {
      falta('Debe ingresar la serie del comprobante.')
      return
    }
    if (!serieSeleccionada && !formNumero.trim()) {
      falta('Debe ingresar el número del comprobante.')
      return
    }
    if (formClase === 'COMPRA' && !formTercero) {
      falta('Debe seleccionar el proveedor del comprobante.')
      return
    }
    if (esNota && !formDocOrigen) {
      falta('Las Notas de Crédito / Débito requieren seleccionar un documento de origen.')
      return
    }
    if (lineas.length === 0) {
      falta('Debe agregar al menos una línea de detalle.')
      return
    }

    for (let i = 0; i < lineas.length; i++) {
      const l = lineas[i]
      if (!l.productoId) {
        falta(`Línea ${i + 1}: Debe seleccionar un producto.`)
        return
      }
      if (!l.almacenId) {
        falta(`Línea ${i + 1}: Debe seleccionar un almacén.`)
        return
      }
      if (!l.tipoOperacionId) {
        falta(`Línea ${i + 1}: Debe seleccionar un tipo de operación.`)
        return
      }
      if (!esMayorQueCero(l.cantidadOriginal)) {
        falta(`Línea ${i + 1}: La cantidad debe ser mayor a 0.`)
        return
      }
    }
    // Bloque 12: operación compatible con la clase y el comprobante (el backend vuelve a validar).
    // B17A-QA-001: en ventas una línea gratuita exige su código del Catálogo 07.
    const errorGratuito = errorCodigoGratuito(
      lineas.map((l) => ({ afectacion: l.afectacionIgv, codigo: l.codigoAfectacionIgv })), formClase)
    if (errorGratuito) {
      falta(errorGratuito)
      return
    }
    const errorOperacion = errorDeOperaciones(lineas, tiposOperacion, formClase, tipoCompSeleccionado)
    if (errorOperacion) {
      falta(errorOperacion)
      return
    }
    // QA-001: devoluciones de una nota con su línea de origen y sin exceder lo disponible.
    if (esNota) {
      const errorNota = errorLineasNota(lineas.map((l) => {
        const op = tiposOperacion.find((t) => t.id === l.tipoOperacionId)
        return { ...l, naturaleza: op?.naturaleza, afectaKardex: op?.afecta_kardex ?? true }
      }), origenDetalles)
      if (errorNota) {
        falta(errorNota)
        return
      }
    }

    const condicion = esNota ? CONDICION_INICIAL : formCondicion
    const errorCondicion = errorCondicionPago({
      condicion: condicion.condicion, fechaVencimiento: condicion.fechaVencimiento, fechaEmision: formFechaEmision,
      cuotas: condicion.cuotas, total: totalesCalculados.total,
    })
    if (errorCondicion) {
      falta(errorCondicion)
      return
    }

    const payload: CrearDocumentoPayload = {
      clase: formClase,
      periodo: Number(formPeriodo),
      tipo_comprobante: Number(formTipoComprobante),
      ...(serieSeleccionada
        ? { serie_comprobante: serieSeleccionada.id }
        : { serie: formSerie.trim(), numero: formNumero.trim() }),
      motivo_nota: esNota && formMotivoNota ? formMotivoNota : undefined,
      condicion_pago: condicion.condicion,
      fecha_vencimiento: condicion.condicion === 'CREDITO' ? condicion.fechaVencimiento : null,
      cuotas: condicion.condicion === 'CREDITO' && condicion.cuotas.length > 0 ? condicion.cuotas : undefined,
      fecha_emision: formFechaEmision,
      moneda_codigo: formMoneda,
      tercero: formTercero ? Number(formTercero) : null,
      documento_origen: formDocOrigen ? Number(formDocOrigen) : null,
      origen_captura: 'MANUAL',
      detalles: lineas.map((l) => ({
        producto: Number(l.productoId),
        producto_unidad: l.productoUnidadId ? Number(l.productoUnidadId) : null,
        almacen: Number(l.almacenId),
        tipo_operacion: Number(l.tipoOperacionId),
        cantidad_original: l.cantidadOriginal,
        precio_unitario: l.precioUnitario,
        igv: l.igv,
        afectacion_igv: l.afectacionIgv,
        codigo_afectacion_igv: codigoAfectacionParaEnviar(l.afectacionIgv, l.codigoAfectacionIgv),
        es_bonificacion: l.esBonificacion,
        descripcion_original: l.descripcionOriginal,
        detalle_origen: l.detalleOrigenId ? Number(l.detalleOrigenId) : null,
      })),
    }

    setGuardandoDoc(true)
    try {
      const nuevoDoc = await crearDocumento(payload)
      setExitoGlobal(`Comprobante ${numeroComprobante(nuevoDoc)} registrado exitosamente.`)
      setModalNuevoAbierto(false)
      setFormSerie('')
      setFormNumero('')
      setFormCondicion(CONDICION_INICIAL)
      setFormMotivoNota('')
      setLineas([])
      await cargarDocumentos()
    } catch (err: unknown) {
      mostrarErrorModal('nuevo', 'No se pudo registrar el comprobante', mensajesDeErrorApi(err, 'Error al guardar el comprobante.'))
    } finally {
      setGuardandoDoc(false)
    }
  }

  const handleEjecutarRevision = async () => {
    if (!modalRevisionDoc) return
    setErrorGlobal(null)
    setErrorModal(null)
    try {
      await revisarDocumento(modalRevisionDoc.id, revEstadoSeleccionado, revMotivo)
      setExitoGlobal(`Estado de revisión actualizado a ${revEstadoSeleccionado}.`)
      setModalRevisionDoc(null)
      setRevMotivo('')
      await cargarDocumentos()
    } catch (err: unknown) {
      mostrarErrorModal('revision', 'No se pudo cambiar el estado de revisión', mensajesDeErrorApi(err, 'Error al cambiar estado de revisión.'))
    }
  }

  const handleConfirmar = async (doc: Documento) => {
    if (
      !window.confirm(
        `¿Confirmar el comprobante ${numeroComprobante(doc)}? Impactará stock en Kardex y no podrá volver a borrador.`
      )
    ) {
      return
    }
    setErrorGlobal(null)
    try {
      await confirmarDocumento(doc.id)
      setExitoGlobal(`Documento ${numeroComprobante(doc)} confirmado exitosamente en Kardex.`)
      await cargarDocumentos()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setErrorGlobal(axiosErr.response?.data?.detail || 'No se pudo confirmar el comprobante.')
    }
  }

  const handleEjecutarAnulacion = async () => {
    if (!modalAnulacionDoc || !anulacionMotivo.trim()) {
      mostrarErrorModal('anulacion', 'No se pudo anular el comprobante', ['Debe especificar un motivo de anulación.'])
      return
    }
    setErrorGlobal(null)
    setErrorModal(null)
    try {
      await anularDocumento(modalAnulacionDoc.id, anulacionMotivo.trim())
      setExitoGlobal(`Documento ${numeroComprobante(modalAnulacionDoc)} anulado con extorno.`)
      setModalAnulacionDoc(null)
      setAnulacionMotivo('')
      await cargarDocumentos()
    } catch (err: unknown) {
      mostrarErrorModal('anulacion', 'No se pudo anular el comprobante', mensajesDeErrorApi(err, 'Error al anular el documento.'))
    }
  }


  const documentosOrigenElegibles = useMemo(() => {
    return documentosOrigen.filter((d) => !d.es_nota && d.clase === formClase)
  }, [documentosOrigen, formClase])

  // La nota necesita elegir su comprobante de origen entre todos (no solo la página visible).
  const necesitaOrigen = modalNuevoAbierto && esNota
  useEffect(() => {
    if (!necesitaOrigen) return
    let ignorar = false
    obtenerDocumentos()
      .then((docs) => {
        if (!ignorar) setDocumentosOrigen(docs)
      })
      .catch(() => {
        if (!ignorar) setDocumentosOrigen([])
      })
    return () => {
      ignorar = true
    }
  }, [necesitaOrigen, empresaId])

  // QA-001: al elegir el comprobante de origen de una nota se cargan sus líneas (con lo que
  // queda por devolver de cada una) para elegir la línea de origen de cada línea de la nota.
  useEffect(() => {
    if (!necesitaOrigen || !formDocOrigen) {
      diferirCarga(() => setOrigenDetalles([]))
      return
    }
    let ignorar = false
    obtenerDocumento(Number(formDocOrigen))
      .then((doc) => {
        if (ignorar) return
        setOrigenDetalles((doc.detalles ?? [])
          .filter((d) => d.producto !== null)
          .map((d) => ({ ...d, producto: d.producto as number })))
      })
      .catch(() => {
        if (!ignorar) setOrigenDetalles([])
      })
    return () => {
      ignorar = true
    }
  }, [necesitaOrigen, formDocOrigen])

  const cambiarDocOrigen = (id: number | '') => {
    setFormDocOrigen(id)
    // Las líneas de origen elegidas eran del comprobante anterior.
    setLineas((prev) => prev.map((l) => (l.detalleOrigenId ? { ...l, detalleOrigenId: '' } : l)))
  }

  /** QA-001: precarga la línea de la nota con la línea de origen elegida. */
  const elegirLineaOrigen = async (tempId: string, valor: string) => {
    const origen = origenDetalles.find((d) => String(d.id) === valor)
    if (!origen) {
      setLineas((prev) => prev.map((l) => (l.tempId === tempId ? { ...l, detalleOrigenId: '' } : l)))
      return
    }
    let unidades: ProductoUnidad[] = []
    try {
      unidades = await getProductoUnidades(origen.producto)
    } catch {
      unidades = []
    }
    setLineas((prev) => prev.map((l) => {
      if (l.tempId !== tempId) return l
      const op = tiposOperacion.find((t) => t.id === l.tipoOperacionId)
      const fisica = esDevolucionFisica(op?.naturaleza, op?.afecta_kardex ?? true)
      const actualizada: LineaFormulario = {
        ...l,
        detalleOrigenId: origen.id,
        productoId: origen.producto,
        almacenId: origen.almacen,
        unidadesDisponibles: unidades.length ? unidades : l.unidadesDisponibles,
        productoUnidadId: origen.producto_unidad ?? l.productoUnidadId,
        factorConversion: origen.factor_conversion,
        ...(fisica ? {
          // Devolución: por defecto todo lo que queda, al precio de la línea de origen.
          cantidadOriginal: disponibleEnUnidad(origen),
          precioUnitario: origen.precio_unitario,
          afectacionIgv: (origen.afectacion_igv as AfectacionIgv) || l.afectacionIgv,
          codigoAfectacionIgv: origen.codigo_afectacion_igv ?? '',
        } : {}),
      }
      actualizada.codigoAfectacionIgv = reconciliarCodigoAfectacion(
        actualizada.afectacionIgv, actualizada.codigoAfectacionIgv, catalogo07)
      if (!actualizada.esBonificacion) {
        const sugerido = sugerirIgvLinea(actualizada, tasaVigente(tasasIgv, formFechaEmision, tasaIgvActual))
        if (sugerido !== null) actualizada.igv = sugerido
      }
      return actualizada
    }))
  }

  // Abre el formulario de nuevo comprobante con la clase de la vista (Compras/Ventas).
  const abrirNuevo = () => {
    const clase = claseInicialNuevo(tabComprobantes ?? 'TODOS', formClase)
    cambiarClase(clase)
    setErrorModal(null)
    setModalNuevoAbierto(true)
    if (lineas.length === 0) setLineas([lineaVacia(clase)])
  }

  // Acceso rápido del Dashboard: /comprobantes?clase=COMPRA&nuevo=1 abre el formulario directamente
  // (y /compras?nuevo=1, que redirige ahí conservando el parámetro).
  // Espera a los catálogos para que la primera línea tenga almacén y tipo de operación.
  const pedirNuevo = searchParams.get('nuevo') === '1'
  useEffect(() => {
    if (!pedirNuevo || !catalogosCargados) return
    diferirCarga(() => {
      const clase = claseInicialNuevo(tabComprobantes ?? 'TODOS', formClase)
      setFormClase(clase)
      setErrorModal(null)
      setModalNuevoAbierto(true)
      setLineas((actuales) => (actuales.length === 0
        ? [lineaVacia(clase)]
        : reconciliarOperaciones(actuales, tiposOperacion, clase, tipoCompSeleccionado)))
      // Se quita solo `nuevo`: la pestaña (?clase=) se conserva.
      const resto = new URLSearchParams(searchParams)
      resto.delete('nuevo')
      setSearchParams(resto, { replace: true })
    })
  }, [pedirNuevo, catalogosCargados, tabComprobantes, searchParams, setSearchParams, lineaVacia, formClase, tiposOperacion, tipoCompSeleccionado])

  const tiposComprobanteFormulario = tiposComprobanteDeVista(vista, tiposComprobante)
  const alertaNuevo = alertaDe('nuevo')
  const alertaRevision = alertaDe('revision')
  const alertaAnulacion = alertaDe('anulacion')

  return (
    <div className="space-y-6">
      <PageHeader
        title={configVista.titulo}
        description={configVista.descripcion}
        icon={<FileSpreadsheet className="h-5 w-5" />}
        actions={
          <Button variant="primary" onClick={abrirNuevo}>
            <Plus className="h-4 w-4 mr-1.5" /> {configVista.botonNuevo}
          </Button>
        }
      />

      {errorGlobal && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50/90 p-3.5 text-xs text-rose-700 animate-in fade-in"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{errorGlobal}</span>
        </div>
      )}

      {exitoGlobal && (
        <div
          role="status"
          className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50/90 p-3.5 text-xs text-emerald-700 animate-in fade-in"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{exitoGlobal}</span>
        </div>
      )}

      {/* Bloque 13: una sola pantalla para compras y ventas (misma tabla, mismos filtros). */}
      {tabComprobantes && (
        <Tabs value={tabComprobantes} onValueChange={cambiarTab}>
          <TabsList aria-label="Clase de comprobante">
            {TABS_COMPROBANTES.map((t) => (
              <TabsTrigger key={t.valor} value={t.valor} role="tab" aria-selected={tabComprobantes === t.valor}>
                {t.etiqueta}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      )}

      {/* Barra de Filtros */}
      <Card>
        <CardContent className="p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {vista === 'NOTAS' && (
              <div className="space-y-1">
                <Label>Clase</Label>
                <Select
                  value={filtroClaseNotas}
                  onChange={(e) => setFiltroClaseNotas(e.target.value as ClaseDocumento | '')}
                >
                  <option value="">Todas las clases</option>
                  <option value="COMPRA">Compras</option>
                  <option value="VENTA">Ventas</option>
                </Select>
              </div>
            )}

            <div className="space-y-1">
              <Label>Período</Label>
              <Select
                value={filtroPeriodo}
                onChange={(e) => setFiltroPeriodo(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">Todos los períodos</option>
                {periodos.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.anio}-{String(p.mes).padStart(2, '0')} ({p.estado})
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1">
              <Label>Estado Documental</Label>
              <Select
                value={filtroEstado}
                onChange={(e) => setFiltroEstado(e.target.value as EstadoDocumental | '')}
              >
                <option value="">Todos los estados</option>
                <option value="BORRADOR">Borrador</option>
                <option value="CONFIRMADO">Confirmado</option>
                <option value="ANULADO">Anulado</option>
              </Select>
            </div>

            <div className="space-y-1">
              <Label>Mesa de Revisión</Label>
              <Select
                value={filtroRevision}
                onChange={(e) => setFiltroRevision(e.target.value as EstadoRevision | '')}
              >
                <option value="">Todas las revisiones</option>
                <option value="PENDIENTE">PENDIENTE</option>
                <option value="EN_REVISION">EN REVISIÓN</option>
                <option value="REVISADO">REVISADO (Aprobado)</option>
                <option value="OBSERVADO">OBSERVADO</option>
              </Select>
            </div>

            <div className="space-y-1 sm:col-span-2 lg:col-span-2">
              <Label>Buscar Comprobante / RUC / Tercero</Label>
              <Input
                placeholder="F001-123, 2060..., EMPRESA..."
                value={filtroBusqueda}
                onChange={(e) => setFiltroBusqueda(e.target.value)}
                leftIcon={<Search className="h-4 w-4" />}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Tabla de Documentos */}
      <Card>
        <CardContent className="p-0">
          <div className="flex items-center justify-between p-3 px-4 border-b border-slate-100 bg-slate-50/50">
            <span className="text-xs font-semibold text-slate-600">
              Total <strong className="font-mono text-slate-900">{totalDocumentos}</strong> comprobantes
            </span>
            {cargando && <span className="text-xs text-slate-400">Actualizando datos...</span>}
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-20">Clase</TableHead>
                <TableHead className="w-40">Comprobante</TableHead>
                <TableHead className="w-24">Emisión</TableHead>
                <TableHead>Proveedor / Cliente</TableHead>
                <TableHead className="w-28">Moneda / TC</TableHead>
                <TableHead numeric className="w-28">Subtotal</TableHead>
                <TableHead numeric className="w-24">IGV</TableHead>
                <TableHead numeric className="w-28">Total</TableHead>
                <TableHead className="w-32">Revisión</TableHead>
                <TableHead className="w-28">Estado</TableHead>
                <TableHead className="w-36">SUNAT</TableHead>
                <TableHead className="w-36 text-center">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documentos.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={12} className="text-center py-10 text-slate-400 text-xs">
                    No se encontraron comprobantes registrados para los filtros seleccionados.
                  </TableCell>
                </TableRow>
              ) : (
                documentos.map((doc) => {
                  const esCompra = doc.clase === 'COMPRA'
                  const revVariant =
                    doc.estado_revision === 'REVISADO'
                      ? 'success'
                      : doc.estado_revision === 'OBSERVADO'
                      ? 'destructive'
                      : doc.estado_revision === 'EN_REVISION'
                      ? 'warning'
                      : 'neutral'

                  const docVariant =
                    doc.estado === 'CONFIRMADO'
                      ? 'success'
                      : doc.estado === 'ANULADO'
                      ? 'destructive'
                      : 'warning'

                  return (
                    <TableRow key={doc.id}>
                      <TableCell>
                        <Badge variant={esCompra ? 'info' : 'success'} size="sm">
                          {doc.clase}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5 flex-wrap font-mono tabular-nums">
                          <span className="font-bold text-slate-900">
                            {doc.tipo_comprobante_codigo || 'DOC'}: {numeroComprobante(doc)}
                          </span>
                          {doc.es_nota && <Badge variant="warning" size="sm">NOTA</Badge>}
                        </div>
                      </TableCell>
                      <TableCell numeric className="text-slate-600">
                        {doc.fecha_emision}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col items-start gap-0.5">
                          <span className="font-semibold text-slate-900 text-xs truncate max-w-xs">
                            {contraparteDocumento(doc).nombre}
                          </span>
                          <span className="font-mono text-[10px] text-slate-400" data-testid="contraparte-documento">
                            {contraparteDocumento(doc).etiquetaDocumento}: {contraparteDocumento(doc).documento}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col items-start gap-0.5">
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-100 text-slate-700 border border-slate-200/60">{doc.moneda_codigo}</span>
                          {doc.moneda_codigo === 'USD' && (
                            <span className="font-mono text-[10px] text-slate-500">
                              TC: {formatearDecimal(doc.monto_tc, { min: 4, max: 4, vacio: '-' })}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell numeric className="font-medium text-slate-800">
                        {formatearDecimal(doc.subtotal)}
                      </TableCell>
                      <TableCell numeric className="text-slate-600">
                        {formatearDecimal(doc.igv)}
                      </TableCell>
                      <TableCell numeric className="font-bold text-slate-950 text-sm">
                        {formatearDecimal(doc.total)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={revVariant} size="sm" dot>
                          {doc.estado_revision}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={docVariant} size="sm">
                          {doc.estado}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {doc.emision_electronica_resumen ? (
                          <div className="flex flex-col items-start gap-0.5">
                            <Badge variant={doc.emision_electronica_resumen.estado === 'RECHAZADO' ? 'destructive'
                              : doc.emision_electronica_resumen.estado.startsWith('ACEPTADO') ? 'success' : 'neutral'} size="sm">
                              {doc.emision_electronica_resumen.estado}
                            </Badge>
                            <span className="text-[10px] text-slate-500">
                              {doc.emision_electronica_resumen.ambiente}
                              {doc.emision_electronica_resumen.pdf_disponible ? ' · PDF' : ''}
                            </span>
                          </div>
                        ) : <span className="text-xs text-slate-400">No preparado</span>}
                      </TableCell>
                      <TableCell className="text-center">
                        <div className="flex items-center justify-center gap-1">
                          {/* Ver Detalle */}
                          <Button
                            type="button"
                            size="icon-sm"
                            variant="ghost"
                            title="Ver Detalle Completo"
                            onClick={async () => {
                              const fullDoc = await obtenerDocumento(doc.id)
                              setModalDetalleDocumento(fullDoc)
                            }}
                          >
                            <Eye className="h-3.5 w-3.5 text-slate-600" />
                          </Button>

                          {/* Mesa de Revisión */}
                          {doc.estado === 'BORRADOR' && (
                            <Button
                              type="button"
                              size="icon-sm"
                              variant="ghost"
                              className="hover:bg-indigo-50 hover:text-indigo-600 transition-colors"
                              title="Mesa de Revisión Contable"
                              onClick={() => {
                                setErrorModal(null)
                                setModalRevisionDoc(doc)
                                setRevEstadoSeleccionado(
                                  doc.estado_revision === 'PENDIENTE' ? 'REVISADO' : doc.estado_revision
                                )
                              }}
                            >
                              <CheckCheck className="h-3.5 w-3.5 text-indigo-600" />
                            </Button>
                          )}

                          {/* Confirmar Documento */}
                          {doc.estado === 'BORRADOR' && doc.estado_revision === 'REVISADO' && (
                            <Button
                              type="button"
                              size="icon-sm"
                              variant="ghost"
                              className="bg-emerald-50 hover:bg-emerald-600 text-emerald-700 hover:text-white border border-emerald-200/90 transition-all shadow-2xs"
                              title="Confirmar e Impactar Kardex"
                              onClick={() => handleConfirmar(doc)}
                            >
                              <CheckCircle2 className="h-3.5 w-3.5" />
                            </Button>
                          )}

                          {/* Anular Documento */}
                          {doc.estado !== 'ANULADO' && (
                            <Button
                              type="button"
                              size="icon-sm"
                              variant="ghost"
                              className="hover:bg-rose-50 hover:text-rose-600 transition-colors"
                              title="Anular con Extorno"
                              onClick={() => {
                                setErrorModal(null)
                                setModalAnulacionDoc(doc)
                              }}
                            >
                              <Ban className="h-3.5 w-3.5 text-rose-600" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
          {totalDocumentos > 0 && (
            <Paginacion
              page={page}
              pageSize={PAGE_SIZE_DEFECTO}
              count={totalDocumentos}
              enPagina={documentos.length}
              cargando={cargando}
              etiqueta="comprobantes"
              onCambiarPagina={(nueva) => setEstadoPagina(irAPagina(claveFiltros, nueva))}
            />
          )}
        </CardContent>
      </Card>

      {/* MODAL: NUEVO COMPROBANTE MAESTRO-DETALLE */}
      {modalNuevoAbierto && (
        <Modal
          isOpen={modalNuevoAbierto}
          onClose={() => setModalNuevoAbierto(false)}
          maxWidth="7xl"
          className="max-w-[96vw] 2xl:max-w-[1720px] max-h-[94vh] w-full"
          icon={<Receipt className="h-5 w-5" />}
          title="Registrar Comprobante Comercial"
          description="Captura manual de facturas, boletas y notas de crédito/débito con validación estricta."
          footer={
            <div className="flex w-full flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 font-mono tabular-nums">
                <div className="flex items-baseline gap-1.5 text-xs">
                  <dt className="text-slate-500">Subtotal:</dt>
                  <dd className="font-semibold text-slate-800">{simboloMoneda} {totalesCalculados.subtotal}</dd>
                </div>
                <div className="flex items-baseline gap-1.5 text-xs">
                  <dt className="text-slate-500">IGV:</dt>
                  <dd className="font-semibold text-slate-800">{simboloMoneda} {totalesCalculados.igv}</dd>
                </div>
                <div className="flex items-baseline gap-1.5 text-xs">
                  <dt className="font-semibold text-slate-700">Total:</dt>
                  <dd className="text-base font-bold text-slate-950">{simboloMoneda} {totalesCalculados.total}</dd>
                </div>
              </dl>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setModalNuevoAbierto(false)}>
                  Cancelar
                </Button>
                <Button variant="primary" onClick={handleGuardarDocumento} isLoading={guardandoDoc}>
                  Guardar Borrador
                </Button>
              </div>
            </div>
          }
        >
          <form onSubmit={handleGuardarDocumento} className="space-y-6">
            {alertaNuevo && <AlertaFormulario ref={alertaModalRef} titulo={alertaNuevo.titulo} mensajes={alertaNuevo.mensajes} />}

            {/* Cabecera */}
            <div className="space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 border-b border-slate-100 pb-1">
                1. Cabecera del Documento
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3.5">
                <div className="space-y-1">
                  <Label required>Clase de Operación</Label>
                  <Select
                    value={formClase}
                    onChange={(e) => cambiarClase(e.target.value as ClaseDocumento)}
                  >
                    <option value="COMPRA">COMPRA (Entrada)</option>
                    <option value="VENTA">VENTA (Salida)</option>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label required>Período Contable</Label>
                  <Select
                    value={formPeriodo}
                    onChange={(e) => setFormPeriodo(Number(e.target.value))}
                    required
                  >
                    <option value="">Seleccione Período...</option>
                    {periodos.map((p) => (
                      <option key={p.id} value={p.id} disabled={p.estado === 'CERRADO'}>
                        {p.anio}-{String(p.mes).padStart(2, '0')} ({p.estado})
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label required>Tipo de Comprobante</Label>
                  <Select
                    value={formTipoComprobante}
                    onChange={(e) => cambiarTipoComprobante(e.target.value ? Number(e.target.value) : '')}
                    required
                  >
                    <option value="">Seleccione Tipo...</option>
                    {tiposComprobanteFormulario.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.codigo_sunat} - {c.descripcion} {c.es_nota ? '(Nota)' : ''}
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label required={formClase === 'COMPRA'}>
                    {formClase === 'COMPRA' ? 'Proveedor' : 'Cliente (Opcional)'}
                  </Label>
                  <Select
                    value={formTercero}
                    onChange={(e) => setFormTercero(e.target.value ? Number(e.target.value) : '')}
                    required={formClase === 'COMPRA'}
                  >
                    <option value="">Seleccione Tercero...</option>
                    {terceros
                      .filter((t) => (formClase === 'COMPRA' ? t.es_proveedor : t.es_cliente))
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.numero_documento} - {t.razon_social}
                        </option>
                      ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label>RUC Emisor Resuelto</Label>
                  <Input disabled value={rucEmisorDisplay} className="bg-slate-50 font-mono" />
                </div>

                {seriesDisponibles.length > 0 && (
                  <div className="space-y-1">
                    <Label required htmlFor="serie-comprobante-select">Serie</Label>
                    <Select
                      id="serie-comprobante-select"
                      value={formSerieId}
                      onChange={(e) => setFormSerieId(e.target.value ? Number(e.target.value) : '')}
                    >
                      {seriesDisponibles.map((x) => (
                        <option key={x.id} value={x.id}>{x.serie} — {x.establecimiento_nombre}</option>
                      ))}
                      <option value="">Otra serie (número manual)</option>
                    </Select>
                  </div>
                )}

                {serieSeleccionada ? (
                  <div className="space-y-1">
                    <Label>Número</Label>
                    <Input
                      disabled
                      value={`Automático (siguiente ${serieSeleccionada.serie}-${serieSeleccionada.siguiente_numero})`}
                      className="bg-slate-50 font-mono tabular-nums"
                      data-testid="numero-automatico"
                    />
                  </div>
                ) : (
                  <>
                    <div className="space-y-1">
                      <Label required>{seriesDisponibles.length > 0 ? 'Serie manual' : 'Serie'}</Label>
                      <Input
                        placeholder="F001"
                        value={formSerie}
                        onChange={(e) => setFormSerie(e.target.value)}
                        required
                        className="font-mono uppercase"
                      />
                    </div>

                    <div className="space-y-1">
                      <Label required>Número</Label>
                      <Input
                        placeholder="12345"
                        value={formNumero}
                        onChange={(e) => setFormNumero(e.target.value)}
                        required
                        className="font-mono tabular-nums"
                      />
                    </div>
                  </>
                )}

                <div className="space-y-1">
                  <Label required>Fecha de Emisión</Label>
                  <Input
                    type="date"
                    value={formFechaEmision}
                    onChange={(e) => cambiarFechaEmision(e.target.value)}
                    required
                    className="font-mono tabular-nums"
                  />
                </div>

                <div className="space-y-1">
                  <Label required>Moneda</Label>
                  <Select
                    value={formMoneda}
                    onChange={(e) => setFormMoneda(e.target.value as 'PEN' | 'USD')}
                  >
                    <option value="PEN">PEN — Soles Peruanos</option>
                    <option value="USD">USD — Dólares Americanos</option>
                  </Select>
                </div>

                {formMoneda === 'USD' && (
                  <div className="space-y-1 sm:col-span-2 xl:col-span-1">
                    <Label>TC Venta SBS {cargandoTc && '⏳'}</Label>
                    <Input
                      disabled
                      value={
                        tcResuelto
                          ? `${formatearDecimal(tcResuelto.venta, { min: 4, max: 4 })} (${tcResuelto.fecha_publicacion})`
                          : 'Sin TC registrado a la fecha'
                      }
                      className={tcResuelto ? 'text-emerald-700 font-bold font-mono' : 'text-rose-600 font-mono'}
                    />
                  </div>
                )}

                {esNota && (
                  <div className="space-y-1 sm:col-span-2 lg:col-span-3 xl:col-span-2">
                    <Label required>Documento de Origen Referenciado (Obligatorio para NC/ND)</Label>
                    <Select
                      value={formDocOrigen}
                      onChange={(e) => cambiarDocOrigen(e.target.value ? Number(e.target.value) : '')}
                      required
                    >
                      <option value="">Seleccione Factura / Boleta de Origen...</option>
                      {documentosOrigenElegibles.map((orig) => (
                        <option key={orig.id} value={orig.id}>
                          {numeroComprobante(orig)} ({orig.fecha_emision}) - {orig.tercero_razon_social} - {orig.moneda_codigo} {orig.total}
                        </option>
                      ))}
                    </Select>
                  </div>
                )}

                {esNota && catalogoMotivoForm && (
                  <div className="space-y-1 sm:col-span-2">
                    <Label htmlFor="motivo-nota-select">Motivo tributario (catálogo {catalogoMotivoForm})</Label>
                    <Select id="motivo-nota-select" value={formMotivoNota} onChange={(e) => setFormMotivoNota(e.target.value)}>
                      <option value="">Sin motivo (se exigirá antes de la emisión electrónica)</option>
                      {motivosNota.map((m) => (
                        <option key={m.codigo} value={m.codigo}>{m.codigo} — {m.descripcion}</option>
                      ))}
                    </Select>
                  </div>
                )}
              </div>
            </div>

            {/* Líneas de Detalle */}
            <div className="space-y-3">
              <div className="flex items-center justify-between border-b border-slate-100 pb-1.5">
                <div className="flex items-center gap-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
                    2. Líneas de Detalle del Comprobante
                  </h4>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                    {lineas.length} {lineas.length === 1 ? 'línea' : 'líneas'}
                  </span>
                </div>
                <Button type="button" variant="secondary" size="xs" onClick={agregarLinea}>
                  <Plus className="h-3.5 w-3.5 mr-1" /> Agregar Línea
                </Button>
              </div>

              {/* Bloque 10: la tabla conserva anchos legibles y se desplaza SOLO dentro de esta
                  sección (min-w-0 evita que estire el modal o la página). */}
              <div className="min-w-0 overflow-x-auto rounded-xl border border-slate-200/90 bg-white shadow-2xs">
                <table className="w-full min-w-[1600px] text-xs text-left border-collapse">
                  <thead className="bg-slate-50/90 border-b border-slate-200 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                    <tr>
                      <th className="px-3 py-2.5 w-10 text-center">#</th>
                      {esNota && <th className="px-3 py-2.5 min-w-[260px]">Línea de origen</th>}
                      <th className="px-3 py-2.5 min-w-[300px]">Producto *</th>
                      <th className="px-3 py-2.5 min-w-[150px]">Unidad presentación *</th>
                      <th className="px-3 py-2.5 min-w-[160px]">Almacén *</th>
                      <th className="px-3 py-2.5 min-w-[180px]">Operación *</th>
                      <th className="px-3 py-2.5 min-w-[130px] text-right">Cantidad</th>
                      <th className="px-3 py-2.5 min-w-[145px] text-right whitespace-nowrap">
                        <span className="hidden sm:inline">Precio unitario</span>
                        <span className="sm:hidden">Precio unit.</span>
                      </th>
                      <th className="px-3 py-2.5 min-w-[185px]">Afectación IGV</th>
                      <th className="px-3 py-2.5 min-w-[130px] text-right">IGV</th>
                      <th className="px-3 py-2.5 min-w-[70px] text-center">Bonif.</th>
                      <th className="px-3 py-2.5 min-w-[130px] text-right whitespace-nowrap">
                        <span className="hidden sm:inline">Cantidad base</span>
                        <span className="sm:hidden">Cant. base</span>
                      </th>
                      <th className="px-2 py-2.5 w-10 text-center"><span className="sr-only">Eliminar</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {lineas.map((linea, idx) => {
                      const cantBase = formatearDecimal(cantidadBase(linea.cantidadOriginal, linea.factorConversion), { min: 2, max: 6 })

                      return (
                        <tr key={linea.tempId} className="hover:bg-slate-50/80 focus-within:bg-slate-50/60 transition-colors">
                          <td className="px-3 py-2.5 text-center font-mono text-slate-400 font-semibold">{idx + 1}</td>
                          {esNota && (
                            <td className="px-3 py-2.5">
                              <select
                                aria-label={`Línea de origen de la línea ${idx + 1}`}
                                className={CLASE_SELECT_TABLA}
                                value={linea.detalleOrigenId ?? ''}
                                onChange={(e) => elegirLineaOrigen(linea.tempId, e.target.value)}
                                disabled={!formDocOrigen}
                              >
                                <option value="">
                                  {!formDocOrigen ? 'Elija el comprobante de origen' : 'Sin línea (solo descuento / ajuste)'}
                                </option>
                                {origenDetalles
                                  .filter((d) => lineasOrigenElegibles([d]).length > 0 || d.id === Number(linea.detalleOrigenId))
                                  .map((d) => (
                                    <option key={d.id} value={d.id}>{etiquetaLineaOrigen(d)}</option>
                                  ))}
                              </select>
                            </td>
                          )}
                          <td className="px-3 py-2.5">
                            <select
                              className={CLASE_SELECT_TABLA}
                              value={linea.productoId}
                              onChange={(e) => actualizarLinea(linea.tempId, 'productoId', e.target.value)}
                              required
                            >
                              <option value="">Seleccione Producto...</option>
                              {productos.map((prod) => (
                                <option key={prod.id} value={prod.id}>
                                  {prod.codigo_interno} - {prod.descripcion}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-2.5">
                            <select
                              className={CLASE_SELECT_TABLA}
                              value={linea.productoUnidadId}
                              onChange={(e) => actualizarLinea(linea.tempId, 'productoUnidadId', e.target.value)}
                              required
                            >
                              <option value="">Unidad...</option>
                              {linea.unidadesDisponibles.map((u) => (
                                <option key={u.id} value={u.id}>
                                  {u.unidad_codigo} (x{u.factor_a_base})
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-2.5">
                            <select
                              className={CLASE_SELECT_TABLA}
                              value={linea.almacenId}
                              onChange={(e) => actualizarLinea(linea.tempId, 'almacenId', e.target.value)}
                              required
                            >
                              {almacenes.map((alm) => (
                                <option key={alm.id} value={alm.id}>
                                  {alm.codigo} - {alm.nombre}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-2.5">
                            <select
                              className={CLASE_SELECT_TABLA}
                              value={linea.tipoOperacionId}
                              onChange={(e) => actualizarLinea(linea.tempId, 'tipoOperacionId', e.target.value ? Number(e.target.value) : '')}
                              required
                            >
                              {operacionesLinea.map((op) => (
                                <option key={op.id} value={op.id}>
                                  {op.codigo_interno} - {op.descripcion}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-3 py-2.5">
                            <input
                              type="number"
                              inputMode="decimal"
                              step="any"
                              min="0"
                              placeholder="0.000000"
                              className={CLASE_INPUT_NUMERICO}
                              value={linea.cantidadOriginal}
                              onChange={(e) => actualizarLinea(linea.tempId, 'cantidadOriginal', e.target.value)}
                              required
                            />
                          </td>
                          <td className="px-3 py-2.5">
                            <input
                              type="number"
                              inputMode="decimal"
                              step="any"
                              min="0"
                              placeholder="0.000000"
                              disabled={linea.esBonificacion}
                              className={CLASE_INPUT_NUMERICO}
                              value={linea.precioUnitario}
                              onChange={(e) => actualizarLinea(linea.tempId, 'precioUnitario', e.target.value)}
                              required
                            />
                          </td>
                          <td className="px-3 py-2.5">
                            <select
                              className={CLASE_SELECT_TABLA}
                              value={linea.afectacionIgv}
                              disabled={linea.esBonificacion}
                              onChange={(e) => actualizarLinea(linea.tempId, 'afectacionIgv', e.target.value)}
                            >
                              {AFECTACIONES_IGV.map((a) => (
                                <option key={a.valor} value={a.valor}>{a.etiqueta}</option>
                              ))}
                            </select>
                            {linea.afectacionIgv === 'GRATUITO' && (
                              <select
                                aria-label={`Código Catálogo 07 de la línea ${idx + 1}`}
                                data-testid="codigo-afectacion-linea"
                                title={opcionesGratuitas.find((c) => c.codigo === linea.codigoAfectacionIgv)?.descripcion
                                  ?? 'Código SUNAT (Catálogo 07) de la operación gratuita'}
                                className={`mt-1 w-full h-8 rounded border bg-white px-2 text-xs focus:ring-1 focus:ring-slate-900 ${
                                  !linea.codigoAfectacionIgv && formClase === 'VENTA' ? 'border-amber-400' : 'border-slate-200'}`}
                                value={linea.codigoAfectacionIgv}
                                onChange={(e) => actualizarLinea(linea.tempId, 'codigoAfectacionIgv', e.target.value)}
                              >
                                <option value="">{formClase === 'VENTA' ? 'Código Cat. 07 (obligatorio)…' : 'Código Cat. 07 (opcional)…'}</option>
                                {opcionesGratuitas.map((c) => (
                                  <option key={c.codigo} value={c.codigo}>{c.codigo} — {c.descripcion}</option>
                                ))}
                              </select>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <input
                              type="number"
                              inputMode="decimal"
                              step="any"
                              min="0"
                              placeholder="0.00"
                              disabled={linea.esBonificacion || !igvEditable(linea.afectacionIgv)}
                              className={CLASE_INPUT_NUMERICO}
                              value={linea.igv}
                              onChange={(e) => actualizarLinea(linea.tempId, 'igv', e.target.value)}
                            />
                          </td>
                          <td className="px-3 py-2.5 text-center">
                            <input
                              type="checkbox"
                              checked={linea.esBonificacion}
                              onChange={(e) => actualizarLinea(linea.tempId, 'esBonificacion', e.target.checked)}
                              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                            />
                          </td>
                          <td className="px-3 py-2.5 text-right whitespace-nowrap">
                            <span className="inline-block bg-slate-100/70 border border-slate-200/60 rounded px-2 py-0.5 text-slate-700 font-mono tabular-nums font-semibold text-xs">
                              {cantBase}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 text-center">
                            <button
                              type="button"
                              onClick={() => eliminarLinea(linea.tempId)}
                              className="text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded p-1.5 transition-colors cursor-pointer"
                              title="Eliminar fila"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Bloque 16: condición de pago */}
            <div className="space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 border-b border-slate-100 pb-1">
                3. Condición de Pago
              </h4>
              <CondicionPagoCampos
                valor={formCondicion}
                onChange={setFormCondicion}
                fechaEmision={formFechaEmision}
                total={totalesCalculados.total}
                simboloMoneda={simboloMoneda}
                esNota={esNota}
              />
            </div>
          </form>
        </Modal>
      )}

      {/* MODAL: VER DETALLE COMPLETO */}
      {modalDetalleDocumento && (
        <Modal
          isOpen={Boolean(modalDetalleDocumento)}
          onClose={() => setModalDetalleDocumento(null)}
          maxWidth="4xl"
          icon={<Eye className="h-5 w-5" />}
          title={`Detalle de Comprobante: ${numeroComprobante(modalDetalleDocumento)}`}
          description={`Clase: ${modalDetalleDocumento.clase} • Estado: ${modalDetalleDocumento.estado} • Revisión: ${modalDetalleDocumento.estado_revision}`}
          footer={
            <Button variant="secondary" onClick={() => setModalDetalleDocumento(null)}>
              Cerrar Visor
            </Button>
          }
        >
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs bg-slate-50 p-3 rounded-lg border border-slate-200">
              <div>
                <span className="text-slate-400 block">
                  {contraparteDocumento(modalDetalleDocumento).rol} ({contraparteDocumento(modalDetalleDocumento).etiquetaDocumento}):
                </span>
                <strong className="font-mono text-slate-800" data-testid="detalle-contraparte-documento">
                  {contraparteDocumento(modalDetalleDocumento).documento}
                </strong>
              </div>
              <div>
                <span className="text-slate-400 block">{contraparteDocumento(modalDetalleDocumento).rol} / Razón Social:</span>
                <strong className="text-slate-800">{contraparteDocumento(modalDetalleDocumento).nombre}</strong>
              </div>
              <div>
                <span className="text-slate-400 block">Fecha Emisión:</span>
                <strong className="font-mono text-slate-800">{modalDetalleDocumento.fecha_emision}</strong>
              </div>
              <div>
                <span className="text-slate-400 block">Moneda / Total:</span>
                <strong className="font-mono text-slate-900 text-sm">
                  {modalDetalleDocumento.moneda_codigo} {formatearDecimal(modalDetalleDocumento.total)}
                </strong>
              </div>
            </div>

            <div className="space-y-2">
              <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wider">Líneas de Detalle</h4>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Producto</TableHead>
                    <TableHead>Almacén</TableHead>
                    <TableHead numeric>Cantidad</TableHead>
                    <TableHead numeric>Precio Unit.</TableHead>
                    <TableHead numeric>IGV</TableHead>
                    <TableHead numeric>Subtotal</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {modalDetalleDocumento.detalles?.map((det) => (
                    <TableRow key={det.id}>
                      <TableCell className="font-semibold text-slate-800">
                        {det.producto_codigo} — {det.producto_descripcion}
                      </TableCell>
                      <TableCell>{det.almacen_nombre || det.almacen}</TableCell>
                      <TableCell numeric className="font-bold">
                        {formatearDecimal(det.cantidad_original, { min: 2, max: 8 })}
                      </TableCell>
                      <TableCell numeric>
                        {formatearDecimal(det.precio_unitario, { min: 4, max: 8 })}
                      </TableCell>
                      <TableCell numeric>
                        {formatearDecimal(det.igv)}
                        {det.afectacion_igv && det.afectacion_igv !== 'GRAVADO' && (
                          <span className="ml-1 text-[10px] text-slate-500">{det.afectacion_igv}</span>
                        )}
                        {det.afectacion_igv === 'GRATUITO' && (
                          <CodigoAfectacionLinea
                            key={`${det.id}-${det.codigo_afectacion_igv ?? ''}`}
                            documento={modalDetalleDocumento}
                            detalle={det}
                            opciones={opcionesGratuitas}
                            catalogo={catalogo07}
                            editable={esAdmin && modalDetalleDocumento.estado !== 'ANULADO'}
                            onActualizado={setModalDetalleDocumento}
                          />
                        )}
                      </TableCell>
                      <TableCell numeric className="font-bold text-slate-900">
                        {formatearDecimal(importeLinea(det.cantidad_original, det.precio_unitario))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <PagosDocumento
              documento={modalDetalleDocumento}
              esAdmin={esAdmin}
              onActualizado={async () => {
                setModalDetalleDocumento(await obtenerDocumento(modalDetalleDocumento.id))
                await cargarDocumentos()
              }}
            />
          </div>
        </Modal>
      )}

      {/* MODAL: MESA DE REVISIÓN */}
      {modalRevisionDoc && (
        <Modal
          isOpen={Boolean(modalRevisionDoc)}
          onClose={() => setModalRevisionDoc(null)}
          title={`Mesa de Revisión: ${numeroComprobante(modalRevisionDoc)}`}
          description="Dictamen formal previo a la confirmación de inventario en Kardex."
          icon={<CheckCheck className="h-5 w-5 text-indigo-600" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setModalRevisionDoc(null)}>
                Cancelar
              </Button>
              <Button variant="primary" onClick={handleEjecutarRevision}>
                Guardar Dictamen
              </Button>
            </div>
          }
        >
          <div className="space-y-4">
            {alertaRevision && <AlertaFormulario ref={alertaModalRef} titulo={alertaRevision.titulo} mensajes={alertaRevision.mensajes} />}
            <div className="space-y-1.5">
              <Label required>Nuevo Estado de Revisión</Label>
              <Select
                value={revEstadoSeleccionado}
                onChange={(e) => setRevEstadoSeleccionado(e.target.value as EstadoRevision)}
              >
                <option value="REVISADO">REVISADO (Aprobado para confirmación en Kardex)</option>
                <option value="OBSERVADO">OBSERVADO (Contiene errores o inconsistencias)</option>
                <option value="EN_REVISION">EN REVISIÓN (Bajo análisis tributario/logístico)</option>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label>Motivo u Observaciones</Label>
              <textarea
                rows={3}
                placeholder="Observaciones formales registradas para trazabilidad del revisor..."
                value={revMotivo}
                onChange={(e) => setRevMotivo(e.target.value)}
                className="w-full rounded-md border border-slate-200 bg-white p-2.5 text-xs text-slate-900 shadow-xs focus:ring-2 focus:ring-slate-900 focus:outline-none"
              />
            </div>
          </div>
        </Modal>
      )}

      {/* MODAL: ANULACIÓN DE COMPROBANTE */}
      {modalAnulacionDoc && (
        <Modal
          isOpen={Boolean(modalAnulacionDoc)}
          onClose={() => setModalAnulacionDoc(null)}
          title={`Anular Comprobante: ${numeroComprobante(modalAnulacionDoc)}`}
          description="Esta acción anulará el comprobante y generará un movimiento de extorno en Kardex si ya estaba confirmado."
          icon={<Ban className="h-5 w-5 text-rose-600" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setModalAnulacionDoc(null)}>
                Cancelar
              </Button>
              <Button variant="destructive" onClick={handleEjecutarAnulacion}>
                Confirmar Anulación
              </Button>
            </div>
          }
        >
          <div className="space-y-4">
            {alertaAnulacion && <AlertaFormulario ref={alertaModalRef} titulo={alertaAnulacion.titulo} mensajes={alertaAnulacion.mensajes} />}
            <div className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
              <div>
                <strong>Aviso Inalterable:</strong> Todo extorno en Kardex preserva los saldos cronológicos e
                inscribe un evento en la tabla de auditoría inmutable.
              </div>
            </div>

            <div className="space-y-1.5">
              <Label required>Motivo de Anulación</Label>
              <textarea
                rows={3}
                required
                placeholder="Indique la justificación comercial/fiscal de la anulación..."
                value={anulacionMotivo}
                onChange={(e) => setAnulacionMotivo(e.target.value)}
                className="w-full rounded-md border border-slate-200 bg-white p-2.5 text-xs text-slate-900 shadow-xs focus:ring-2 focus:ring-rose-500 focus:outline-none"
              />
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

export default DocumentosPage
