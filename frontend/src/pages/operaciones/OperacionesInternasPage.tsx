import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import axios from 'axios'
import { Link } from 'react-router-dom'
import {
  ClipboardList,
  PackagePlus,
  FileWarning,
  Plus,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Pencil,
  Ban,
  Building2,
  Save,
  Search,
  Trash2,
  Eye,
  RotateCcw,
  Coins,
  Activity,
  Package,
  FileSpreadsheet,
  Download,
  Upload,
  Loader2,
  FileText,
  Paperclip,
  ShieldCheck,
  X,
} from 'lucide-react'

import { obtenerTiposOperacion, type TipoOperacion } from '../../api/catalogos'
import { getAlmacenes, getProductos, type Almacen, type Producto } from '../../api/inventario'
import { obtenerSaldosActuales, type StockAlmacenApi } from '../../api/kardex'
import {
  anularNotaInterna,
  confirmarNotaInterna,
  confirmarSaldoInicial,
  createNotaInterna,
  createSaldoInicial,
  descargarPlantillaSaldosInicialesExcel,
  descargarSustentoPdfNotaInterna,
  eliminarNotaInternaBorrador,
  eliminarSaldoInicialBorrador,
  getNotaInterna,
  getNotasInternas,
  getSaldoInicial,
  getSaldosIniciales,
  importarSaldosInicialesExcel,
  subirSustentoPdfNotaInterna,
  updateNotaInterna,
  updateSaldoInicial,
  type NotaInterna,
  type NotaInternaDetallePayload,
  type NotaInternaFiltros,
  type ResultadoImportacionSaldosIniciales,
  type SaldoInicial,
  type SaldoInicialFiltros,
} from '../../api/operaciones'
import { obtenerPeriodos, type Periodo } from '../../api/periodos'
import { useAuth } from '../../context/useAuth'
import { campoFechaNotaInterna, formularioNotaTrasRespuesta } from '../../utils/notaInternaForm'
import { descargarBlob } from '../../utils/descargaArchivo'
import { PageHeader } from '../../components/ui/page-header'
import { Button } from '../../components/ui/button'
import { Card, CardContent } from '../../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Label } from '../../components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs'
import { Modal } from '../../components/ui/modal'
import { Paginacion } from '../../components/ui/paginacion'
import { diferirCarga } from '../../utils/efectos'
import { formatearDecimal } from '../../utils/decimal'
import { useSoloConsulta } from '../../hooks/useSoloConsulta'

type TabId = 'saldos' | 'notas'
const PAGE_SIZE = 25

const TIPOS_ESTANDAR = new Set(['MERMA', 'DESMEDRO', 'CONSUMO_INTERNO', 'RETIRO'])
const TIPOS_ADMIN = new Set(['AJUSTE_INGRESO', 'AJUSTE_SALIDA', 'AJUSTE_VALOR_MANUAL'])

const SALDO_INICIAL = {
  periodo: '',
  almacen: '',
  producto: '',
  cantidad: '',
  valor_pen: '',
}

const LINEA_INICIAL = (): NotaInternaDetallePayload => ({
  producto: 0,
  cantidad_base: '',
  costo_unitario_pen: null,
  valor_ajuste_pen: null,
})

const NOTA_INICIAL = {
  almacen: '',
  periodo: '',
  tipo_operacion: '',
  fecha: '',
  motivo: '',
  responsable: '',
  observacion: '',
  archivo_sustento: '',
  detalles: [LINEA_INICIAL()],
}

const extraerError = (error: unknown) => {
  if (!axios.isAxiosError(error)) return 'No se pudo completar la operación.'
  const data = error.response?.data
  if (typeof data === 'string') return data
  if (!data || typeof data !== 'object') return 'No se pudo completar la operación.'
  return Object.entries(data)
    .map(([campo, detalle]) => {
      if (Array.isArray(detalle)) return `${campo}: ${detalle.join(' ')}`
      if (detalle && typeof detalle === 'object') return `${campo}: ${JSON.stringify(detalle)}`
      return campo === 'detail' || campo === 'non_field_errors'
        ? String(detalle)
        : `${campo}: ${String(detalle)}`
    })
    .join(' ')
}

const decimalComoFraccion = (valor: string) => {
  const limpio = valor.trim()
  if (!/^-?\d+(\.\d+)?$/.test(limpio)) return null
  const negativo = limpio.startsWith('-')
  const sinSigno = negativo ? limpio.slice(1) : limpio
  const [entero, decimales = ''] = sinSigno.split('.')
  const escala = 10n ** BigInt(decimales.length)
  const numero = BigInt(`${entero}${decimales}` || '0') * (negativo ? -1n : 1n)
  return { numero, escala }
}

const dividirASeisDecimales = (valor: string, cantidad: string) => {
  const dividendo = decimalComoFraccion(valor)
  const divisor = decimalComoFraccion(cantidad)
  if (!dividendo || !divisor || divisor.numero === 0n) return '0.000000'
  const negativo = (dividendo.numero < 0n) !== (divisor.numero < 0n)
  const numerador =
    (dividendo.numero < 0n ? -dividendo.numero : dividendo.numero) * divisor.escala * 1_000_000n
  const denominador = dividendo.escala * (divisor.numero < 0n ? -divisor.numero : divisor.numero)
  let resultado = numerador / denominador
  if ((numerador % denominador) * 2n >= denominador) resultado += 1n
  const texto = resultado.toString().padStart(7, '0')
  const formateado = `${texto.slice(0, -6)}.${texto.slice(-6)}`
  return negativo && resultado !== 0n ? `-${formateado}` : formateado
}

const etiquetaPeriodo = (periodo: Periodo) =>
  `${periodo.anio}-${String(periodo.mes).padStart(2, '0')} · ${periodo.estado}`

export const OperacionesInternasPage = () => {
  const { empresaActiva } = useAuth()
  const soloConsulta = useSoloConsulta()
  const esAdmin = empresaActiva?.rol === 'ADMIN'
  const [tab, setTab] = useState<TabId>('saldos')
  const [periodos, setPeriodos] = useState<Periodo[]>([])
  const [almacenes, setAlmacenes] = useState<Almacen[]>([])
  const [productos, setProductos] = useState<Producto[]>([])
  const [tiposOperacion, setTiposOperacion] = useState<TipoOperacion[]>([])
  const [stocksAlmacen, setStocksAlmacen] = useState<StockAlmacenApi[]>([])
  const [saldos, setSaldos] = useState<SaldoInicial[]>([])
  const [notas, setNotas] = useState<NotaInterna[]>([])
  const [loading, setLoading] = useState(false)
  const [catalogosLoading, setCatalogosLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Filtros (Default: ACTIVOS oculta anulados de la vista diaria)
  const [saldoFiltros, setSaldoFiltros] = useState({ periodo: '', almacen: '', producto: '', estado: 'ACTIVOS' })
  const [notaFiltros, setNotaFiltros] = useState({ periodo: '', almacen: '', tipo: '', estado: 'ACTIVOS', search: '' })

  // Paginación
  const [pageSaldos, setPageSaldos] = useState(1)
  const [pageNotas, setPageNotas] = useState(1)

  // Formularios de Creación / Edición
  const [saldoForm, setSaldoForm] = useState(SALDO_INICIAL)
  const [saldoEditando, setSaldoEditando] = useState<SaldoInicial | null>(null)
  const [saldoFormVisible, setSaldoFormVisible] = useState(false)
  const [notaForm, setNotaForm] = useState(NOTA_INICIAL)
  const [notaEditando, setNotaEditando] = useState<NotaInterna | null>(null)
  const [notaFormVisible, setNotaFormVisible] = useState(false)
  const [pdfSustento, setPdfSustento] = useState<File | null>(null)
  const [descargandoPdf, setDescargandoPdf] = useState(false)
  const [subiendoPdfDetalle, setSubiendoPdfDetalle] = useState(false)

  // Modales Especiales: Visor Solo Lectura, Anulación con Extorno y Eliminación
  const [detalleNota, setDetalleNota] = useState<NotaInterna | null>(null)
  const [detalleSaldo, setDetalleSaldo] = useState<SaldoInicial | null>(null)
  const [notaParaExtorno, setNotaParaExtorno] = useState<NotaInterna | null>(null)
  const [motivoExtorno, setMotivoExtorno] = useState('')
  const [borradorAEliminar, setBorradorAEliminar] = useState<{ tipo: 'saldo' | 'nota'; id: number; descripcion: string } | null>(null)

  // Modal de Importación Masiva de Saldos Iniciales (.xlsx)
  const [importarModalOpen, setImportarModalOpen] = useState(false)
  const [archivoExcel, setArchivoExcel] = useState<File | null>(null)
  const [importPeriodoId, setImportPeriodoId] = useState('')
  const [importAlmacenId, setImportAlmacenId] = useState('')
  const [autoConfirmar, setAutoConfirmar] = useState(true)
  const [descargandoPlantilla, setDescargandoPlantilla] = useState(false)
  const [procesandoImportacion, setProcesandoImportacion] = useState(false)
  const [errorImportacion, setErrorImportacion] = useState<string | null>(null)
  const [resultadoImportacion, setResultadoImportacion] = useState<ResultadoImportacionSaldosIniciales | null>(null)
  const [filtroEstadoDiagnostico, setFiltroEstadoDiagnostico] = useState<'TODOS' | 'NUEVO' | 'ACTUALIZAR' | 'ERROR'>('TODOS')

  const requestRef = useRef(0)

  const periodosAbiertos = useMemo(
    () => periodos.filter((periodo) => periodo.estado === 'ABIERTO'),
    [periodos]
  )
  const periodoNotaSeleccionado = useMemo(
    () => periodosAbiertos.find((periodo) => String(periodo.id) === notaForm.periodo),
    [notaForm.periodo, periodosAbiertos]
  )
  const tiposInternos = useMemo(
    () =>
      tiposOperacion.filter(
        (tipo) =>
          tipo.activo &&
          tipo.es_interna &&
          tipo.origen_requerido === 'NOTA_INTERNA' &&
          (TIPOS_ESTANDAR.has(tipo.codigo_interno) || TIPOS_ADMIN.has(tipo.codigo_interno))
      ),
    [tiposOperacion]
  )
  const tiposSeleccionables = useMemo(
    () => tiposInternos.filter((tipo) => esAdmin || TIPOS_ESTANDAR.has(tipo.codigo_interno)),
    [esAdmin, tiposInternos]
  )
  const cppInformativo = useMemo(
    () => dividirASeisDecimales(saldoForm.valor_pen, saldoForm.cantidad),
    [saldoForm.cantidad, saldoForm.valor_pen]
  )
  const recursosFaltantes = useMemo(() => {
    const faltantes: string[] = []
    if (!periodosAbiertos.length) faltantes.push('períodos abiertos')
    if (!almacenes.length) faltantes.push('almacenes')
    if (!productos.length) faltantes.push('productos')
    if (tab === 'notas' && !tiposSeleccionables.length) faltantes.push('tipos de operación internos')
    return faltantes
  }, [almacenes.length, periodosAbiertos.length, productos.length, tab, tiposSeleccionables.length])

  // Métricas ejecutivas en vivo
  const metricas = useMemo(() => {
    const notasActivas = notas.filter((n) => n.estado !== 'ANULADO')
    const mermasDesmedros = notasActivas.filter((n) =>
      n.tipo_operacion_codigo.includes('MERMA') || n.tipo_operacion_codigo.includes('DESMEDRO')
    ).length
    const consumosRetiros = notasActivas.filter((n) =>
      n.tipo_operacion_codigo.includes('CONSUMO') || n.tipo_operacion_codigo.includes('RETIRO')
    ).length
    const ajustes = notasActivas.filter((n) => n.tipo_operacion_codigo.includes('AJUSTE')).length
    const saldosActivos = saldos.filter((s) => s.estado === 'CONFIRMADO').length
    return {
      totalActivas: notasActivas.length + saldosActivos,
      mermasDesmedros,
      consumosRetiros,
      ajustes,
    }
  }, [notas, saldos])

  const mapaStocks = useMemo(() => {
    const mapa = new Map<string, number>()
    for (const item of stocksAlmacen) {
      mapa.set(`${item.almacen_id}-${item.producto_id}`, Number(item.cantidad_actual || 0))
    }
    return mapa
  }, [stocksAlmacen])

  const obtenerStockDisponible = useCallback((almacenId: number | string, productoId: number | string): number => {
    if (!almacenId || !productoId) return 0
    return mapaStocks.get(`${almacenId}-${productoId}`) ?? 0
  }, [mapaStocks])

  const limpiarMensajes = () => {
    setError('')
    setSuccess('')
  }

  const cerrarFormularios = useCallback(() => {
    setSaldoFormVisible(false)
    setSaldoEditando(null)
    setSaldoForm(SALDO_INICIAL)
    setNotaFormVisible(false)
    setNotaEditando(null)
    setNotaForm(NOTA_INICIAL)
    setDetalleNota(null)
    setDetalleSaldo(null)
    setNotaParaExtorno(null)
    setMotivoExtorno('')
    setBorradorAEliminar(null)
  }, [])

  const filtrosSaldoApi = useCallback(
    (): SaldoInicialFiltros => ({
      periodo_id: saldoFiltros.periodo ? Number(saldoFiltros.periodo) : undefined,
      almacen_id: saldoFiltros.almacen ? Number(saldoFiltros.almacen) : undefined,
      producto_id: saldoFiltros.producto ? Number(saldoFiltros.producto) : undefined,
      estado: saldoFiltros.estado === 'TODOS' ? undefined : (saldoFiltros.estado as SaldoInicialFiltros['estado']),
    }),
    [saldoFiltros]
  )

  const filtrosNotaApi = useCallback(
    (): NotaInternaFiltros => ({
      periodo_id: notaFiltros.periodo ? Number(notaFiltros.periodo) : undefined,
      almacen_id: notaFiltros.almacen ? Number(notaFiltros.almacen) : undefined,
      tipo_operacion: notaFiltros.tipo || undefined,
      estado: notaFiltros.estado === 'TODOS' ? undefined : (notaFiltros.estado as NotaInternaFiltros['estado']),
      search: notaFiltros.search.trim() || undefined,
    }),
    [notaFiltros]
  )

  const cargarLista = useCallback(async () => {
    if (!empresaActiva) return
    const requestId = ++requestRef.current
    setLoading(true)
    setError('')
    try {
      const [saldosData, notasData] = await Promise.all([
        getSaldosIniciales(filtrosSaldoApi()),
        getNotasInternas(filtrosNotaApi()),
      ])
      if (requestId === requestRef.current) {
        setSaldos(saldosData)
        setNotas(notasData)
      }
    } catch (err) {
      if (requestId === requestRef.current) setError(extraerError(err))
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }, [empresaActiva, filtrosNotaApi, filtrosSaldoApi])

  const empresaId = empresaActiva?.id

  useEffect(() => {
    requestRef.current += 1
    let ignorar = false
    diferirCarga(() => {
      if (ignorar) return
      cerrarFormularios()
      setPeriodos([])
      setAlmacenes([])
      setProductos([])
      setTiposOperacion([])
      setStocksAlmacen([])
      setSaldos([])
      setNotas([])
      limpiarMensajes()
      if (!empresaId) return
      setCatalogosLoading(true)
      Promise.all([
        obtenerPeriodos(),
        getAlmacenes(),
        getProductos(),
        obtenerTiposOperacion(),
        obtenerSaldosActuales().catch(() => ({ saldos_cpp: [], stocks_almacen: [] })),
      ])
        .then(([nuevosPeriodos, nuevosAlmacenes, nuevosProductos, nuevosTipos, respuestaSaldos]) => {
          if (ignorar) return
          setPeriodos(nuevosPeriodos)
          setAlmacenes(nuevosAlmacenes)
          setProductos(nuevosProductos)
          setTiposOperacion(nuevosTipos)
          setStocksAlmacen(respuestaSaldos.stocks_almacen || [])
        })
        .catch((err) => {
          if (!ignorar) setError(extraerError(err))
        })
        .finally(() => {
          if (!ignorar) setCatalogosLoading(false)
        })
    })
    return () => {
      ignorar = true
    }
  }, [cerrarFormularios, empresaId])

  useEffect(() => {
    diferirCarga(cargarLista)
  }, [cargarLista])

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

  const refrescar = async () => {
    try {
      await cargarLista()
    } catch {
      setError('El cambio se guardó, pero la lista no pudo actualizarse. Recarga la página.')
    }
  }

  const handleDescargarPlantilla = async () => {
    try {
      setDescargandoPlantilla(true)
      setErrorImportacion(null)
      const blob = await descargarPlantillaSaldosInicialesExcel()
      descargarBlob(blob, 'plantilla_saldos_iniciales_op16.xlsx')
    } catch {
      setErrorImportacion('Error al descargar la plantilla oficial de saldos iniciales.')
    } finally {
      setDescargandoPlantilla(false)
    }
  }

  const handleProcesarExcel = async (modo: 'PREVISUALIZAR' | 'CONFIRMAR') => {
    if (!archivoExcel) {
      setErrorImportacion('Seleccione un archivo Excel (.xlsx).')
      return
    }
    if (!importPeriodoId) {
      setErrorImportacion('Seleccione un período contable abierto.')
      return
    }
    if (!importAlmacenId) {
      setErrorImportacion('Seleccione un almacén destino.')
      return
    }

    try {
      setProcesandoImportacion(true)
      setErrorImportacion(null)
      const formData = new FormData()
      formData.append('archivo', archivoExcel)
      formData.append('periodo', importPeriodoId)
      formData.append('almacen', importAlmacenId)
      formData.append('modo', modo)
      formData.append('auto_confirmar', String(autoConfirmar))

      const res = await importarSaldosInicialesExcel(formData)
      setResultadoImportacion(res)

      if (modo === 'CONFIRMAR') {
        const confirmados = res.resumen.confirmados_kardex ?? 0
        const creados = res.resumen.creados ?? 0
        const actualizados = res.resumen.actualizados ?? 0
        const msg = confirmados > 0
          ? `Importación completada: ${confirmados} saldo(s) inicial(es) confirmados en el Kardex (Op. 16).`
          : `Importación completada: ${creados} saldo(s) inicial(es) creados y ${actualizados} actualizados.`
        setSuccess(msg)
        cerrarModalImportar()
        await refrescar()
      }
    } catch (err: unknown) {
      setErrorImportacion(extraerError(err))
    } finally {
      setProcesandoImportacion(false)
    }
  }

  const cerrarModalImportar = () => {
    setImportarModalOpen(false)
    setArchivoExcel(null)
    setResultadoImportacion(null)
    setErrorImportacion(null)
    setFiltroEstadoDiagnostico('TODOS')
  }

  const abrirNuevo = () => {
    limpiarMensajes()
    if (tab === 'saldos') {
      setSaldoEditando(null)
      setSaldoForm(SALDO_INICIAL)
      setSaldoFormVisible(true)
    } else {
      setNotaEditando(null)
      setNotaForm(NOTA_INICIAL)
      setPdfSustento(null)
      setNotaFormVisible(true)
    }
  }

  const editarSaldo = async (saldo: SaldoInicial) => {
    limpiarMensajes()
    try {
      const detalle = await getSaldoInicial(saldo.id)
      setSaldoEditando(detalle)
      setSaldoForm({
        periodo: String(detalle.periodo),
        almacen: String(detalle.almacen),
        producto: String(detalle.producto),
        cantidad: detalle.cantidad,
        valor_pen: detalle.valor_pen,
      })
      setSaldoFormVisible(true)
    } catch (err) {
      setError(extraerError(err))
    }
  }

  const guardarSaldo = (event: FormEvent) => {
    event.preventDefault()
    void (async () => {
      const payload = {
        periodo: Number(saldoForm.periodo),
        almacen: Number(saldoForm.almacen),
        producto: Number(saldoForm.producto),
        cantidad: saldoForm.cantidad,
        valor_pen: saldoForm.valor_pen,
      }
      const guardado = await ejecutar(async () => {
        if (saldoEditando) await updateSaldoInicial(saldoEditando.id, payload)
        else await createSaldoInicial(payload)
      }, saldoEditando ? 'Saldo inicial actualizado.' : 'Saldo inicial creado.')
      if (!guardado) return
      setSaldoFormVisible(false)
      setSaldoEditando(null)
      setSaldoForm(SALDO_INICIAL)
      setTab('saldos')
      setPageSaldos(1)
      await refrescar()
    })()
  }

  const editarNota = async (nota: NotaInterna) => {
    limpiarMensajes()
    try {
      const detalle = await getNotaInterna(nota.id)
      setNotaEditando(detalle)
      setNotaForm({
        almacen: String(detalle.almacen),
        periodo: String(detalle.periodo),
        tipo_operacion: String(detalle.tipo_operacion),
        fecha: detalle.fecha,
        motivo: detalle.motivo,
        responsable: detalle.responsable ?? '',
        observacion: detalle.observacion ?? '',
        archivo_sustento: detalle.archivo_sustento ?? '',
        detalles: detalle.detalles.map((linea) => ({
          producto: linea.producto,
          cantidad_base: linea.cantidad_base,
          costo_unitario_pen: linea.costo_unitario_pen,
          valor_ajuste_pen: linea.valor_ajuste_pen,
        })),
      })
      setPdfSustento(null)
      setNotaFormVisible(true)
    } catch (err) {
      setError(extraerError(err))
    }
  }

  const actualizarLinea = (indice: number, cambio: Partial<NotaInternaDetallePayload>) => {
    setNotaForm((actual) => ({
      ...actual,
      detalles: actual.detalles.map((linea, posicion) =>
        posicion === indice ? { ...linea, ...cambio } : linea
      ),
    }))
  }

  const guardarNota = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const campoFecha = campoFechaNotaInterna(new FormData(event.currentTarget).get('fecha'))
    if (!campoFecha.fecha) {
      setError('La fecha debe tener el formato YYYY-MM-DD.')
      return
    }
    if (!notaForm.detalles.length || notaForm.detalles.some((linea) => !linea.producto)) {
      setError('Cada línea debe tener un producto y la nota debe contener al menos una línea.')
      return
    }
    void (async () => {
      const formularioEnviado = { ...notaForm, ...campoFecha }
      const payload = {
        almacen: Number(formularioEnviado.almacen),
        periodo: Number(formularioEnviado.periodo),
        tipo_operacion: Number(formularioEnviado.tipo_operacion),
        fecha: formularioEnviado.fecha,
        motivo: formularioEnviado.motivo,
        responsable: formularioEnviado.responsable || null,
        observacion: formularioEnviado.observacion || null,
        archivo_sustento: formularioEnviado.archivo_sustento || null,
        detalles: formularioEnviado.detalles.map((linea) => ({
          ...linea,
          costo_unitario_pen: esAdmin ? linea.costo_unitario_pen || null : null,
          valor_ajuste_pen: esAdmin ? linea.valor_ajuste_pen || null : null,
        })),
      }
      const guardado = await ejecutar(async () => {
        let notaGuardada: NotaInterna
        if (notaEditando) {
          notaGuardada = await updateNotaInterna(notaEditando.id, payload)
        } else {
          notaGuardada = await createNotaInterna(payload)
        }
        if (pdfSustento) {
          await subirSustentoPdfNotaInterna(
            notaGuardada.id,
            pdfSustento,
            formularioEnviado.archivo_sustento || undefined
          )
        }
      }, notaEditando ? 'Nota interna actualizada.' : 'Nota interna creada.')
      const formularioConservado = formularioNotaTrasRespuesta(formularioEnviado, guardado)
      if (formularioConservado) {
        setNotaForm(formularioConservado)
        return
      }
      setPdfSustento(null)
      setNotaFormVisible(false)
      setNotaEditando(null)
      setNotaForm(NOTA_INICIAL)
      setTab('notas')
      setPageNotas(1)
      await refrescar()
    })()
  }

  const notaRequiereAdmin = (nota: NotaInterna) =>
    TIPOS_ADMIN.has(nota.tipo_operacion_codigo) ||
    nota.detalles.some((linea) => linea.costo_unitario_pen !== null || linea.valor_ajuste_pen !== null)

  const confirmarSaldo = async (saldo: SaldoInicial) => {
    if (!window.confirm(`¿Confirmar el saldo inicial de ${saldo.producto_codigo}? Impactará stock en Kardex.`))
      return
    const guardado = await ejecutar(async () => {
      await confirmarSaldoInicial(saldo.id)
    }, 'Saldo inicial confirmado y aplicado al Kardex.')
    if (guardado) await refrescar()
  }

  const confirmarNota = async (nota: NotaInterna) => {
    if (!window.confirm(`¿Confirmar la nota interna #${nota.id}? Impactará stock y CPP en Kardex.`))
      return
    const guardado = await ejecutar(async () => {
      await confirmarNotaInterna(nota.id)
    }, `Nota interna #${nota.id} confirmada y aplicada al Kardex.`)
    if (guardado) await refrescar()
  }

  // Eliminación física de borrador
  const ejecutarEliminacionBorrador = async () => {
    if (!borradorAEliminar) return
    const guardado = await ejecutar(async () => {
      if (borradorAEliminar.tipo === 'saldo') {
        await eliminarSaldoInicialBorrador(borradorAEliminar.id)
      } else {
        await eliminarNotaInternaBorrador(borradorAEliminar.id)
      }
    }, `${borradorAEliminar.tipo === 'saldo' ? 'Saldo inicial' : 'Nota interna'} borrador eliminado físicamente.`)
    if (guardado) {
      setBorradorAEliminar(null)
      await refrescar()
    }
  }

  // Anulación con extorno para nota confirmada
  const ejecutarExtornoNota = async () => {
    if (!notaParaExtorno) return
    if (!motivoExtorno.trim()) {
      setError('El motivo de anulación es obligatorio.')
      return
    }
    const guardado = await ejecutar(async () => {
      await anularNotaInterna(notaParaExtorno.id, { motivo: motivoExtorno.trim() })
    }, `Nota interna #${notaParaExtorno.id} anulada con extorno contable en Kardex.`)
    if (guardado) {
      setNotaParaExtorno(null)
      setMotivoExtorno('')
      await refrescar()
    }
  }

  if (!empresaActiva) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center bg-white rounded-xl border border-slate-200 shadow-2xs">
        <div className="h-12 w-12 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 mb-4">
          <Building2 className="h-6 w-6" />
        </div>
        <h2 className="text-lg font-bold text-slate-900 mb-1">Selecciona una Empresa Activa</h2>
        <p className="text-xs text-slate-500 mb-4 max-w-sm">
          Los saldos iniciales y notas internas operan bajo aislamiento multi-tenant estricto.
        </p>
        <Link to="/empresas">
          <Button variant="primary">Ir a Empresas</Button>
        </Link>
      </div>
    )
  }

  const tienePermisoCrear = !soloConsulta && (tab === 'notas' || esAdmin)
  const puedeCrear = tienePermisoCrear && recursosFaltantes.length === 0

  // Paginación en cliente
  const saldosPaginados = saldos.slice((pageSaldos - 1) * PAGE_SIZE, pageSaldos * PAGE_SIZE)
  const notasPaginadas = notas.slice((pageNotas - 1) * PAGE_SIZE, pageNotas * PAGE_SIZE)

  return (
    <div className="space-y-5">
      {/* Nivel 1: Header + Botón de Acción */}
      <PageHeader
        title="Operaciones Internas de Inventario"
        description={`Bitácora legal de saldos de apertura, mermas, desmedros, consumos y ajustes valorizados para ${empresaActiva.razon_social}.`}
        icon={<ClipboardList className="h-5 w-5" />}
        badge={
          <Badge variant={esAdmin ? 'info' : 'neutral'} dot>
            {esAdmin ? 'Control Administrativo (ADMIN)' : 'Operación Estándar'}
          </Badge>
        }
        actions={
          <div className="flex items-center gap-2">
            {tab === 'saldos' && (
              <Button
                variant="outline"
                onClick={() => {
                  limpiarMensajes()
                  setErrorImportacion(null)
                  setResultadoImportacion(null)
                  setArchivoExcel(null)
                  if (!importPeriodoId && periodosAbiertos.length > 0) {
                    setImportPeriodoId(String(periodosAbiertos[0].id))
                  }
                  if (!importAlmacenId && almacenes.length > 0) {
                    setImportAlmacenId(String(almacenes[0].id))
                  }
                  setImportarModalOpen(true)
                }}
                disabled={!esAdmin || catalogosLoading}
                title={!esAdmin ? 'La importación requiere rol ADMIN' : 'Importación masiva de saldos iniciales vía Excel'}
              >
                <FileSpreadsheet className="h-4 w-4 mr-1.5 text-indigo-600" />
                Importar Excel (Op. 16)
              </Button>
            )}
            <Button
              variant="primary"
              onClick={abrirNuevo}
              disabled={!puedeCrear || catalogosLoading}
              title={
                !tienePermisoCrear
                  ? 'Los saldos iniciales requieren rol ADMIN'
                  : recursosFaltantes.length
                  ? `Faltan: ${recursosFaltantes.join(', ')}`
                  : undefined
              }
            >
              <Plus className="h-4 w-4 mr-1.5" />
              Nuevo {tab === 'saldos' ? 'Saldo Inicial' : 'Nota Interna'}
            </Button>
          </div>
        }
      />

      {/* Cinta de Resumen Operativo (4 Métricas en vivo) */}
      <div className="grid grid-cols-2 md:grid-cols-4 rounded-xl border border-slate-200/90 bg-white shadow-2xs divide-y md:divide-y-0 md:divide-x divide-slate-100 overflow-hidden">
        <div className="p-3.5 flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 border border-indigo-100 text-indigo-600">
            <Activity className="h-4 w-4" />
          </div>
          <div>
            <span className="text-[11px] font-medium text-slate-500 uppercase tracking-wider block">Total Activas</span>
            <span className="font-mono text-base font-bold text-slate-900 tabular-nums">{metricas.totalActivas}</span>
          </div>
        </div>

        <div className="p-3.5 flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-50 border border-amber-100 text-amber-600">
            <FileWarning className="h-4 w-4" />
          </div>
          <div>
            <span className="text-[11px] font-medium text-slate-500 uppercase tracking-wider block">Mermas / Desmedros</span>
            <span className="font-mono text-base font-bold text-slate-900 tabular-nums">{metricas.mermasDesmedros}</span>
          </div>
        </div>

        <div className="p-3.5 flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-50 border border-emerald-100 text-emerald-600">
            <Package className="h-4 w-4" />
          </div>
          <div>
            <span className="text-[11px] font-medium text-slate-500 uppercase tracking-wider block">Consumos / Retiros</span>
            <span className="font-mono text-base font-bold text-slate-900 tabular-nums">{metricas.consumosRetiros}</span>
          </div>
        </div>

        <div className="p-3.5 flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-purple-50 border border-purple-100 text-purple-600">
            <Coins className="h-4 w-4" />
          </div>
          <div>
            <span className="text-[11px] font-medium text-slate-500 uppercase tracking-wider block">Ajustes Valorizados</span>
            <span className="font-mono text-base font-bold text-slate-900 tabular-nums">{metricas.ajustes}</span>
          </div>
        </div>
      </div>

      {/* Alertas */}
      {error && (
        <div role="alert" className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50/90 p-3.5 text-xs text-rose-700 animate-in fade-in">
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{error}</span>
        </div>
      )}

      {success && (
        <div role="status" className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50/90 p-3.5 text-xs text-emerald-700 animate-in fade-in">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{success}</span>
        </div>
      )}

      {!catalogosLoading && recursosFaltantes.length > 0 && (
        <div role="status" className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50/90 p-3 text-xs text-amber-800">
          <AlertCircle className="h-4 w-4 shrink-0 text-amber-600 mt-0.5" />
          <span><strong>Configuración pendiente:</strong> Para crear registros faltan {recursosFaltantes.join(', ')}.</span>
        </div>
      )}

      {/* Nivel 2: Pestañas + Filtros */}
      <Tabs
        value={tab}
        onValueChange={(val) => {
          setTab(val as TabId)
          cerrarFormularios()
          limpiarMensajes()
        }}
      >
        <TabsList>
          <TabsTrigger value="saldos" icon={<PackagePlus className="h-3.5 w-3.5" />}>
            Saldos Iniciales ({saldos.length})
          </TabsTrigger>
          <TabsTrigger value="notas" icon={<FileWarning className="h-3.5 w-3.5" />}>
            Notas Internas: Mermas, Desmedros y Ajustes ({notas.length})
          </TabsTrigger>
        </TabsList>

        {/* TAB 1: SALDOS INICIALES */}
        <TabsContent value="saldos" className="space-y-4">
          <Card>
            <CardContent className="p-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
                <div className="space-y-1">
                  <Label>Período</Label>
                  <Select
                    value={saldoFiltros.periodo}
                    onChange={(e) => {
                      setSaldoFiltros({ ...saldoFiltros, periodo: e.target.value })
                      setPageSaldos(1)
                    }}
                  >
                    <option value="">Todos los períodos</option>
                    {periodos.map((p) => (
                      <option key={p.id} value={p.id}>{etiquetaPeriodo(p)}</option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label>Almacén</Label>
                  <Select
                    value={saldoFiltros.almacen}
                    onChange={(e) => {
                      setSaldoFiltros({ ...saldoFiltros, almacen: e.target.value })
                      setPageSaldos(1)
                    }}
                  >
                    <option value="">Todos los almacenes</option>
                    {almacenes.map((a) => (
                      <option key={a.id} value={a.id}>{a.codigo} · {a.nombre}</option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label>Producto</Label>
                  <Select
                    value={saldoFiltros.producto}
                    onChange={(e) => {
                      setSaldoFiltros({ ...saldoFiltros, producto: e.target.value })
                      setPageSaldos(1)
                    }}
                  >
                    <option value="">Todos los productos</option>
                    {productos.map((p) => (
                      <option key={p.id} value={p.id}>{p.codigo_interno} · {p.descripcion}</option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label>Estado</Label>
                  <Select
                    value={saldoFiltros.estado}
                    onChange={(e) => {
                      setSaldoFiltros({ ...saldoFiltros, estado: e.target.value })
                      setPageSaldos(1)
                    }}
                  >
                    <option value="ACTIVOS">Activos (Borrador y Confirmado)</option>
                    <option value="TODOS">Todos (Incluye Anulados)</option>
                    <option value="BORRADOR">Solo Borradores</option>
                    <option value="CONFIRMADO">Solo Confirmados</option>
                  </Select>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Nivel 3: Tabla de Saldos con scroll y cabecera fija */}
          <Card>
            <CardContent className="p-0">
              <Table containerClassName="border-0 shadow-none rounded-none max-h-[580px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-28">Período</TableHead>
                    <TableHead className="w-40">Almacén</TableHead>
                    <TableHead>Producto</TableHead>
                    <TableHead className="w-24 text-center">Unidad Base</TableHead>
                    <TableHead numeric className="w-32">Cantidad</TableHead>
                    <TableHead numeric className="w-36">Valor Total PEN</TableHead>
                    <TableHead numeric className="w-32">CPP Inicial</TableHead>
                    <TableHead className="w-28 text-center">Estado</TableHead>
                    <TableHead className="w-36 text-center">Acciones</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading ? (
                    <TableRow>
                      <TableCell colSpan={9} className="text-center py-10 text-slate-400 text-xs">
                        Cargando saldos iniciales...
                      </TableCell>
                    </TableRow>
                  ) : saldosPaginados.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={9} className="text-center py-10 text-slate-400 text-xs">
                        No hay saldos iniciales registrados para los filtros seleccionados.
                      </TableCell>
                    </TableRow>
                  ) : (
                    saldosPaginados.map((s) => (
                      <TableRow key={s.id}>
                        <TableCell className="font-semibold text-slate-800 text-xs">{s.periodo_descripcion}</TableCell>
                        <TableCell>
                          <span className="font-mono text-xs font-bold text-slate-900">{s.almacen_codigo}</span>
                          <span className="text-[10px] text-slate-400 block truncate max-w-xs">{s.almacen_nombre}</span>
                        </TableCell>
                        <TableCell>
                          <span className="font-mono text-xs font-bold text-slate-900">{s.producto_codigo}</span>
                          <span className="text-[10px] text-slate-500 block truncate max-w-xs">{s.producto_descripcion}</span>
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge variant="outline" className="font-mono text-[10px]">
                            {s.unidad_base_codigo || '—'}
                          </Badge>
                        </TableCell>
                        <TableCell numeric className="font-bold text-slate-800 font-mono tabular-nums">
                          {formatearDecimal(s.cantidad, { min: 4, max: 8 })}
                        </TableCell>
                        <TableCell numeric className="font-bold text-slate-900 font-mono tabular-nums">
                          S/ {formatearDecimal(s.valor_pen)}
                        </TableCell>
                        <TableCell numeric className="font-bold text-indigo-700 font-mono tabular-nums">
                          S/ {formatearDecimal(s.cpp_inicial, { min: 6, max: 6 })}
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge variant={s.estado === 'CONFIRMADO' ? 'success' : 'warning'} dot>
                            {s.estado}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-center">
                          <div className="flex items-center justify-center gap-1">
                            <Button
                              type="button"
                              size="xs"
                              variant="ghost"
                              onClick={() => setDetalleSaldo(s)}
                              title="Ver detalle de saldo inicial"
                            >
                              <Eye className="h-3.5 w-3.5 text-slate-600" />
                            </Button>
                            {esAdmin && s.estado === 'BORRADOR' && (
                              <>
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="outline"
                                  onClick={() => void editarSaldo(s)}
                                  title="Editar borrador"
                                >
                                  <Pencil className="h-3 w-3 text-slate-500" />
                                </Button>
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="primary"
                                  onClick={() => void confirmarSaldo(s)}
                                  title="Confirmar saldo inicial en Kardex"
                                >
                                  <CheckCircle2 className="h-3 w-3 mr-0.5" /> Confirmar
                                </Button>
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="ghost"
                                  onClick={() => setBorradorAEliminar({ tipo: 'saldo', id: s.id, descripcion: `${s.producto_codigo} (${s.almacen_codigo})` })}
                                  title="Eliminar borrador"
                                  className="text-rose-600 hover:bg-rose-50"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
              {saldos.length > 0 && (
                <Paginacion
                  page={pageSaldos}
                  pageSize={PAGE_SIZE}
                  count={saldos.length}
                  enPagina={saldosPaginados.length}
                  cargando={loading}
                  onCambiarPagina={setPageSaldos}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 2: NOTAS INTERNAS */}
        <TabsContent value="notas" className="space-y-4">
          <Card>
            <CardContent className="p-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3">
                <div className="space-y-1">
                  <Label>Período</Label>
                  <Select
                    value={notaFiltros.periodo}
                    onChange={(e) => {
                      setNotaFiltros({ ...notaFiltros, periodo: e.target.value })
                      setPageNotas(1)
                    }}
                  >
                    <option value="">Todos los períodos</option>
                    {periodos.map((p) => (
                      <option key={p.id} value={p.id}>{etiquetaPeriodo(p)}</option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label>Almacén</Label>
                  <Select
                    value={notaFiltros.almacen}
                    onChange={(e) => {
                      setNotaFiltros({ ...notaFiltros, almacen: e.target.value })
                      setPageNotas(1)
                    }}
                  >
                    <option value="">Todos los almacenes</option>
                    {almacenes.map((a) => (
                      <option key={a.id} value={a.id}>{a.codigo} · {a.nombre}</option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label>Tipo de Operación</Label>
                  <Select
                    value={notaFiltros.tipo}
                    onChange={(e) => {
                      setNotaFiltros({ ...notaFiltros, tipo: e.target.value })
                      setPageNotas(1)
                    }}
                  >
                    <option value="">Todos los tipos</option>
                    {tiposInternos.map((t) => (
                      <option key={t.id} value={t.codigo_interno}>{t.codigo_interno} · {t.descripcion}</option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label>Estado</Label>
                  <Select
                    value={notaFiltros.estado}
                    onChange={(e) => {
                      setNotaFiltros({ ...notaFiltros, estado: e.target.value })
                      setPageNotas(1)
                    }}
                  >
                    <option value="ACTIVOS">Activos (Borrador y Confirmado)</option>
                    <option value="TODOS">Todos (Incluye Anulados)</option>
                    <option value="BORRADOR">Solo Borradores</option>
                    <option value="CONFIRMADO">Solo Confirmados</option>
                    <option value="ANULADO">Solo Anulados</option>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label>Buscar Motivo / Responsable</Label>
                  <Input
                    placeholder="Merma, Ajuste..."
                    value={notaFiltros.search}
                    onChange={(e) => {
                      setNotaFiltros({ ...notaFiltros, search: e.target.value })
                      setPageNotas(1)
                    }}
                    leftIcon={<Search className="h-4 w-4" />}
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Tabla de Notas con scroll y cabecera fija */}
          <Card>
            <CardContent className="p-0">
              <Table containerClassName="border-0 shadow-none rounded-none max-h-[580px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-16"># ID</TableHead>
                    <TableHead className="w-24">Fecha</TableHead>
                    <TableHead className="w-28">Período</TableHead>
                    <TableHead className="w-36">Almacén</TableHead>
                    <TableHead className="w-48">Tipo de Operación</TableHead>
                    <TableHead className="min-w-[180px]">Motivo</TableHead>
                    <TableHead className="w-32">Responsable</TableHead>
                    <TableHead className="w-28 text-center">Estado</TableHead>
                    <TableHead numeric className="w-16 text-center">Líneas</TableHead>
                    <TableHead className="w-44 text-center">Acciones</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {notasPaginadas.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={10} className="text-center py-10 text-slate-400 text-xs">
                        No hay notas internas registradas para los filtros seleccionados.
                      </TableCell>
                    </TableRow>
                  ) : (
                    notasPaginadas.map((nota) => {
                      const esBorrador = nota.estado === 'BORRADOR' && (esAdmin || !notaRequiereAdmin(nota))
                      const esConfirmado = nota.estado === 'CONFIRMADO' && (esAdmin || !notaRequiereAdmin(nota))

                      return (
                        <TableRow key={nota.id}>
                          <TableCell className="font-mono font-bold text-slate-900 text-xs">
                            #{nota.id}
                          </TableCell>
                          <TableCell className="font-mono text-slate-600 text-xs whitespace-nowrap">
                            {nota.fecha}
                          </TableCell>
                          <TableCell className="text-slate-700 text-xs">{nota.periodo_descripcion}</TableCell>
                          <TableCell>
                            <span className="font-mono text-xs font-bold text-slate-900">{nota.almacen_codigo}</span>
                            <span className="text-[10px] text-slate-400 block truncate max-w-xs">{nota.almacen_nombre}</span>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col">
                              <Badge
                                variant={
                                  nota.tipo_operacion_codigo.includes('AJUSTE')
                                    ? 'warning'
                                    : 'info'
                                }
                                size="sm"
                                className="font-mono text-[10px]"
                              >
                                {nota.tipo_operacion_codigo}
                              </Badge>
                              <span className="text-[10px] text-slate-400 truncate max-w-xs mt-0.5">
                                {nota.tipo_operacion_descripcion}
                              </span>
                            </div>
                          </TableCell>
                          <TableCell className="font-medium text-slate-800 text-xs max-w-xs truncate" title={nota.motivo}>
                            {nota.motivo}
                          </TableCell>
                          <TableCell className="text-slate-600 text-xs truncate max-w-[120px]">{nota.responsable || '—'}</TableCell>
                          <TableCell className="text-center">
                            <Badge
                              variant={
                                nota.estado === 'CONFIRMADO'
                                  ? 'success'
                                  : nota.estado === 'ANULADO'
                                  ? 'destructive'
                                  : 'warning'
                              }
                              dot
                            >
                              {nota.estado}
                            </Badge>
                          </TableCell>
                          <TableCell numeric className="font-bold text-slate-700 font-mono text-center">
                            {nota.numero_lineas}
                          </TableCell>
                          <TableCell className="text-center">
                            <div className="flex items-center justify-center gap-1">
                              {/* Botón Ver Detalle (Para todos los estados) */}
                              <Button
                                type="button"
                                size="xs"
                                variant="ghost"
                                onClick={() => setDetalleNota(nota)}
                                title="Ver ficha técnica de la nota"
                              >
                                <Eye className="h-3.5 w-3.5 text-slate-600" />
                              </Button>

                              {/* Descarga directa de PDF si existe */}
                              {nota.sustento_pdf?.tiene_pdf && (
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="ghost"
                                  onClick={async () => {
                                    if (!nota.sustento_pdf) return
                                    try {
                                      await descargarSustentoPdfNotaInterna(nota.id, nota.sustento_pdf.nombre_archivo)
                                    } catch {
                                      setError('No se pudo descargar el archivo PDF.')
                                    }
                                  }}
                                  title={`Descargar sustento PDF (${nota.sustento_pdf.nombre_archivo})`}
                                  className="text-emerald-700 hover:text-emerald-800 hover:bg-emerald-50"
                                >
                                  <FileText className="h-3.5 w-3.5" />
                                </Button>
                              )}

                              {/* Acciones en BORRADOR */}
                              {esBorrador && (
                                <>
                                  <Button
                                    type="button"
                                    size="xs"
                                    variant="outline"
                                    onClick={() => void editarNota(nota)}
                                    title="Editar borrador"
                                  >
                                    <Pencil className="h-3 w-3 text-slate-500" />
                                  </Button>
                                  <Button
                                    type="button"
                                    size="xs"
                                    variant="primary"
                                    onClick={() => void confirmarNota(nota)}
                                    title="Confirmar en Kardex"
                                  >
                                    <CheckCircle2 className="h-3 w-3 mr-0.5" /> Confirmar
                                  </Button>
                                  <Button
                                    type="button"
                                    size="xs"
                                    variant="ghost"
                                    onClick={() => setBorradorAEliminar({ tipo: 'nota', id: nota.id, descripcion: `Nota #${nota.id} (${nota.tipo_operacion_codigo})` })}
                                    title="Eliminar borrador"
                                    className="text-rose-600 hover:bg-rose-50"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                </>
                              )}

                              {/* Acciones en CONFIRMADO (Extorno) */}
                              {esConfirmado && (
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="ghost"
                                  onClick={() => setNotaParaExtorno(nota)}
                                  title="Anular con extorno en Kardex"
                                  className="text-amber-700 hover:bg-amber-50 gap-1 text-[11px]"
                                >
                                  <RotateCcw className="h-3 w-3 text-amber-600" /> Extornar
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
              {notas.length > 0 && (
                <Paginacion
                  page={pageNotas}
                  pageSize={PAGE_SIZE}
                  count={notas.length}
                  enPagina={notasPaginadas.length}
                  cargando={loading}
                  onCambiarPagina={setPageNotas}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Modal: Saldo Inicial (Crear / Editar) */}
      {saldoFormVisible && (
        <Modal
          isOpen={saldoFormVisible}
          onClose={() => setSaldoFormVisible(false)}
          title={saldoEditando ? 'Editar Saldo Inicial' : 'Registrar Saldo Inicial'}
          description="Afecta el inventario de apertura del período contable. El CPP se calculará de forma definitiva."
          icon={<PackagePlus className="h-5 w-5" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setSaldoFormVisible(false)}>
                Cancelar
              </Button>
              <Button variant="primary" onClick={guardarSaldo} isLoading={saving}>
                <Save className="h-4 w-4 mr-1.5" />
                {saldoEditando ? 'Guardar Cambios' : 'Crear Saldo'}
              </Button>
            </div>
          }
        >
          <form onSubmit={guardarSaldo} className="space-y-4">
            <div className="flex items-center gap-2 pb-1">
              <Badge variant="info" className="text-[10px]">Apertura de Ejercicio</Badge>
            </div>

            <div className="space-y-1.5">
              <Label required>Período Contable Abierto</Label>
              <Select
                required
                value={saldoForm.periodo}
                onChange={(e) => setSaldoForm({ ...saldoForm, periodo: e.target.value })}
              >
                <option value="">Seleccionar Período Abierto</option>
                {periodosAbiertos.map((p) => (
                  <option key={p.id} value={p.id}>{etiquetaPeriodo(p)}</option>
                ))}
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label required>Almacén Físico</Label>
                <Select
                  required
                  value={saldoForm.almacen}
                  onChange={(e) => setSaldoForm({ ...saldoForm, almacen: e.target.value })}
                >
                  <option value="">Seleccionar Almacén</option>
                  {almacenes.map((a) => (
                    <option key={a.id} value={a.id}>{a.codigo} · {a.nombre}</option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label required>Producto en Existencia</Label>
                <Select
                  required
                  value={saldoForm.producto}
                  onChange={(e) => setSaldoForm({ ...saldoForm, producto: e.target.value })}
                >
                  <option value="">Seleccionar Producto</option>
                  {productos.map((p) => (
                    <option key={p.id} value={p.id}>{p.codigo_interno} · {p.descripcion}</option>
                  ))}
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label required>Cantidad Inicial (Unidad Base)</Label>
                <Input
                  required
                  inputMode="decimal"
                  pattern="^\d+(\.\d{1,8})?$"
                  placeholder="Ej. 100.00000000"
                  value={saldoForm.cantidad}
                  onChange={(e) => setSaldoForm({ ...saldoForm, cantidad: e.target.value })}
                  className="font-mono tabular-nums"
                />
              </div>

              <div className="space-y-1.5">
                <Label required>Valor Total PEN</Label>
                <Input
                  required
                  inputMode="decimal"
                  pattern="^-?\d+(\.\d{1,8})?$"
                  placeholder="Ej. 2500.00"
                  value={saldoForm.valor_pen}
                  onChange={(e) => setSaldoForm({ ...saldoForm, valor_pen: e.target.value })}
                  className="font-mono tabular-nums"
                />
              </div>
            </div>

            <div className="rounded-xl border border-indigo-200 bg-indigo-50/50 p-3.5 flex items-center justify-between shadow-2xs">
              <div>
                <span className="text-xs text-indigo-950 font-semibold block">CPP Inicial Informativo:</span>
                <span className="text-[10px] text-slate-500">Valor Total PEN / Cantidad (ROUND_HALF_UP a 6 decimales)</span>
              </div>
              <strong className="font-mono text-lg text-indigo-700 tabular-nums">
                S/ {cppInformativo}
              </strong>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal: Nota Interna (Crear / Editar) */}
      {notaFormVisible && (
        <Modal
          isOpen={notaFormVisible}
          onClose={() => setNotaFormVisible(false)}
          maxWidth="5xl"
          title={notaEditando ? `Editar Nota Interna #${notaEditando.id}` : 'Nueva Nota Interna de Inventario'}
          description="Registro de hechos operacionales de inventario (mermas, desmedros, consumos internos y ajustes)."
          icon={<FileWarning className="h-5 w-5" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setNotaFormVisible(false)}>
                Cancelar
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  const form = document.getElementById('form-nota-interna') as HTMLFormElement
                  if (form) form.requestSubmit()
                }}
                isLoading={saving}
              >
                <Save className="h-4 w-4 mr-1.5" />
                {notaEditando ? 'Guardar Nota' : 'Crear Nota'}
              </Button>
            </div>
          }
        >
          <form id="form-nota-interna" onSubmit={guardarNota} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label required>Período Contable</Label>
                <Select
                  required
                  value={notaForm.periodo}
                  onChange={(e) => setNotaForm((prev) => ({ ...prev, periodo: e.target.value }))}
                >
                  <option value="">Seleccionar Período</option>
                  {periodosAbiertos.map((p) => (
                    <option key={p.id} value={p.id}>{etiquetaPeriodo(p)}</option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1">
                <Label required>Almacén Físico</Label>
                <Select
                  required
                  value={notaForm.almacen}
                  onChange={(e) => setNotaForm((actual) => ({ ...actual, almacen: e.target.value }))}
                >
                  <option value="">Seleccionar Almacén</option>
                  {almacenes.map((a) => (
                    <option key={a.id} value={a.id}>{a.codigo} · {a.nombre}</option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1">
                <Label required>Fecha</Label>
                <Input
                  required
                  name="fecha"
                  type="date"
                  min={periodoNotaSeleccionado?.fecha_inicio}
                  max={periodoNotaSeleccionado?.fecha_fin}
                  value={notaForm.fecha}
                  onChange={(e) => setNotaForm((actual) => ({ ...actual, fecha: e.target.value }))}
                  className="font-mono tabular-nums"
                />
              </div>
            </div>

            <div className="space-y-1">
              <Label required>Tipo de Operación Interna (SUNAT Tabla 12)</Label>
              <Select
                required
                value={notaForm.tipo_operacion}
                onChange={(e) => setNotaForm((actual) => ({ ...actual, tipo_operacion: e.target.value }))}
              >
                <option value="">Seleccionar Tipo de Operación</option>
                {tiposSeleccionables.map((tipo) => (
                  <option key={tipo.id} value={tipo.id}>
                    {tipo.codigo_interno} · {tipo.descripcion} {TIPOS_ADMIN.has(tipo.codigo_interno) ? '— [Exclusivo ADMIN]' : ''}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-1">
              <Label required>Motivo o Justificación Operativa</Label>
              <textarea
                required
                maxLength={500}
                rows={2}
                placeholder="Explicación detallada de la merma, desmedro, rotura, autoconsumo o ajuste..."
                value={notaForm.motivo}
                onChange={(e) => setNotaForm((actual) => ({ ...actual, motivo: e.target.value }))}
                className="w-full rounded-md border border-slate-200 bg-white p-2.5 text-xs text-slate-900 shadow-xs focus:ring-2 focus:ring-slate-900 focus:outline-none"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Responsable / Operador</Label>
                <Input
                  maxLength={200}
                  placeholder="Nombre de quien reporta o autoriza"
                  value={notaForm.responsable}
                  onChange={(e) => setNotaForm((actual) => ({ ...actual, responsable: e.target.value }))}
                />
              </div>

              <div className="space-y-1">
                <Label>Sustento Legal / Documento (SUNAT)</Label>
                <Input
                  maxLength={500}
                  placeholder="Ej. Acta Notarial de Destrucción N° 124-2026 / Informe Técnico"
                  value={notaForm.archivo_sustento}
                  onChange={(e) => setNotaForm((actual) => ({ ...actual, archivo_sustento: e.target.value }))}
                />
              </div>
            </div>

            {/* Adjuntar Informe Técnico / Sustento PDF */}
            <div className="rounded-xl border border-slate-200/90 bg-slate-50/70 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <Label>Informe Técnico / Acta en PDF (Opcional, máx. 5 MB)</Label>
                  <span className="text-[10px] text-slate-500 block">
                    Huella digital criptográfica SHA-256 para sustento tributario SUNAT
                  </span>
                </div>
                {notaEditando?.sustento_pdf?.tiene_pdf && !pdfSustento && (
                  <Badge variant="success" size="sm" className="font-mono text-[10px]">
                    <ShieldCheck className="h-3 w-3 mr-1" />
                    PDF Vinculado
                  </Badge>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <label className="cursor-pointer inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-2xs">
                  <Paperclip className="h-3.5 w-3.5 text-slate-500" />
                  <span>{pdfSustento ? 'Cambiar PDF' : (notaEditando?.sustento_pdf?.tiene_pdf ? 'Reemplazar PDF' : 'Seleccionar PDF')}</span>
                  <input
                    type="file"
                    accept=".pdf,application/pdf"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0] || null
                      if (file && !file.name.toLowerCase().endsWith('.pdf')) {
                        setError('El archivo debe tener extensión .pdf.')
                        return
                      }
                      setPdfSustento(file)
                    }}
                  />
                </label>

                {pdfSustento && (
                  <div className="flex items-center gap-2 text-xs bg-indigo-50 border border-indigo-200 text-indigo-900 px-3 py-1.5 rounded-lg shadow-2xs">
                    <FileText className="h-4 w-4 text-indigo-600 shrink-0" />
                    <span className="font-mono font-medium truncate max-w-[240px]" title={pdfSustento.name}>
                      {pdfSustento.name}
                    </span>
                    <button
                      type="button"
                      onClick={() => setPdfSustento(null)}
                      className="text-slate-400 hover:text-slate-600 ml-1 p-0.5 rounded"
                      title="Descartar archivo"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}

                {!pdfSustento && notaEditando?.sustento_pdf?.tiene_pdf && (
                  <div className="flex items-center gap-2 text-xs text-slate-600 bg-white border border-slate-200 px-3 py-1.5 rounded-lg">
                    <FileText className="h-3.5 w-3.5 text-emerald-600" />
                    <span className="font-mono truncate max-w-[200px]" title={notaEditando.sustento_pdf.nombre_archivo}>
                      {notaEditando.sustento_pdf.nombre_archivo}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">
                      SHA: {notaEditando.sustento_pdf.sha256.slice(0, 12)}...
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Líneas de Detalle */}
            <div className="space-y-2 pt-2 border-t border-slate-100">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
                    Líneas de Detalle de Productos
                  </h4>
                  <span className="text-[10px] text-slate-400">
                    {notaForm.detalles.length} {notaForm.detalles.length === 1 ? 'línea' : 'líneas'} en borrador
                  </span>
                </div>
                <Button
                  type="button"
                  size="xs"
                  variant="secondary"
                  onClick={() =>
                    setNotaForm((actual) => ({
                      ...actual,
                      detalles: [...actual.detalles, LINEA_INICIAL()],
                    }))
                  }
                >
                  <Plus className="h-3 w-3 mr-1" /> Agregar Línea
                </Button>
              </div>

              <div className="space-y-2">
                {notaForm.detalles.map((linea, indice) => {
                  const stockDisp = obtenerStockDisponible(notaForm.almacen, linea.producto)
                  const productoObj = productos.find((p) => p.id === linea.producto)
                  const excedeStock = Number(linea.cantidad_base || 0) > stockDisp

                  return (
                    <div
                      key={indice}
                      className="p-3 rounded-xl border border-slate-200/90 bg-slate-50/60 space-y-2 shadow-2xs"
                    >
                      <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-2.5">
                        <span className="font-mono text-xs font-bold text-slate-400 px-1 self-center">{indice + 1}</span>

                        <div className="flex-1 space-y-1">
                          <div className="flex items-center justify-between">
                            <Label required>Producto</Label>
                            {linea.producto > 0 && (
                              <span className="text-[11px] font-mono text-slate-500">
                                Stock disp: <strong className={excedeStock ? 'text-rose-600 font-bold' : 'text-slate-800'}>{formatearDecimal(stockDisp, { min: 2, max: 4 })}</strong> {productoObj?.unidad_base?.codigo || ''}
                              </span>
                            )}
                          </div>
                          <Select
                            required
                            value={linea.producto || ''}
                            onChange={(e) => actualizarLinea(indice, { producto: Number(e.target.value) })}
                          >
                            <option value="">Seleccionar Producto</option>
                            {productos.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.codigo_interno} · {p.descripcion}
                              </option>
                            ))}
                          </Select>
                        </div>

                        <div className="w-full sm:w-36 space-y-1">
                          <Label required>Cantidad Base</Label>
                          <Input
                            required
                            inputMode="decimal"
                            pattern="^\d+(\.\d{1,8})?$"
                            placeholder="1.0000"
                            value={linea.cantidad_base}
                            onChange={(e) => actualizarLinea(indice, { cantidad_base: e.target.value })}
                            className={`font-mono tabular-nums ${excedeStock ? 'border-rose-400 focus:ring-rose-500' : ''}`}
                          />
                        </div>

                        {esAdmin && (
                          <div className="w-full sm:w-32 space-y-1">
                            <Label>Costo Unit. PEN</Label>
                            <Input
                              inputMode="decimal"
                              pattern="^-?\d+(\.\d{1,8})?$"
                              placeholder="Auto"
                              value={linea.costo_unitario_pen ?? ''}
                              onChange={(e) =>
                                actualizarLinea(indice, { costo_unitario_pen: e.target.value || null })
                              }
                              className="font-mono tabular-nums"
                            />
                          </div>
                        )}

                        {esAdmin && (
                          <div className="w-full sm:w-32 space-y-1">
                            <Label>Valor Ajuste PEN</Label>
                            <Input
                              inputMode="decimal"
                              pattern="^-?\d+(\.\d{1,8})?$"
                              placeholder="Auto"
                              value={linea.valor_ajuste_pen ?? ''}
                              onChange={(e) =>
                                actualizarLinea(indice, { valor_ajuste_pen: e.target.value || null })
                              }
                              className="font-mono tabular-nums"
                            />
                          </div>
                        )}

                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          disabled={notaForm.detalles.length === 1}
                          onClick={() =>
                            setNotaForm((actual) => ({
                              ...actual,
                              detalles: actual.detalles.filter((_, posicion) => posicion !== indice),
                            }))
                          }
                          className="text-slate-400 hover:text-rose-600 self-center sm:self-end mb-1"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>

                      {excedeStock && linea.producto > 0 && Number(linea.cantidad_base || 0) > 0 && (
                        <div className="flex items-center gap-1.5 text-[11px] text-amber-700 bg-amber-50 px-2.5 py-1 rounded-md border border-amber-200">
                          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                          <span>Atención: La cantidad ingresada supera el stock actual disponible ({stockDisp}). Si la nota es de salida, el motor Kardex rechazará la confirmación por stock insuficiente.</span>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal: Visor Detalle Nota Interna (Solo Lectura) */}
      {detalleNota && (
        <Modal
          isOpen={Boolean(detalleNota)}
          onClose={() => setDetalleNota(null)}
          maxWidth="4xl"
          title={`Ficha Técnica — Nota Interna #${detalleNota.id}`}
          description={`Operación: ${detalleNota.tipo_operacion_codigo} · ${detalleNota.tipo_operacion_descripcion}`}
          icon={<Eye className="h-5 w-5" />}
          footer={
            <Button variant="secondary" onClick={() => setDetalleNota(null)}>
              Cerrar Ficha
            </Button>
          }
        >
          <div className="space-y-4">
            {/* Cabecera */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3.5 rounded-xl border border-slate-200 bg-slate-50/70 text-xs">
              <div>
                <span className="text-[10px] text-slate-400 font-semibold uppercase block">Fecha Operación</span>
                <span className="font-mono font-medium text-slate-900">{detalleNota.fecha}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-semibold uppercase block">Período Contable</span>
                <span className="font-medium text-slate-800">{detalleNota.periodo_descripcion}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-semibold uppercase block">Almacén</span>
                <span className="font-mono font-bold text-slate-900">{detalleNota.almacen_codigo}</span>
                <span className="text-[10px] text-slate-500 block truncate">{detalleNota.almacen_nombre}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-semibold uppercase block">Estado</span>
                <Badge
                  variant={
                    detalleNota.estado === 'CONFIRMADO'
                      ? 'success'
                      : detalleNota.estado === 'ANULADO'
                      ? 'destructive'
                      : 'warning'
                  }
                  dot
                >
                  {detalleNota.estado}
                </Badge>
              </div>
            </div>

            {/* Motivo y Sustento */}
            <div className="space-y-2 text-xs">
              <div className="rounded-lg border border-slate-200 p-3 bg-white">
                <strong className="text-slate-900 block mb-0.5">Motivo o Justificación:</strong>
                <p className="text-slate-600 leading-relaxed">{detalleNota.motivo}</p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div className="rounded-lg border border-slate-200 p-2.5 bg-white">
                  <strong className="text-slate-900 text-[11px] block">Responsable / Operador:</strong>
                  <span className="text-slate-600">{detalleNota.responsable || '—'}</span>
                </div>
                <div className="rounded-lg border border-slate-200 p-2.5 bg-white">
                  <strong className="text-slate-900 text-[11px] block">Sustento Legal (SUNAT):</strong>
                  <span className="text-slate-600">{detalleNota.archivo_sustento || '—'}</span>
                </div>
              </div>

              {detalleNota.observacion && (
                <div className="rounded-lg border border-slate-200 p-3 bg-slate-50 text-slate-700">
                  <strong className="text-slate-900 block mb-0.5">Observaciones / Historial:</strong>
                  <p className="whitespace-pre-line text-xs font-mono">{detalleNota.observacion}</p>
                </div>
              )}

              {/* Sustento Documentario PDF */}
              {detalleNota.sustento_pdf?.tiene_pdf ? (
                <div className="p-3 rounded-xl border border-emerald-200 bg-emerald-50/70 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5 shadow-2xs">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-1.5 text-emerald-950 font-bold text-xs">
                      <ShieldCheck className="h-4 w-4 text-emerald-600" />
                      <span>Documento de Sustento PDF Verificado</span>
                    </div>
                    <div className="text-[11px] text-slate-600 font-mono">
                      {detalleNota.sustento_pdf.nombre_archivo}
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono">
                      SHA-256: {detalleNota.sustento_pdf.sha256}
                    </div>
                  </div>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    className="border-emerald-300 text-emerald-800 hover:bg-emerald-100 self-start sm:self-center"
                    onClick={async () => {
                      if (!detalleNota.sustento_pdf) return
                      try {
                        setDescargandoPdf(true)
                        await descargarSustentoPdfNotaInterna(detalleNota.id, detalleNota.sustento_pdf.nombre_archivo)
                      } catch {
                        setError('No se pudo descargar el archivo PDF.')
                      } finally {
                        setDescargandoPdf(false)
                      }
                    }}
                    disabled={descargandoPdf}
                  >
                    <Download className="h-3.5 w-3.5 mr-1 text-emerald-700" />
                    Descargar PDF Sustento
                  </Button>
                </div>
              ) : (
                detalleNota.estado !== 'ANULADO' && (
                  <div className="p-3 rounded-xl border border-slate-200 bg-slate-50 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                    <div>
                      <span className="text-xs font-semibold text-slate-700 block">Sin sustento PDF adjunto</span>
                      <span className="text-[10px] text-slate-500">Puede adjuntar un informe técnico o acta notarial en PDF</span>
                    </div>
                    <label className="cursor-pointer inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 bg-white text-xs font-semibold text-slate-700 hover:bg-slate-50 shadow-2xs self-start sm:self-center">
                      {subiendoPdfDetalle ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-500" />
                      ) : (
                        <Upload className="h-3.5 w-3.5 text-slate-500" />
                      )}
                      <span>{subiendoPdfDetalle ? 'Adjuntando...' : 'Adjuntar PDF'}</span>
                      <input
                        type="file"
                        accept=".pdf,application/pdf"
                        className="hidden"
                        disabled={subiendoPdfDetalle}
                        onChange={async (e) => {
                          const file = e.target.files?.[0]
                          if (!file) return
                          if (!file.name.toLowerCase().endsWith('.pdf')) {
                            setError('El archivo debe tener extensión .pdf.')
                            return
                          }
                          try {
                            setSubiendoPdfDetalle(true)
                            const notaActualizada = await subirSustentoPdfNotaInterna(
                              detalleNota.id,
                              file,
                              detalleNota.archivo_sustento || undefined
                            )
                            setDetalleNota(notaActualizada)
                            setSuccess('Documento de sustento PDF adjuntado correctamente.')
                            await refrescar()
                          } catch (err) {
                            setError(extraerError(err))
                          } finally {
                            setSubiendoPdfDetalle(false)
                          }
                        }}
                      />
                    </label>
                  </div>
                )
              )}
            </div>

            {/* Líneas de detalle */}
            <div className="space-y-1.5 pt-2 border-t border-slate-200">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
                Productos Registrados ({detalleNota.detalles.length})
              </h4>
              <Table containerClassName="border rounded-lg max-h-60">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">#</TableHead>
                    <TableHead className="w-32">Código</TableHead>
                    <TableHead>Descripción</TableHead>
                    <TableHead className="w-24 text-center">Unidad</TableHead>
                    <TableHead numeric className="w-32">Cantidad Base</TableHead>
                    {detalleNota.detalles.some((l) => l.costo_unitario_pen !== null) && (
                      <TableHead numeric className="w-32">Costo Unit. PEN</TableHead>
                    )}
                    {detalleNota.detalles.some((l) => l.valor_ajuste_pen !== null) && (
                      <TableHead numeric className="w-32">Ajuste PEN</TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detalleNota.detalles.map((linea, idx) => (
                    <TableRow key={linea.id || idx}>
                      <TableCell className="font-mono text-slate-400 text-xs">{idx + 1}</TableCell>
                      <TableCell className="font-mono font-bold text-slate-900 text-xs">{linea.producto_codigo}</TableCell>
                      <TableCell className="text-slate-700 text-xs">{linea.producto_descripcion}</TableCell>
                      <TableCell className="text-center">
                        <Badge variant="outline" className="font-mono text-[10px]">{linea.unidad_base_codigo || 'NIU'}</Badge>
                      </TableCell>
                      <TableCell numeric className="font-mono font-bold text-slate-900 tabular-nums">
                        {formatearDecimal(linea.cantidad_base, { min: 2, max: 8 })}
                      </TableCell>
                      {detalleNota.detalles.some((l) => l.costo_unitario_pen !== null) && (
                        <TableCell numeric className="font-mono text-slate-700 tabular-nums">
                          {linea.costo_unitario_pen ? `S/ ${formatearDecimal(linea.costo_unitario_pen, { min: 4, max: 6 })}` : '—'}
                        </TableCell>
                      )}
                      {detalleNota.detalles.some((l) => l.valor_ajuste_pen !== null) && (
                        <TableCell numeric className="font-mono text-slate-700 tabular-nums">
                          {linea.valor_ajuste_pen ? `S/ ${formatearDecimal(linea.valor_ajuste_pen)}` : '—'}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </Modal>
      )}

      {/* Modal: Visor Detalle Saldo Inicial (Solo Lectura) */}
      {detalleSaldo && (
        <Modal
          isOpen={Boolean(detalleSaldo)}
          onClose={() => setDetalleSaldo(null)}
          maxWidth="2xl"
          title={`Detalle de Saldo Inicial #${detalleSaldo.id}`}
          description={`Inventario de apertura para ${detalleSaldo.producto_codigo}`}
          icon={<Eye className="h-5 w-5" />}
          footer={
            <Button variant="secondary" onClick={() => setDetalleSaldo(null)}>
              Cerrar
            </Button>
          }
        >
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-2 gap-3 p-3.5 rounded-xl border border-slate-200 bg-slate-50/70">
              <div>
                <span className="text-[10px] text-slate-400 font-semibold uppercase block">Período Contable</span>
                <span className="font-medium text-slate-900">{detalleSaldo.periodo_descripcion}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-semibold uppercase block">Estado</span>
                <Badge variant={detalleSaldo.estado === 'CONFIRMADO' ? 'success' : 'warning'} dot>
                  {detalleSaldo.estado}
                </Badge>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-semibold uppercase block">Almacén Físico</span>
                <span className="font-mono font-bold text-slate-900">{detalleSaldo.almacen_codigo}</span>
                <span className="text-slate-500 block truncate">{detalleSaldo.almacen_nombre}</span>
              </div>
              <div>
                <span className="text-[10px] text-slate-400 font-semibold uppercase block">Producto</span>
                <span className="font-mono font-bold text-slate-900">{detalleSaldo.producto_codigo}</span>
                <span className="text-slate-500 block truncate">{detalleSaldo.producto_descripcion}</span>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3 p-3.5 rounded-xl border border-indigo-100 bg-indigo-50/40">
              <div>
                <span className="text-[10px] text-indigo-900 font-semibold uppercase block">Cantidad Inicial</span>
                <span className="font-mono text-base font-bold text-slate-900 tabular-nums">
                  {formatearDecimal(detalleSaldo.cantidad, { min: 4, max: 8 })}
                </span>
                <span className="text-[10px] text-slate-400 block">{detalleSaldo.unidad_base_codigo || 'NIU'}</span>
              </div>
              <div>
                <span className="text-[10px] text-indigo-900 font-semibold uppercase block">Valor Total PEN</span>
                <span className="font-mono text-base font-bold text-slate-900 tabular-nums">
                  S/ {formatearDecimal(detalleSaldo.valor_pen)}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-indigo-900 font-semibold uppercase block">CPP Inicial</span>
                <span className="font-mono text-base font-bold text-indigo-700 tabular-nums">
                  S/ {formatearDecimal(detalleSaldo.cpp_inicial, { min: 6, max: 6 })}
                </span>
              </div>
            </div>
          </div>
        </Modal>
      )}

      {/* Modal: Anular con Extorno Contable */}
      {notaParaExtorno && (
        <Modal
          isOpen={Boolean(notaParaExtorno)}
          onClose={() => {
            setNotaParaExtorno(null)
            setMotivoExtorno('')
          }}
          maxWidth="lg"
          title={`Anular con Extorno — Nota Interna #${notaParaExtorno.id}`}
          description="Reversión legal con contra-asiento en Kardex Permanente."
          icon={<RotateCcw className="h-5 w-5 text-amber-600" />}
          footer={
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setNotaParaExtorno(null)
                  setMotivoExtorno('')
                }}
              >
                Cancelar
              </Button>
              <Button
                variant="destructive"
                onClick={ejecutarExtornoNota}
                isLoading={saving}
                disabled={!motivoExtorno.trim()}
              >
                <Ban className="h-4 w-4 mr-1.5" />
                Confirmar Anulación y Extorno
              </Button>
            </div>
          }
        >
          <div className="space-y-4 text-xs">
            <div className="flex items-start gap-2.5 p-3 rounded-xl border border-amber-200 bg-amber-50/80 text-amber-900">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-amber-600" />
              <div className="leading-relaxed">
                <strong>Advertencia de Integridad Contable:</strong> Al anular una nota confirmada, los movimientos
                originales permanecerán intactos y se insertará un contra-asiento con{' '}
                <code className="font-mono text-[11px] bg-amber-100 px-1 py-0.5 rounded">es_extorno = True</code> en el Kardex.
                El costo promedio ponderado (CPP) y el stock de los productos afectados serán recalculados cronológicamente.
              </div>
            </div>

            <div className="p-3 rounded-lg border border-slate-200 bg-slate-50 space-y-1">
              <div><strong className="text-slate-900">Operación:</strong> {notaParaExtorno.tipo_operacion_codigo} · {notaParaExtorno.tipo_operacion_descripcion}</div>
              <div><strong className="text-slate-900">Almacén:</strong> {notaParaExtorno.almacen_codigo} — {notaParaExtorno.almacen_nombre}</div>
              <div><strong className="text-slate-900">Fecha original:</strong> {notaParaExtorno.fecha}</div>
            </div>

            <div className="space-y-1.5">
              <Label required>Motivo Obligatorio de Anulación</Label>
              <textarea
                required
                rows={3}
                placeholder="Indique con claridad el error, motivo tributario o justificación del extorno..."
                value={motivoExtorno}
                onChange={(e) => setMotivoExtorno(e.target.value)}
                className="w-full rounded-md border border-slate-200 bg-white p-2.5 text-xs text-slate-900 shadow-xs focus:ring-2 focus:ring-rose-500 focus:outline-none"
              />
            </div>
          </div>
        </Modal>
      )}

      {/* Modal: Confirmar Eliminación Física de Borrador */}
      {borradorAEliminar && (
        <Modal
          isOpen={Boolean(borradorAEliminar)}
          onClose={() => setBorradorAEliminar(null)}
          maxWidth="md"
          title="Eliminar Registro Borrador"
          description="Eliminación física definitiva de la base de datos."
          icon={<Trash2 className="h-5 w-5 text-rose-600" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setBorradorAEliminar(null)}>
                Cancelar
              </Button>
              <Button variant="destructive" onClick={ejecutarEliminacionBorrador} isLoading={saving}>
                <Trash2 className="h-4 w-4 mr-1.5" />
                Eliminar Definitivamente
              </Button>
            </div>
          }
        >
          <div className="space-y-3 text-xs leading-relaxed text-slate-600">
            <p>
              ¿Estás seguro de eliminar físicamente{' '}
              <strong className="text-slate-900">{borradorAEliminar.descripcion}</strong>?
            </p>
            <p className="text-slate-500">
              Dado que este registro está en estado <strong className="text-amber-700">BORRADOR</strong>, no ha impactado
              Kardex ni balances valorizados. Desaparecerá por completo sin dejar registros anulados innecesarios.
            </p>
          </div>
        </Modal>
      )}

      {/* Modal: Importación Masiva de Saldos Iniciales vía Excel (.xlsx) */}
      {importarModalOpen && (
        <Modal
          isOpen={importarModalOpen}
          onClose={cerrarModalImportar}
          title="Importación Masiva de Saldos Iniciales (Operación 16 SUNAT)"
          description="Carga y valida masivamente saldos iniciales usando la plantilla oficial con previsualización fila por fila antes de impactar el Kardex."
          icon={<FileSpreadsheet className="h-5 w-5 text-indigo-600" />}
          maxWidth="5xl"
        >
          <div className="space-y-4">
            {/* Paso 1: Período, Almacén y Descarga de Plantilla */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="space-y-1.5">
                <Label required>Período Contable Abierto</Label>
                <Select
                  required
                  value={importPeriodoId}
                  onChange={(e) => {
                    setImportPeriodoId(e.target.value)
                    setResultadoImportacion(null)
                    setErrorImportacion(null)
                  }}
                >
                  <option value="">Seleccionar Período</option>
                  {periodosAbiertos.map((p) => (
                    <option key={p.id} value={p.id}>{etiquetaPeriodo(p)}</option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label required>Almacén Destino</Label>
                <Select
                  required
                  value={importAlmacenId}
                  onChange={(e) => {
                    setImportAlmacenId(e.target.value)
                    setResultadoImportacion(null)
                    setErrorImportacion(null)
                  }}
                >
                  <option value="">Seleccionar Almacén</option>
                  {almacenes.map((a) => (
                    <option key={a.id} value={a.id}>{a.codigo} · {a.nombre}</option>
                  ))}
                </Select>
              </div>

              <div className="flex flex-col justify-end space-y-1.5">
                <Label className="text-slate-600">Plantilla Oficial</Label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleDescargarPlantilla}
                  disabled={descargandoPlantilla}
                  className="w-full justify-center"
                >
                  {descargandoPlantilla ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                  ) : (
                    <Download className="h-3.5 w-3.5 mr-1.5 text-indigo-600" />
                  )}
                  Descargar Plantilla (.xlsx)
                </Button>
              </div>
            </div>

            {/* Paso 2: Selección de archivo y botón Previsualizar */}
            <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-3">
              <span className="text-xs font-semibold text-slate-800 uppercase tracking-wide flex items-center gap-1.5">
                <Upload className="h-4 w-4 text-indigo-600" />
                Archivo Excel (.xlsx) con Saldos Iniciales
              </span>
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
                <div className="flex-1">
                  <Input
                    type="file"
                    accept=".xlsx"
                    onChange={(e) => {
                      const f = e.target.files?.[0] || null
                      setArchivoExcel(f)
                      setResultadoImportacion(null)
                      setErrorImportacion(null)
                    }}
                    className="text-xs file:mr-2 file:py-1 file:px-2 file:rounded-md file:border-0 file:text-xs file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
                  />
                </div>
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  disabled={!archivoExcel || !importPeriodoId || !importAlmacenId || procesandoImportacion}
                  onClick={() => handleProcesarExcel('PREVISUALIZAR')}
                >
                  {procesandoImportacion ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                  ) : (
                    <Search className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  Previsualizar Saldos
                </Button>
              </div>
              {archivoExcel && (
                <p className="text-[11px] text-slate-500 font-mono">
                  Archivo seleccionado: {archivoExcel.name}
                </p>
              )}
            </div>

            {errorImportacion && (
              <div
                role="alert"
                className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50/90 p-3 text-xs text-rose-700 animate-in fade-in"
              >
                <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
                <span className="font-medium leading-relaxed">{errorImportacion}</span>
              </div>
            )}

            {/* Paso 3: Diagnóstico Previo y Tabla de Filas */}
            {resultadoImportacion && (
              <div className="space-y-3 pt-2 border-t border-slate-200">
                {/* KPIs de Diagnóstico */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <div className="rounded-lg border border-slate-200 bg-white p-3 text-center">
                    <span className="text-xs text-slate-500 block">Total Filas</span>
                    <span className="text-lg font-bold text-slate-900">{resultadoImportacion.resumen.total_filas}</span>
                  </div>
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3 text-center">
                    <span className="text-xs text-emerald-700 font-medium flex items-center justify-center gap-1">
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> Nuevos
                    </span>
                    <span className="text-lg font-bold text-emerald-700">{resultadoImportacion.resumen.nuevos ?? 0}</span>
                  </div>
                  <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-3 text-center">
                    <span className="text-xs text-amber-700 font-medium flex items-center justify-center gap-1">
                      <AlertTriangle className="h-3.5 w-3.5 text-amber-600" /> A Actualizar
                    </span>
                    <span className="text-lg font-bold text-amber-700">{resultadoImportacion.resumen.actualizables ?? 0}</span>
                  </div>
                  <div className="rounded-lg border border-rose-200 bg-rose-50/50 p-3 text-center">
                    <span className="text-xs text-rose-700 font-medium flex items-center justify-center gap-1">
                      <AlertCircle className="h-3.5 w-3.5 text-rose-600" /> Con Error
                    </span>
                    <span className="text-lg font-bold text-rose-700">{resultadoImportacion.resumen.con_error ?? 0}</span>
                  </div>
                </div>

                {/* Filtro y Header de Tabla */}
                <div className="flex items-center justify-between text-xs pt-1">
                  <span className="font-semibold text-slate-700">Detalle de pre-validación fila por fila:</span>
                  <div className="flex items-center gap-1">
                    {(['TODOS', 'NUEVO', 'ACTUALIZAR', 'ERROR'] as const).map((filtro) => (
                      <button
                        key={filtro}
                        type="button"
                        onClick={() => setFiltroEstadoDiagnostico(filtro)}
                        className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                          filtroEstadoDiagnostico === filtro
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                        }`}
                      >
                        {filtro}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Tabla de Filas con Scroll */}
                <div className="max-h-60 overflow-y-auto rounded-lg border border-slate-200 bg-white">
                  <Table>
                    <TableHeader className="sticky top-0 bg-slate-50 z-10 shadow-xs">
                      <TableRow>
                        <TableHead className="w-12 text-center text-xs">Fila</TableHead>
                        <TableHead className="w-28 text-xs">Código</TableHead>
                        <TableHead className="text-xs">Descripción</TableHead>
                        <TableHead className="w-24 text-right text-xs">Cantidad</TableHead>
                        <TableHead className="w-24 text-right text-xs">CPP Inicial (S/)</TableHead>
                        <TableHead className="w-24 text-right text-xs">Valor Total (S/)</TableHead>
                        <TableHead className="w-24 text-center text-xs">Estado</TableHead>
                        <TableHead className="text-xs">Observación</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {resultadoImportacion.filas
                        .filter((f) => filtroEstadoDiagnostico === 'TODOS' || f.estado_fila === filtroEstadoDiagnostico)
                        .map((f) => (
                          <TableRow key={f.numero_fila} className={f.estado_fila === 'ERROR' ? 'bg-rose-50/40' : undefined}>
                            <TableCell className="text-center font-mono text-xs">{f.numero_fila}</TableCell>
                            <TableCell className="font-mono text-xs font-semibold">{f.codigo_interno}</TableCell>
                            <TableCell className="text-xs">{f.descripcion_producto || '—'}</TableCell>
                            <TableCell className="text-right font-mono text-xs">
                              {f.cantidad ? formatearDecimal(f.cantidad, { min: 2, max: 4 }) : '—'}
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs">
                              {f.cpp_inicial ? `S/ ${formatearDecimal(f.cpp_inicial, { min: 2, max: 6 })}` : '—'}
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs">
                              {f.valor_pen ? `S/ ${formatearDecimal(f.valor_pen, { min: 2, max: 2 })}` : '—'}
                            </TableCell>
                            <TableCell className="text-center">
                              {f.estado_fila === 'NUEVO' && (
                                <Badge variant="success" size="xs">NUEVO</Badge>
                              )}
                              {f.estado_fila === 'ACTUALIZAR' && (
                                <Badge variant="warning" size="xs">ACTUALIZAR</Badge>
                              )}
                              {f.estado_fila === 'ERROR' && (
                                <Badge variant="destructive" size="xs">ERROR</Badge>
                              )}
                            </TableCell>
                            <TableCell className="text-xs">
                              {f.observacion ? (
                                <span className={f.estado_fila === 'ERROR' ? 'text-rose-700 font-medium' : 'text-slate-600'}>
                                  {f.observacion}
                                </span>
                              ) : (
                                <span className="text-slate-400 text-[11px]">Correcto</span>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                    </TableBody>
                  </Table>
                </div>

                {/* Opción de Confirmación Automática */}
                <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-3 flex items-start gap-3">
                  <input
                    type="checkbox"
                    id="chkAutoConfirmarSaldos"
                    checked={autoConfirmar}
                    onChange={(e) => setAutoConfirmar(e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <label htmlFor="chkAutoConfirmarSaldos" className="text-xs text-slate-700 cursor-pointer">
                    <span className="font-semibold block text-slate-900">
                      Confirmar automáticamente en el Kardex (Operación 16 SUNAT) al importar
                    </span>
                    Si está marcado, registra los saldos en estado <strong>CONFIRMADO</strong>, genera los movimientos de apertura en el Kardex y actualiza los costos promedio. Si se desmarca, se guardarán como <strong>BORRADOR</strong> para revisión manual previa.
                  </label>
                </div>

                {/* Alerta de Validación */}
                {(resultadoImportacion.resumen.con_error ?? 0) > 0 ? (
                  <p className="text-xs text-rose-700 font-medium flex items-center gap-1.5">
                    <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
                    El archivo contiene {resultadoImportacion.resumen.con_error} fila(s) con error. Corrija los códigos o importes en el Excel antes de procesar la importación definitiva.
                  </p>
                ) : (
                  <p className="text-xs text-emerald-700 font-medium flex items-center gap-1.5">
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
                    Validación exitosa. Listo para procesar {(resultadoImportacion.resumen.nuevos ?? 0) + (resultadoImportacion.resumen.actualizables ?? 0)} saldo(s) inicial(es).
                  </p>
                )}
              </div>
            )}

            {/* Acciones del Modal */}
            <div className="flex items-center justify-end gap-2 pt-4 border-t border-slate-200">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={cerrarModalImportar}
                disabled={procesandoImportacion}
              >
                Cancelar
              </Button>
              <Button
                type="button"
                variant="primary"
                size="sm"
                disabled={
                  !resultadoImportacion ||
                  (resultadoImportacion.resumen.con_error ?? 0) > 0 ||
                  ((resultadoImportacion.resumen.nuevos ?? 0) === 0 && (resultadoImportacion.resumen.actualizables ?? 0) === 0) ||
                  procesandoImportacion
                }
                onClick={() => handleProcesarExcel('CONFIRMAR')}
              >
                {procesandoImportacion ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />
                )}
                Procesar Importación ({resultadoImportacion ? (resultadoImportacion.resumen.nuevos ?? 0) + (resultadoImportacion.resumen.actualizables ?? 0) : 0} saldos)
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

export default OperacionesInternasPage
