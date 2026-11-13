import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useAuth } from '../../context/useAuth';
import {
  actualizarEquivalencia,
  corregirCampoCaptura,
  crearEquivalencia,
  eliminarCaptura,
  generarBorradorDesdeCaptura,
  obtenerCapturaDetalle,
  obtenerCapturas,
  obtenerEquivalencias,
  subirCaptura,
  sugerirEquivalencia,
  type CapturaCampo,
  type DocumentoCaptura,
  type GenerarBorradorResponse,
  type ProductoEquivalencia,
  type SugerirEquivalenciaResponse,
} from '../../api/captura';
import { mensajeDeError, mensajesDeErrorApi } from '../../utils/errores';
import {
  DESCRIPCION_TIPO_CAPTURA,
  PASOS_CAPTURA,
  TIPOS_CAPTURA,
  acceptCaptura,
  formatosVisibles,
  pasoActualCaptura,
  tipoSugerido,
  validarArchivoCaptura,
  type TipoCaptura,
} from '../../utils/capturaArchivos';
import { diferirCarga } from '../../utils/efectos';
import {
  getAlmacenes,
  getProductos,
  getProductoUnidades,
  getTerceros,
  getUnidadesMedida,
  type Almacen,
  type Producto,
  type ProductoUnidad,
  type Tercero,
  type UnidadMedida,
} from '../../api/inventario';
import {
  ScanLine,
  Upload,
  FileCode,
  RotateCcw,
  FileSpreadsheet,
  Search,
  Sparkles,
  Plus,
  Loader2,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Check,
  X,
  Edit3,
  Save,
  Filter,
  Eye,
  EyeOff,
  ZoomIn,
  ZoomOut,
  RotateCw,
  Trash2,
  FileText,
  Image as ImageIcon,
  Maximize2,
  Minimize2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { PageHeader } from '../../components/ui/page-header';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Select } from '../../components/ui/select';
import { Label } from '../../components/ui/label';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs';
import { formatearDecimal } from '../../utils/decimal';

/** QA2-001: valor del selector para el proveedor del comprobante que aún no está registrado. */
const PROVEEDOR_DE_CAPTURA = 'captura';

export const CapturaHomologacionPage: React.FC = () => {
  const { empresaActiva } = useAuth();

  // Pestaña activa: 'capturas' | 'homologaciones'
  const [activeTab, setActiveTab] = useState<'capturas' | 'homologaciones'>('capturas');

  // Estados de carga y feedback
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Catálogos auxiliares
  const [almacenes, setAlmacenes] = useState<Almacen[]>([]);
  const [terceros, setTerceros] = useState<Tercero[]>([]);
  const [productos, setProductos] = useState<Producto[]>([]);
  const [unidadesMedida, setUnidadesMedida] = useState<UnidadMedida[]>([]);

  // -------------------------------------------------------------
  // ESTADOS PESTAÑA 1: CAPTURAS XML / PDF / OCR
  // -------------------------------------------------------------
  const [capturas, setCapturas] = useState<DocumentoCaptura[]>([]);
  const [selectedCapturaId, setSelectedCapturaId] = useState<number | null>(null);
  const [capturaDetalle, setCapturaDetalle] = useState<DocumentoCaptura | null>(null);

  // Subida de archivos
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTipo, setUploadTipo] = useState<TipoCaptura>('XML');
  const [textoOcr, setTextoOcr] = useState<string>('');
  const [selectedAlmacenId, setSelectedAlmacenId] = useState<number | string>('');

  // Pre-subida y vista previa
  const [preUploadPreviewUrl, setPreUploadPreviewUrl] = useState<string | null>(null);
  const [preUploadFileType, setPreUploadFileType] = useState<'image' | 'pdf' | 'xml' | 'other'>('other');

  // Control de UI y filtros de bandeja
  const [mostrarSubida, setMostrarSubida] = useState<boolean>(false);
  const [busquedaCapturas, setBusquedaCapturas] = useState<string>('');
  const [filtroEstadoCaptura, setFiltroEstadoCaptura] = useState<'todos' | 'pendientes' | 'borradores'>('todos');

  // Visor "Ojo contra Dato"
  const [mostrarVisor, setMostrarVisor] = useState(false);
  const [zoomPct, setZoomPct] = useState<number>(100);
  const [rotacionDeg, setRotacionDeg] = useState<number>(0);
  const [modoAjuste, setModoAjuste] = useState<'pagina' | 'ancho' | 'zoom'>('pagina');
  const [esPantallaCompleta, setEsPantallaCompleta] = useState<boolean>(false);
  const [archivosCache, setArchivosCache] = useState<Record<string, { url: string; tipo: 'image' | 'pdf' | 'xml'; nombre: string }>>({});

  // Edición en línea de campos
  const [editingCampoId, setEditingCampoId] = useState<number | null>(null);
  const [tempValorCorregido, setTempValorCorregido] = useState<string>('');

  // Resultado de generación de borrador
  const [borradorResultado, setBorradorResultado] = useState<GenerarBorradorResponse | null>(null);

  // -------------------------------------------------------------
  // ESTADOS PESTAÑA 2: HOMOLOGACIONES (PRODUCTO_EQUIVALENCIA)
  // -------------------------------------------------------------
  const [equivalencias, setEquivalencias] = useState<ProductoEquivalencia[]>([]);
  const [filtroTerceroId, setFiltroTerceroId] = useState<string>('');
  const [busquedaEquiv, setBusquedaEquiv] = useState<string>('');

  // Formulario Nueva Equivalencia
  const [showEquivModal, setShowEquivModal] = useState(false);
  const [formTerceroId, setFormTerceroId] = useState<string>('');
  const [formCodigoExt, setFormCodigoExt] = useState<string>('');
  const [formDescExt, setFormDescExt] = useState<string>('');
  const [formUnidadExt, setFormUnidadExt] = useState<string>('NIU');
  // RUC del emisor de la captura desde la que se abrió la homologación (QA-002).
  const [rucEsperadoEquiv, setRucEsperadoEquiv] = useState<string>('');
  // QA2-001: captura desde la que se homologa (el backend toma su proveedor y lo registra si falta).
  const [capturaEquivId, setCapturaEquivId] = useState<number | null>(null);
  const [formProductoId, setFormProductoId] = useState<string>('');
  const [productoUnidades, setProductoUnidades] = useState<ProductoUnidad[]>([]);
  const [formProductoUnidadId, setFormProductoUnidadId] = useState<string>('');
  const [formFactor, setFormFactor] = useState<string>('1.00000000');

  // Probador de Sugerencias
  const [showSugerirModal, setShowSugerirModal] = useState(false);
  const [testTerceroId, setTestTerceroId] = useState<string>('');
  const [testCodigoExt, setTestCodigoExt] = useState<string>('');
  const [testDescExt, setTestDescExt] = useState<string>('');
  const [sugerenciaResultado, setSugerenciaResultado] = useState<SugerirEquivalenciaResponse | null>(null);

  // Carga inicial de datos auxiliares
  useEffect(() => {
    if (!empresaActiva) return;
    const cargarAuxiliares = async () => {
      try {
        const [alms, tercs, prods, unds] = await Promise.all([
          getAlmacenes(),
          getTerceros({ tipo: 'proveedor' }),
          getProductos(),
          getUnidadesMedida(),
        ]);
        setAlmacenes(alms);
        setTerceros(tercs);
        setProductos(prods);
        setUnidadesMedida(unds);
        if (alms.length > 0) {
          setSelectedAlmacenId(alms[0].id);
        }
      } catch (err) {
        console.error('Error al cargar catálogos auxiliares:', err);
      }
    };
    cargarAuxiliares();
  }, [empresaActiva]);

  // Cargar lista de capturas
  const cargarCapturas = useCallback(async () => {
    if (!empresaActiva) return;
    try {
      setLoading(true);
      const data = await obtenerCapturas();
      setCapturas(data);
      if (data.length > 0) {
        // Solo se preselecciona la primera captura si aún no hay una elegida.
        setSelectedCapturaId((actual) => (actual === null ? data[0].id : actual));
      }
    } catch (err) {
      setErrorMsg(mensajeDeError(err, ['detail'], 'Error al cargar capturas.'));
    } finally {
      setLoading(false);
    }
  }, [empresaActiva]);

  // Auto-apertura del formulario de subida si no hay comprobantes cargados
  useEffect(() => {
    if (capturas.length === 0) {
      setMostrarSubida(true);
    }
  }, [capturas.length]);

  // Capturas filtradas en la columna izquierda
  const capturasFiltradas = useMemo(() => {
    return capturas.filter((c) => {
      if (filtroEstadoCaptura === 'pendientes' && c.estado_proceso === 'BORRADOR_GENERADO') return false;
      if (filtroEstadoCaptura === 'borradores' && c.estado_proceso !== 'BORRADOR_GENERADO') return false;
      if (!busquedaCapturas.trim()) return true;
      const q = busquedaCapturas.toLowerCase().trim();
      const nombreArchivo = (c.ruta_archivo || '').toLowerCase();
      const hash = (c.hash_sha256 || '').toLowerCase();
      const docSerie = (c.documento_serie_numero || '').toLowerCase();
      const tipo = (c.tipo || '').toLowerCase();
      return nombreArchivo.includes(q) || hash.includes(q) || docSerie.includes(q) || tipo.includes(q);
    });
  }, [capturas, filtroEstadoCaptura, busquedaCapturas]);

  // Cargar lista de equivalencias
  const cargarEquivalencias = useCallback(async () => {
    if (!empresaActiva) return;
    try {
      setLoading(true);
      const tercId = filtroTerceroId ? Number(filtroTerceroId) : undefined;
      const data = await obtenerEquivalencias(tercId);
      setEquivalencias(data);
    } catch (err) {
      setErrorMsg(mensajeDeError(err, ['detail'], 'Error al cargar equivalencias.'));
    } finally {
      setLoading(false);
    }
  }, [empresaActiva, filtroTerceroId]);

  useEffect(() => {
    // Bloque 14: en la pestaña de captura también se cargan las equivalencias, para que el
    // contador de la pestaña "Homologación (n)" no muestre 0 hasta abrirla.
    diferirCarga(
      activeTab === 'capturas'
        ? async () => {
            await cargarCapturas();
            await cargarEquivalencias();
          }
        : cargarEquivalencias,
    );
  }, [activeTab, cargarCapturas, cargarEquivalencias]);

  // Cargar detalle de la captura seleccionada
  useEffect(() => {
    const cargarDetalle = async () => {
      if (!selectedCapturaId) {
        setCapturaDetalle(null);
        return;
      }
      try {
        setBorradorResultado(null);
        const data = await obtenerCapturaDetalle(selectedCapturaId);
        setCapturaDetalle(data);
      } catch (err) {
        console.error('Error al obtener detalle de captura:', err);
      }
    };
    diferirCarga(cargarDetalle);
  }, [selectedCapturaId]);

  // Manejo de cambio de archivo y detección de tipo
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      const tipo = tipoSugerido(file.name, uploadTipo);
      setUploadFile(file);
      setUploadTipo(tipo);
      setSuccessMsg(null);
      const valErr = validarArchivoCaptura(file, tipo);
      setErrorMsg(valErr);
      if (!valErr) {
        if (preUploadPreviewUrl) {
          URL.revokeObjectURL(preUploadPreviewUrl);
        }
        const isImg = file.type.startsWith('image/') || /\.(jpg|jpeg|png|webp)$/i.test(file.name);
        const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
        setPreUploadFileType(isImg ? 'image' : isPdf ? 'pdf' : /\.xml$/i.test(file.name) ? 'xml' : 'other');
        setPreUploadPreviewUrl(URL.createObjectURL(file));
      } else {
        if (preUploadPreviewUrl) URL.revokeObjectURL(preUploadPreviewUrl);
        setPreUploadPreviewUrl(null);
      }
    }
  };

  const handleLimpiarArchivo = () => {
    if (preUploadPreviewUrl) {
      URL.revokeObjectURL(preUploadPreviewUrl);
    }
    setUploadFile(null);
    setPreUploadPreviewUrl(null);
    const el = document.getElementById('captura-file-input') as HTMLInputElement | null;
    if (el) el.value = '';
  };

  // Subir captura
  const handleSubirCaptura = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) {
      setErrorMsg('Seleccione un archivo XML o documento para procesar.');
      return;
    }
    const invalido = validarArchivoCaptura(uploadFile, uploadTipo);
    if (invalido) {
      setErrorMsg(invalido);
      return;
    }
    setErrorMsg(null);
    setSuccessMsg(null);
    const currentFile = uploadFile;
    const currentFileType = preUploadFileType;
    try {
      setLoading(true);
      const res = await subirCaptura(currentFile, uploadTipo, textoOcr);
      setSuccessMsg(res.mensaje || 'Archivo procesado exitosamente.');

      const fileUrl = URL.createObjectURL(currentFile);
      const fileCat: 'image' | 'pdf' | 'xml' = currentFileType === 'image' ? 'image' : currentFileType === 'pdf' ? 'pdf' : 'xml';
      setArchivosCache((prev) => ({
        ...prev,
        [String(res.id)]: { url: fileUrl, tipo: fileCat, nombre: currentFile.name },
        [`hash_${res.hash_sha256}`]: { url: fileUrl, tipo: fileCat, nombre: currentFile.name },
      }));

      if (currentFile.size <= 2 * 1024 * 1024) {
        try {
          const reader = new FileReader();
          reader.onload = () => {
            if (typeof reader.result === 'string') {
              try {
                sessionStorage.setItem(`fk_captura_${res.id}`, reader.result);
                sessionStorage.setItem(`fk_captura_hash_${res.hash_sha256}`, reader.result);
                sessionStorage.setItem(`fk_captura_meta_${res.id}`, JSON.stringify({ tipo: fileCat, nombre: currentFile.name }));
              } catch {
                // Ignore quota
              }
            }
          };
          reader.readAsDataURL(currentFile);
        } catch {
          // Ignore
        }
      }

      setUploadFile(null);
      setPreUploadPreviewUrl(null);
      setTextoOcr('');
      setMostrarVisor(true);
      setMostrarSubida(false);
      await cargarCapturas();
      setSelectedCapturaId(res.id);
    } catch (err) {
      setErrorMsg(mensajesDeErrorApi(err, 'Error al subir y procesar captura.').join(' '));
    } finally {
      setLoading(false);
    }
  };

  // Descartar captura de prueba o errónea
  const handleDescartarCaptura = async (id: number) => {
    if (!window.confirm('¿Está seguro de descartar esta captura? Esta acción no se puede deshacer.')) {
      return;
    }
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      setLoading(true);
      await eliminarCaptura(id);
      setSuccessMsg('Captura descartada exitosamente.');
      if (selectedCapturaId === id) {
        setSelectedCapturaId(null);
        setCapturaDetalle(null);
      }
      await cargarCapturas();
    } catch (err) {
      setErrorMsg(mensajesDeErrorApi(err, 'Error al descartar captura.').join(' '));
    } finally {
      setLoading(false);
    }
  };

  // Auto-activación del visor si la captura tiene campos observados en rojo (< 70%) o alertas
  useEffect(() => {
    if (capturaDetalle?.campos) {
      const hayObservados = capturaDetalle.campos.some(
        (c) => c.confianza !== null && Number(c.confianza) < 70
      );
      const hayAlertas = capturaDetalle.campos.some((c) => c.nombre_campo === 'alerta_validacion');
      if (hayObservados || hayAlertas) {
        setMostrarVisor(true);
      }
    }
  }, [capturaDetalle]);

  // Resolución de la vista previa del comprobante original (memoria o sessionStorage)
  const previewActiva = useMemo(() => {
    if (!capturaDetalle) return null;
    const enMemoria = archivosCache[String(capturaDetalle.id)] || archivosCache[`hash_${capturaDetalle.hash_sha256}`];
    if (enMemoria) return enMemoria;
    try {
      const dataUrl = sessionStorage.getItem(`fk_captura_${capturaDetalle.id}`) || sessionStorage.getItem(`fk_captura_hash_${capturaDetalle.hash_sha256}`);
      const metaStr = sessionStorage.getItem(`fk_captura_meta_${capturaDetalle.id}`);
      if (dataUrl && metaStr) {
        const meta = JSON.parse(metaStr);
        return { url: dataUrl, tipo: meta.tipo as 'image' | 'pdf' | 'xml', nombre: meta.nombre as string };
      }
    } catch {
      // Ignore
    }
    return null;
  }, [capturaDetalle, archivosCache]);

  const handleZoomIn = () => {
    setModoAjuste('zoom');
    setZoomPct((prev) => Math.min(prev + 25, 250));
  };
  const handleZoomOut = () => {
    setModoAjuste('zoom');
    setZoomPct((prev) => Math.max(prev - 25, 50));
  };
  const handleRotate = () => setRotacionDeg((prev) => (prev + 90) % 360);
  const handleResetView = () => {
    setModoAjuste('pagina');
    setZoomPct(100);
    setRotacionDeg(0);
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // No capturar atajos de navegación si el usuario está tipeando en un input o textarea
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return;
      }

      if (e.key === 'Escape' && esPantallaCompleta) {
        setEsPantallaCompleta(false);
      } else if (esPantallaCompleta || mostrarVisor) {
        if (e.key === 'r' || e.key === 'R') {
          e.preventDefault();
          handleRotate();
        } else if (e.key === '+' || e.key === '=') {
          e.preventDefault();
          handleZoomIn();
        } else if (e.key === '-' || e.key === '_') {
          e.preventDefault();
          handleZoomOut();
        } else if (e.key === '0') {
          e.preventDefault();
          handleResetView();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    if (esPantallaCompleta) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [esPantallaCompleta, mostrarVisor]);

  const handleVincularArchivoLocal = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0 && capturaDetalle) {
      const file = e.target.files[0];
      const url = URL.createObjectURL(file);
      const isImg = file.type.startsWith('image/') || /\.(jpg|jpeg|png|webp)$/i.test(file.name);
      const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
      const cat: 'image' | 'pdf' | 'xml' = isImg ? 'image' : isPdf ? 'pdf' : 'xml';
      setArchivosCache((prev) => ({
        ...prev,
        [String(capturaDetalle.id)]: { url, tipo: cat, nombre: file.name },
        [`hash_${capturaDetalle.hash_sha256}`]: { url, tipo: cat, nombre: file.name },
      }));
      setMostrarVisor(true);
    }
  };

  // Guardar corrección de campo
  const handleGuardarCorreccion = async (campoId: number) => {
    if (!selectedCapturaId) return;
    try {
      const updated = await corregirCampoCaptura(selectedCapturaId, campoId, tempValorCorregido);
      if (capturaDetalle && capturaDetalle.campos) {
        setCapturaDetalle({
          ...capturaDetalle,
          campos: capturaDetalle.campos.map((c) => (c.id === campoId ? updated : c)),
        });
      }
      setEditingCampoId(null);
      setSuccessMsg(`Campo ${updated.nombre_campo} corregido con éxito.`);
    } catch (err) {
      setErrorMsg(mensajesDeErrorApi(err, 'Error al corregir campo.').join(' '));
    }
  };

  // Generar borrador desde captura
  const handleGenerarBorrador = async () => {
    if (!selectedCapturaId) return;
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      setLoading(true);
      const almId = selectedAlmacenId ? Number(selectedAlmacenId) : undefined;
      const res = await generarBorradorDesdeCaptura(selectedCapturaId, almId);
      // El borrador puede haber creado el proveedor del XML (QA-002).
      await recargarTerceros();
      setBorradorResultado(res);
      setSuccessMsg(res.mensaje);
      await cargarCapturas();
      const detalleActualizado = await obtenerCapturaDetalle(selectedCapturaId);
      setCapturaDetalle(detalleActualizado);
    } catch (err) {
      setErrorMsg(mensajesDeErrorApi(err, 'Error al generar borrador.').join(' '));
    } finally {
      setLoading(false);
    }
  };

  // Cargar unidades del producto cuando se selecciona en el modal de equivalencia
  useEffect(() => {
    const cargarUnidades = async () => {
      if (!formProductoId) {
        setProductoUnidades([]);
        setFormProductoUnidadId('');
        return;
      }
      try {
        const unds = await getProductoUnidades(Number(formProductoId));
        setProductoUnidades(unds);
        if (unds.length > 0) {
          const base = unds.find((u) => u.es_base) || unds[0];
          setFormProductoUnidadId(String(base.id));
        }
      } catch (err) {
        console.error('Error al cargar unidades del producto:', err);
      }
    };
    diferirCarga(cargarUnidades);
  }, [formProductoId]);

  // Guardar nueva equivalencia
  const handleCrearEquivalencia = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formTerceroId || !formProductoUnidadId) {
      setErrorMsg('Debe seleccionar el proveedor y la unidad del producto.');
      return;
    }
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      setLoading(true);
      await crearEquivalencia({
        // QA2-001: 'captura' = proveedor del comprobante aún no registrado (se crea al guardar).
        tercero: formTerceroId === PROVEEDOR_DE_CAPTURA ? null : Number(formTerceroId),
        captura: capturaEquivId,
        codigo_externo: formCodigoExt.trim() || null,
        descripcion_externa: formDescExt.trim() || null,
        unidad_externa_codigo: formUnidadExt || null,
        producto_unidad: Number(formProductoUnidadId),
        factor_conversion: formFactor,
        activa: true,
      });
      setSuccessMsg('Equivalencia confirmada y registrada exitosamente.');
      setShowEquivModal(false);
      setFormCodigoExt('');
      setFormDescExt('');
      setFormFactor('1.00000000');
      await cargarEquivalencias();
      await recargarTerceros();
      if (capturaEquivId) {
        // Volver a la captura: sus líneas se recalculan con la nueva equivalencia.
        if (capturaEquivId === selectedCapturaId) setCapturaDetalle(await obtenerCapturaDetalle(capturaEquivId));
        setActiveTab('capturas');
        setCapturaEquivId(null);
      }
    } catch (err) {
      setErrorMsg(mensajesDeErrorApi(err, 'Error al registrar equivalencia.').join(' '));
    } finally {
      setLoading(false);
    }
  };

  // Alternar estado activo de equivalencia
  const handleToggleEquivalencia = async (equiv: ProductoEquivalencia) => {
    try {
      await actualizarEquivalencia(equiv.id, { activa: !equiv.activa });
      await cargarEquivalencias();
    } catch (err) {
      setErrorMsg(mensajesDeErrorApi(err, 'Error al actualizar equivalencia.').join(' '));
    }
  };

  // Probar sugerencia
  const handleProbarSugerencia = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!testTerceroId) {
      setErrorMsg('Seleccione un proveedor para probar la sugerencia.');
      return;
    }
    try {
      setLoading(true);
      const res = await sugerirEquivalencia(Number(testTerceroId), testCodigoExt.trim(), testDescExt.trim());
      setSugerenciaResultado(res);
    } catch (err) {
      setErrorMsg(mensajeDeError(err, ['detail'], 'Error al probar sugerencia.'));
    } finally {
      setLoading(false);
    }
  };

  // Campos separados de la captura
  const camposCabecera = useMemo(() => {
    if (!capturaDetalle?.campos) return [];
    return capturaDetalle.campos.filter((c) => c.seccion === 'CABECERA' && c.nombre_campo !== 'alerta_validacion');
  }, [capturaDetalle]);

  // Alertas de validación contable registradas en la captura
  const alertasValidacion = useMemo(() => {
    if (!capturaDetalle?.campos) return [];
    return capturaDetalle.campos.filter((c) => c.nombre_campo === 'alerta_validacion');
  }, [capturaDetalle]);

  // Proveedor (emisor) de la captura, para precargar la homologación de una línea.
  const rucEmisorCaptura = useMemo(() => {
    const campo = camposCabecera.find((c) => c.nombre_campo === 'ruc_emisor');
    return (campo?.valor_corregido || campo?.valor_extraido || '').replace(/\D/g, '');
  }, [camposCabecera]);

  /**
   * QA-002: la lista de proveedores se cargaba una sola vez al abrir la pantalla. El proveedor
   * que se crea al generar el borrador del primer XML no aparecía, y la equivalencia se
   * registraba con otro proveedor: el segundo XML no la reutilizaba. Ahora se recarga y se
   * preselecciona el proveedor por el RUC del comprobante.
   */
  const recargarTerceros = useCallback(async () => {
    try {
      const lista = await getTerceros({ tipo: 'proveedor' });
      setTerceros(lista);
      return lista;
    } catch {
      return terceros;
    }
  }, [terceros]);

  const proveedorDeCaptura = async (): Promise<string> => {
    const proveedor = capturaDetalle?.homologacion?.proveedor;
    if (proveedor?.tercero_id) {
      if (!terceros.some((t) => t.id === proveedor.tercero_id)) await recargarTerceros();
      return String(proveedor.tercero_id);
    }
    // Proveedor nuevo (aún no registrado): se registra al guardar la equivalencia.
    if (proveedor?.documento) return PROVEEDOR_DE_CAPTURA;
    if (!rucEmisorCaptura) return '';
    let lista = terceros;
    if (!lista.some((t) => t.numero_documento === rucEmisorCaptura)) lista = await recargarTerceros();
    const t = lista.find((x) => x.numero_documento === rucEmisorCaptura);
    return t ? String(t.id) : '';
  };


  const camposDetalle = useMemo(() => {
    if (!capturaDetalle?.campos) return [];
    return capturaDetalle.campos.filter((c) => c.seccion === 'DETALLE');
  }, [capturaDetalle]);

  // Agrupación de líneas de detalle
  const lineasAgrupadas = useMemo(() => {
    const mapa: Record<number, Record<string, CapturaCampo>> = {};
    camposDetalle.forEach((c) => {
      const num = c.numero_linea || 1;
      if (!mapa[num]) mapa[num] = {};
      mapa[num][c.nombre_campo] = c;
    });
    return Object.entries(mapa).sort(([a], [b]) => Number(a) - Number(b));
  }, [camposDetalle]);

  // Filtrado de equivalencias en frontend
  const equivalenciasFiltradas = useMemo(() => {
    return equivalencias.filter((eq) => {
      if (!busquedaEquiv) return true;
      const b = busquedaEquiv.toLowerCase();
      const codExt = eq.codigo_externo?.toLowerCase() || '';
      const descExt = eq.descripcion_externa?.toLowerCase() || '';
      const prodCod = eq.producto_info?.producto_codigo.toLowerCase() || '';
      const prodDesc = eq.producto_info?.producto_descripcion.toLowerCase() || '';
      return codExt.includes(b) || descExt.includes(b) || prodCod.includes(b) || prodDesc.includes(b);
    });
  }, [equivalencias, busquedaEquiv]);

  // Helper para badge de confianza
  const renderConfianzaBadge = (confStr: string | null) => {
    if (confStr === null) return <Badge variant="neutral" size="xs">N/A</Badge>;
    const num = Number(confStr);
    let variant: 'success' | 'warning' | 'destructive' = 'success';
    if (num < 70) {
      variant = 'destructive';
    } else if (num < 90) {
      variant = 'warning';
    }
    return (
      <Badge variant={variant} size="xs" className="font-mono tabular-nums">
        {num.toFixed(1)}%
      </Badge>
    );
  };

  return (
    <div className="space-y-6">
      {/* 1. Encabezado principal */}
      <PageHeader
        title="Captura XML / OCR y Homologación de Productos"
        description={`Importación automatizada de comprobantes electrónicos (UBL 2.1) y catálogo de equivalencias proveedor ↔ almacén · ${
          empresaActiva?.razon_social || 'Empresa activa'
        }`}
        icon={ScanLine}
        badge={
          <div className="flex items-center gap-1.5 flex-wrap">
            <Badge variant="info">Fase 11 & 12 · Bloque 6</Badge>
            <Badge variant="neutral" className="font-mono text-xs">UBL 2.1</Badge>
            <Badge variant="neutral" className="text-xs">Sin envío a SUNAT</Badge>
          </div>
        }
      />

      {/* 2. Alertas */}
      {errorMsg && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800 flex items-start gap-2.5">
          <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Error en la operación</p>
            <p className="mt-0.5">{errorMsg}</p>
          </div>
        </div>
      )}

      {successMsg && (
        <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-xs text-emerald-800 flex items-start gap-2.5">
          <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Operación exitosa</p>
            <p className="mt-0.5">{successMsg}</p>
          </div>
        </div>
      )}

      {/* 3. Selector de Pestañas */}
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'capturas' | 'homologaciones')}>
        <TabsList className="h-auto w-full lg:w-auto">
          <TabsTrigger value="capturas" className="gap-2 flex-1 lg:flex-none" title="Bandeja de Captura XML / OCR" icon={<Upload className="h-4 w-4" />}>
            <span className="lg:hidden">Captura</span>
            <span className="hidden lg:inline">Bandeja de Captura XML / OCR</span>
          </TabsTrigger>
          <TabsTrigger value="homologaciones" className="gap-2 flex-1 lg:flex-none" title="Catálogo de Homologación" icon={<RotateCcw className="h-4 w-4" />}>
            <span className="lg:hidden">Homologación ({equivalencias.length})</span>
            <span className="hidden lg:inline">Catálogo de Homologación ({equivalencias.length})</span>
          </TabsTrigger>
        </TabsList>

        {/* ==================================================================== */}
        {/* PESTAÑA 1: BANDEJA DE CAPTURA XML / PDF / OCR                        */}
        {/* ==================================================================== */}
        <TabsContent value="capturas" className="space-y-5 pt-2">
          {/* Tarjeta de Carga de Comprobantes (Colapsable) */}
          {!mostrarSubida && capturas.length > 0 ? (
            <div className="rounded-xl border border-slate-200 bg-white p-3.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs">
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 shrink-0">
                  <Upload className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-xs font-bold text-slate-900 flex items-center gap-2">
                    Cargar Nuevo Comprobante
                    <Badge variant="neutral" size="xs">XML · PDF · Imagen</Badge>
                  </h3>
                  <p className="text-[11px] text-slate-500 truncate">
                    Procesamiento asistido por IA o XML oficial UBL 2.1 sin registrar hasta su confirmación.
                  </p>
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setMostrarSubida(true)}
                className="shrink-0 text-xs"
              >
                <Plus className="h-3.5 w-3.5 mr-1 text-indigo-600" />
                Subir Nuevo Comprobante
                <ChevronDown className="h-3.5 w-3.5 ml-1 text-slate-400" />
              </Button>
            </div>
          ) : (
            <Card className="border-indigo-100 shadow-xs">
              <CardHeader className="pb-3 border-b border-slate-100">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                    <FileCode className="h-4 w-4 text-indigo-600" />
                    Subir Comprobante para Captura Automática
                  </CardTitle>
                  {capturas.length > 0 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() => setMostrarSubida(false)}
                      className="text-slate-500 hover:text-slate-700"
                    >
                      <ChevronUp className="h-3.5 w-3.5 mr-1" />
                      Ocultar formulario
                    </Button>
                  )}
                </div>
                <CardDescription className="text-xs">
                  Cargue un comprobante en XML UBL 2.1, PDF, imagen o escaneado. Los datos extraídos se muestran para revisarlos y corregirlos:
                  nada se registra hasta que usted genere el borrador y lo confirme en Comprobantes.
                </CardDescription>
                <ol aria-label="Pasos de la captura" className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px]">
                  {PASOS_CAPTURA.map((paso, i) => {
                    const actual = pasoActualCaptura(capturaDetalle);
                    return (
                      <li key={paso} className="flex items-center gap-1.5">
                        <span
                          aria-current={i === actual ? 'step' : undefined}
                          className={`rounded-full px-2 py-0.5 font-medium ${
                            i === actual
                              ? 'bg-indigo-600 text-white'
                              : i < actual
                                ? 'bg-indigo-50 text-indigo-700'
                                : 'bg-slate-100 text-slate-500'
                          }`}
                        >
                          {i + 1}. {paso}
                        </span>
                        {i < PASOS_CAPTURA.length - 1 && <span className="text-slate-300" aria-hidden="true">→</span>}
                      </li>
                    );
                  })}
                </ol>
              </CardHeader>
              <CardContent className="pt-4">
                <form onSubmit={handleSubirCaptura} className="space-y-4">
                  <div className="space-y-1.5">
                    <Label>Tipo de Captura</Label>
                    <div role="radiogroup" aria-label="Tipo de captura" className="grid grid-cols-2 sm:grid-cols-4 rounded-md border border-slate-200 p-0.5 bg-slate-50 gap-1 max-w-xl">
                      {TIPOS_CAPTURA.map((t) => (
                        <button
                          type="button"
                          role="radio"
                          aria-checked={uploadTipo === t}
                          key={t}
                          onClick={() => {
                            setUploadTipo(t);
                            setErrorMsg(uploadFile ? validarArchivoCaptura(uploadFile, t) : null);
                          }}
                          className={`py-1.5 text-[11px] font-semibold rounded transition-colors ${
                            uploadTipo === t
                              ? 'bg-white text-indigo-600 shadow-xs'
                              : 'text-slate-600 hover:text-slate-900'
                          }`}
                        >
                          {DESCRIPCION_TIPO_CAPTURA[t].titulo}
                        </button>
                      ))}
                    </div>
                    <p className="text-[11px] text-slate-600" data-testid="captura-ayuda-tipo">
                      {DESCRIPCION_TIPO_CAPTURA[uploadTipo].texto}
                    </p>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
                    <div className="sm:col-span-2 space-y-1.5 min-w-0">
                      <Label htmlFor="captura-file-input">Archivo del Comprobante</Label>
                      <Input
                        id="captura-file-input"
                        type="file"
                        accept={acceptCaptura(uploadTipo)}
                        onChange={handleFileChange}
                        aria-describedby="captura-formatos"
                        className="cursor-pointer"
                      />
                      <span id="captura-formatos" className="text-[11px] text-slate-500 block">
                        Formatos permitidos: {formatosVisibles(uploadTipo)}
                      </span>
                      {uploadFile && (
                        <div className="mt-2 p-2.5 rounded-lg border border-slate-200 bg-slate-50 flex items-center justify-between gap-3">
                          <div className="flex items-center gap-3 min-w-0">
                            {preUploadFileType === 'image' && preUploadPreviewUrl ? (
                              <img
                                src={preUploadPreviewUrl}
                                alt="Miniatura comprobante"
                                className="h-20 w-20 object-contain rounded border border-slate-300 bg-white shrink-0 shadow-xs"
                              />
                            ) : preUploadFileType === 'pdf' ? (
                              <div className="h-16 w-16 rounded border border-rose-200 bg-rose-50 flex flex-col items-center justify-center shrink-0 text-rose-600">
                                <FileText className="h-6 w-6" />
                                <span className="text-[9px] font-bold mt-0.5">PDF</span>
                              </div>
                            ) : (
                              <div className="h-16 w-16 rounded border border-indigo-200 bg-indigo-50 flex flex-col items-center justify-center shrink-0 text-indigo-600">
                                <FileCode className="h-6 w-6" />
                                <span className="text-[9px] font-bold mt-0.5">XML</span>
                              </div>
                            )}
                            <div className="min-w-0">
                              <span className="text-[11px] text-indigo-600 font-medium block break-all">
                                Seleccionado: <strong>{uploadFile.name}</strong> ({(uploadFile.size / 1024).toFixed(1)} KB)
                              </span>
                              <span className="text-[10px] text-slate-500 block mt-0.5">
                                Listo para procesar y extraer con IA
                              </span>
                            </div>
                          </div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="xs"
                            onClick={handleLimpiarArchivo}
                            className="text-slate-500 hover:text-rose-600 shrink-0"
                            title="Quitar archivo"
                          >
                            <X className="h-4 w-4 mr-1" />
                            Quitar
                          </Button>
                        </div>
                      )}
                    </div>

                    <div>
                      <Button
                        type="submit"
                        variant="primary"
                        disabled={loading || !uploadFile}
                        className="w-full"
                      >
                        {loading ? (
                          <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                        ) : (
                          <Upload className="h-4 w-4 mr-1.5" />
                        )}
                        {loading ? 'Procesando...' : 'Subir y Extraer Datos'}
                      </Button>
                    </div>
                  </div>

                  {uploadTipo !== 'XML' && (
                    <div className="space-y-1.5 pt-2 border-t border-slate-100">
                      <Label htmlFor="texto-ocr-input">
                        Texto del comprobante (OCR)
                      </Label>
                      <p className="text-[11px] text-indigo-900 bg-indigo-50 border border-indigo-200 rounded px-2.5 py-1.5">
                        El sistema procesa imágenes y PDFs escaneados automáticamente mediante IA multimodal (Gemini).
                        Si desea ingresar o complementar el texto manualmente, puede pegarlo en este campo opcional.
                        Revise y confirme siempre los campos extraídos antes de generar el comprobante en borrador.
                      </p>
                      <textarea
                        id="texto-ocr-input"
                        rows={3}
                        value={textoOcr}
                        onChange={(e) => setTextoOcr(e.target.value)}
                        placeholder="Ej.: FACTURA ELECTRÓNICA F001-123 · RUC 20555000111 · Fecha 18/02/2026 · Total 156.35"
                        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 resize-y"
                      />
                    </div>
                  )}
                </form>
              </CardContent>
            </Card>
          )}

          {/* Master-Detail Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
            {/* Panel Izquierdo: Bandeja de Capturas (lg:col-span-4 xl:col-span-3) */}
            <Card className="lg:col-span-4 xl:col-span-3 overflow-hidden shadow-xs">
              <CardHeader className="py-3 px-3.5 border-b border-slate-200 bg-slate-50/50 flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                    Bandeja de Comprobantes
                  </CardTitle>
                  <CardDescription className="text-[11px] text-slate-500">
                    {capturasFiltradas.length} de {capturas.length} comprobante(s)
                  </CardDescription>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  onClick={cargarCapturas}
                  disabled={loading}
                  title="Actualizar bandeja de comprobantes"
                >
                  <RotateCcw className="h-3 w-3 mr-1" />
                  Actualizar
                </Button>
              </CardHeader>

              {/* Filtros rápidos y buscador en la bandeja */}
              <div className="p-2.5 border-b border-slate-100 bg-white space-y-2">
                <Input
                  type="text"
                  placeholder="Buscar archivo, serie o hash..."
                  value={busquedaCapturas}
                  onChange={(e) => setBusquedaCapturas(e.target.value)}
                  leftIcon={<Search className="h-3.5 w-3.5" />}
                  className="h-7 text-xs"
                />
                <div className="grid grid-cols-3 gap-1 rounded bg-slate-100 p-0.5 text-[10px] font-semibold text-slate-600">
                  <button
                    type="button"
                    onClick={() => setFiltroEstadoCaptura('todos')}
                    className={`py-1 rounded text-center transition-colors ${
                      filtroEstadoCaptura === 'todos' ? 'bg-white text-indigo-600 shadow-xs font-bold' : 'hover:text-slate-900'
                    }`}
                  >
                    Todos
                  </button>
                  <button
                    type="button"
                    onClick={() => setFiltroEstadoCaptura('pendientes')}
                    className={`py-1 rounded text-center transition-colors ${
                      filtroEstadoCaptura === 'pendientes' ? 'bg-white text-indigo-600 shadow-xs font-bold' : 'hover:text-slate-900'
                    }`}
                  >
                    Pendientes
                  </button>
                  <button
                    type="button"
                    onClick={() => setFiltroEstadoCaptura('borradores')}
                    className={`py-1 rounded text-center transition-colors ${
                      filtroEstadoCaptura === 'borradores' ? 'bg-white text-indigo-600 shadow-xs font-bold' : 'hover:text-slate-900'
                    }`}
                  >
                    Borradores
                  </button>
                </div>
              </div>

              <CardContent className="p-2.5">
                {capturas.length === 0 ? (
                  <div className="text-center py-10 px-2 space-y-2">
                    <FileText className="h-8 w-8 text-slate-300 mx-auto" />
                    <p className="text-xs text-slate-600 font-medium">No hay comprobantes cargados</p>
                    <p className="text-[11px] text-slate-400">Use el botón superior para subir su primer comprobante.</p>
                  </div>
                ) : capturasFiltradas.length === 0 ? (
                  <p className="text-xs text-slate-500 text-center py-8">
                    No se encontraron comprobantes con el filtro aplicado.
                  </p>
                ) : (
                  <div className="space-y-2 max-h-[660px] overflow-y-auto pr-1">
                    {capturasFiltradas.map((c) => {
                      const isSelected = c.id === selectedCapturaId;
                      const isDraftGenerated = c.estado_proceso === 'BORRADOR_GENERADO';
                      return (
                        <div
                          key={c.id}
                          onClick={() => setSelectedCapturaId(c.id)}
                          className={`p-3 rounded-lg border cursor-pointer transition-all ${
                            isSelected
                              ? 'border-indigo-600 bg-indigo-50/70 shadow-xs ring-1 ring-indigo-500/20'
                              : 'border-slate-200 bg-white hover:bg-slate-50'
                          }`}
                        >
                          <div className="flex items-center justify-between mb-1.5">
                            <Badge variant="neutral" size="xs">
                              {c.tipo}
                            </Badge>
                            <div className="flex items-center gap-1.5">
                              <Badge
                                variant={isDraftGenerated ? 'success' : 'warning'}
                                size="xs"
                                dot
                              >
                                {c.estado_proceso}
                              </Badge>
                              {!isDraftGenerated && c.documento_id === null && (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleDescartarCaptura(c.id);
                                  }}
                                  className="text-slate-400 hover:text-rose-600 p-0.5 rounded transition-colors"
                                  title="Descartar captura"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              )}
                            </div>
                          </div>
                          <p className="text-xs font-semibold text-slate-900 truncate" title={c.ruta_archivo}>
                            {c.ruta_archivo.split('/').pop()}
                          </p>
                          <p className="text-[11px] font-mono text-slate-500 mt-0.5 truncate" title={c.hash_sha256}>
                            SHA: {c.hash_sha256.slice(0, 14)}…
                          </p>
                          <div className="flex items-center justify-between text-[10px] text-slate-400 mt-2 pt-1.5 border-t border-slate-100">
                            <span>{c.subido_por_username || 'Usuario'}</span>
                            <span className="font-mono tabular-nums">{new Date(c.creado_en).toLocaleDateString('es-PE')}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Panel Derecho: Workspace de Trabajo "Ojo contra Dato" (lg:col-span-8 xl:col-span-9) */}
            <div className="lg:col-span-8 xl:col-span-9 space-y-4 min-w-0">
              {!capturaDetalle ? (
                <div className="rounded-xl border border-dashed border-slate-300 bg-white py-16 text-center text-xs text-slate-500">
                  <Search className="h-6 w-6 text-slate-400 mx-auto mb-2" />
                  Seleccione una captura de la bandeja izquierda para auditar sus datos o cargue un nuevo comprobante.
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Barra de Acciones de la Captura */}
                  <Card className="shadow-xs">
                    <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-bold text-slate-900">
                            Captura #{capturaDetalle.id} [{capturaDetalle.tipo}]
                          </span>
                          {capturaDetalle.documento_serie_numero ? (
                            <Badge variant="success" size="xs" dot>
                              Comprobante: {capturaDetalle.documento_serie_numero}
                            </Badge>
                          ) : (
                            <Badge variant="warning" size="xs" dot>
                              Pendiente de conversión a borrador
                            </Badge>
                          )}
                        </div>
                        <p className="text-[11px] font-mono text-slate-500 mt-1 select-all break-all">
                          Hash SHA-256: {capturaDetalle.hash_sha256}
                        </p>
                      </div>

                      <div className="flex items-center gap-2.5 flex-wrap">
                        <div>
                          <Button
                            type="button"
                            variant={mostrarVisor ? 'primary' : 'outline'}
                            size="sm"
                            onClick={() => setMostrarVisor(!mostrarVisor)}
                            title={mostrarVisor ? 'Ocultar visor del comprobante' : 'Ver documento original al lado de los datos'}
                          >
                            {mostrarVisor ? <EyeOff className="h-4 w-4 mr-1.5" /> : <Eye className="h-4 w-4 mr-1.5" />}
                            {mostrarVisor ? 'Ocultar Visor' : 'Ver Comprobante'}
                          </Button>
                        </div>

                        <div className="space-y-1">
                          <Label className="text-[11px]">Almacén Destino:</Label>
                          <Select
                            value={selectedAlmacenId}
                            onChange={(e) => setSelectedAlmacenId(e.target.value)}
                            disabled={Boolean(capturaDetalle.documento_id)}
                            className="h-8 text-xs min-w-[150px]"
                          >
                            {almacenes.map((a) => (
                              <option key={a.id} value={a.id}>
                                {a.codigo} - {a.nombre}
                              </option>
                            ))}
                          </Select>
                        </div>

                        <div className="pt-4 sm:pt-0">
                          <Button
                            type="button"
                            variant="primary"
                            size="sm"
                            onClick={handleGenerarBorrador}
                            disabled={loading || Boolean(capturaDetalle.documento_id)}
                          >
                            <FileSpreadsheet className="h-4 w-4 mr-1.5" />
                            {capturaDetalle.documento_id
                              ? 'Comprobante Ya Generado'
                              : 'Convertir a Comprobante en Borrador'}
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Feedback de Borrador Generado con Incidencias */}
                  {borradorResultado && (
                    <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-xs text-emerald-800 space-y-2 shadow-xs">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
                        <div>
                          <strong>{borradorResultado.mensaje}</strong> (Doc #{borradorResultado.documento_id} · {borradorResultado.serie_numero})
                          <p className="mt-0.5">
                            Quedó en BORRADOR: revíselo y confírmelo en <strong>Comprobantes</strong>. Hasta entonces no mueve el Kardex.
                          </p>
                        </div>
                      </div>
                      {borradorResultado.lineas_sin_homologar > 0 && (
                        <div className="rounded border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-800 flex items-start gap-2">
                          <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
                          <div>
                            Se generaron <strong>{borradorResultado.lineas_sin_homologar} incidencia(s) de tipo PRODUCTO_SIN_HOMOLOGAR</strong>.
                            Debe registrar la homologación en la Pestaña 2 para que los productos queden vinculados antes de confirmar el documento.
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Workspace Ojo contra Dato: 2 columnas paralelas en pantallas xl cuando el visor está visible */}
                  <div className={`grid grid-cols-1 ${mostrarVisor ? 'xl:grid-cols-12' : 'grid-cols-1'} gap-5 items-start`}>
                    {/* Sub-panel Izquierdo: Visor Sticky de Comprobante Original (5 cols) */}
                    {mostrarVisor && (
                      <div className="xl:col-span-5 xl:sticky xl:top-4 space-y-3">
                        <Card className="border-indigo-100 shadow-xs overflow-hidden h-auto xl:max-h-[calc(100vh-140px)] flex flex-col">
                          {/* Fila 1: Encabezado limpio y espacioso (sin colisiones con los controles) */}
                          <CardHeader className="py-2.5 px-3 bg-slate-50 border-b border-slate-200 flex flex-row items-center justify-between shrink-0 gap-2">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="p-1.5 rounded-md bg-indigo-100 text-indigo-700 shrink-0">
                                {previewActiva?.tipo === 'image' ? (
                                  <ImageIcon className="h-3.5 w-3.5" />
                                ) : previewActiva?.tipo === 'pdf' ? (
                                  <FileText className="h-3.5 w-3.5" />
                                ) : (
                                  <Eye className="h-3.5 w-3.5" />
                                )}
                              </span>
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <CardTitle className="text-[11px] font-bold text-slate-800 uppercase tracking-wider truncate">
                                    Visor Original
                                  </CardTitle>
                                  {previewActiva && (
                                    <Badge variant="neutral" size="xs" className="shrink-0 text-[9px] px-1.5 py-0 font-semibold uppercase">
                                      {previewActiva.tipo}
                                    </Badge>
                                  )}
                                </div>
                                <p
                                  className="text-[10px] text-slate-500 truncate"
                                  title={previewActiva?.nombre || capturaDetalle.ruta_archivo}
                                >
                                  {previewActiva?.nombre || capturaDetalle.ruta_archivo.split('/').pop()}
                                </p>
                              </div>
                            </div>

                            {/* Botón de pantalla completa en el extremo derecho */}
                            {previewActiva && (
                              <div className="flex items-center gap-1 shrink-0">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="xs"
                                  onClick={() => setEsPantallaCompleta(true)}
                                  title="Ver comprobante en pantalla completa (Esc para salir)"
                                  className="h-6 px-2 text-[10px] font-semibold text-indigo-700 border-indigo-200 bg-indigo-50/50 hover:bg-indigo-100/70 hover:text-indigo-900 transition-colors flex items-center gap-1 cursor-pointer"
                                >
                                  <Maximize2 className="h-3 w-3" />
                                  <span className="hidden sm:inline">Ampliar</span>
                                </Button>
                              </div>
                            )}
                          </CardHeader>

                          {/* Fila 2: Barra de herramientas dedicada para el visor en línea (evita superposiciones) */}
                          {previewActiva && previewActiva.tipo === 'image' && (
                            <div className="px-2.5 py-1.5 bg-slate-50/70 border-b border-slate-200/80 flex items-center justify-between gap-1.5 shrink-0">
                              {/* Selector Página / Ancho */}
                              <div className="flex items-center rounded border border-slate-200 bg-white p-0.5 shadow-2xs">
                                <button
                                  type="button"
                                  onClick={() => setModoAjuste('pagina')}
                                  className={`px-1.5 py-0.5 text-[10px] font-medium rounded transition-colors cursor-pointer ${
                                    modoAjuste === 'pagina'
                                      ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-2xs'
                                      : 'text-slate-600 hover:text-slate-900'
                                  }`}
                                  title="Página Completa: muestra 100% del documento sin cortes"
                                >
                                  Página
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setModoAjuste('ancho')}
                                  className={`px-1.5 py-0.5 text-[10px] font-medium rounded transition-colors cursor-pointer ${
                                    modoAjuste === 'ancho'
                                      ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-2xs'
                                      : 'text-slate-600 hover:text-slate-900'
                                  }`}
                                  title="Ajustar Ancho: expande la imagen al ancho para leer el texto"
                                >
                                  Ancho
                                </button>
                              </div>

                              {/* Controles de Zoom, Rotación y Reset */}
                              <div className="flex items-center gap-0.5">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="xs"
                                  onClick={handleZoomOut}
                                  disabled={zoomPct <= 50}
                                  title="Alejar (-25%)"
                                  className="h-6 w-6 p-0"
                                >
                                  <ZoomOut className="h-3 w-3" />
                                </Button>
                                <span className="text-[10px] font-mono font-semibold text-slate-700 w-7 text-center select-none">
                                  {zoomPct}%
                                </span>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="xs"
                                  onClick={handleZoomIn}
                                  disabled={zoomPct >= 250}
                                  title="Acercar (+25%)"
                                  className="h-6 w-6 p-0"
                                >
                                  <ZoomIn className="h-3 w-3" />
                                </Button>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="xs"
                                  onClick={handleRotate}
                                  title="Rotar 90°"
                                  className="h-6 w-6 p-0 ml-0.5"
                                >
                                  <RotateCw className="h-3 w-3" />
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="xs"
                                  onClick={handleResetView}
                                  className="text-[10px] h-6 px-1 text-slate-500 hover:text-slate-800"
                                  title="Restablecer vista"
                                >
                                  Reset
                                </Button>
                              </div>
                            </div>
                          )}

                          <CardContent className="p-2.5 flex-1 min-h-0 overflow-hidden flex flex-col">
                            {previewActiva ? (
                              previewActiva.tipo === 'image' ? (
                                <>
                                  <div className="overflow-auto rounded-lg border border-slate-300/80 bg-slate-200/75 p-3 flex flex-col items-center justify-start flex-1 min-h-[360px] xl:max-h-[calc(100vh-250px)] shadow-inner">
                                    <div
                                      className="transition-transform duration-150 inline-block my-auto"
                                      style={{
                                        transform: `rotate(${rotacionDeg}deg)`,
                                        transformOrigin: 'center center',
                                      }}
                                    >
                                      <img
                                        src={previewActiva.url}
                                        alt="Comprobante original"
                                        className="select-none shadow-xl rounded-sm ring-1 ring-slate-900/15 bg-white block"
                                        style={{
                                          width: modoAjuste === 'ancho' ? '100%' : modoAjuste === 'pagina' ? 'auto' : `${zoomPct}%`,
                                          maxHeight: modoAjuste === 'pagina' ? 'calc(100vh - 280px)' : 'none',
                                          maxWidth: modoAjuste === 'pagina' ? '100%' : modoAjuste === 'ancho' ? '100%' : 'none',
                                          height: 'auto',
                                        }}
                                      />
                                    </div>
                                  </div>
                                  {/* Barra de atajos de teclado sutil en el pie del visor */}
                                  <div className="mt-2 pt-1 border-t border-slate-100 flex items-center justify-center gap-2 text-[10px] text-slate-500 font-medium select-none flex-wrap">
                                    <span className="flex items-center gap-1">
                                      <kbd className="px-1 py-0.5 rounded bg-slate-100 border border-slate-300 text-[9px] font-mono shadow-2xs font-semibold text-slate-700">+/-</kbd>
                                      <span>Zoom</span>
                                    </span>
                                    <span className="text-slate-300">·</span>
                                    <span className="flex items-center gap-1">
                                      <kbd className="px-1 py-0.5 rounded bg-slate-100 border border-slate-300 text-[9px] font-mono shadow-2xs font-semibold text-slate-700">R</kbd>
                                      <span>Rotar 90°</span>
                                    </span>
                                    <span className="text-slate-300">·</span>
                                    <span className="flex items-center gap-1">
                                      <kbd className="px-1 py-0.5 rounded bg-slate-100 border border-slate-300 text-[9px] font-mono shadow-2xs font-semibold text-slate-700">0</kbd>
                                      <span>Reset</span>
                                    </span>
                                    <span className="text-slate-300">·</span>
                                    <span className="flex items-center gap-1">
                                      <kbd className="px-1 py-0.5 rounded bg-slate-100 border border-slate-300 text-[9px] font-mono shadow-2xs font-semibold text-slate-700">Esc</kbd>
                                      <span>Salir</span>
                                    </span>
                                  </div>
                                </>
                              ) : previewActiva.tipo === 'pdf' ? (
                                <div className="h-[520px] xl:h-[calc(100vh-230px)]">
                                  <iframe
                                    src={previewActiva.url}
                                    title="Vista previa PDF"
                                    className="w-full h-full rounded border border-slate-200 bg-white"
                                  />
                                </div>
                              ) : (
                                <div className="rounded border border-indigo-200 bg-indigo-50/60 p-4 text-xs text-indigo-900 flex items-center gap-3">
                                  <FileCode className="h-8 w-8 text-indigo-600 shrink-0" />
                                  <div>
                                    <p className="font-semibold">Archivo XML UBL 2.1 estructurado</p>
                                    <p className="text-[11px] text-indigo-700 mt-0.5">
                                      Los datos de este comprobante electrónico fueron leídos directamente desde sus etiquetas XML oficiales con 100% de confianza.
                                    </p>
                                  </div>
                                </div>
                              )
                            ) : (
                              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-xs text-slate-600 space-y-2">
                                <FileText className="h-7 w-7 text-slate-400 mx-auto" />
                                <p className="font-semibold text-slate-800">Vista previa no disponible en la sesión</p>
                                <p className="text-[11px] text-slate-500 max-w-xs mx-auto">
                                  Vincule el archivo original desde su equipo para renderizarlo aquí sin volver a subirlo al servidor.
                                </p>
                                <div className="pt-1">
                                  <label className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 cursor-pointer shadow-xs transition-colors">
                                    <Upload className="h-3.5 w-3.5 text-indigo-600" />
                                    Vincular archivo local
                                    <input
                                      type="file"
                                      accept=".pdf,.jpg,.jpeg,.png,.webp,.xml"
                                      onChange={handleVincularArchivoLocal}
                                      className="hidden"
                                    />
                                  </label>
                                </div>
                              </div>
                            )}
                          </CardContent>
                        </Card>

                        {/* Modal de Pantalla Completa montado mediante Portal en document.body (supera sidebar y topbar) */}
                        {esPantallaCompleta &&
                          createPortal(
                            <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-5 md:p-6 lg:p-8 animate-in fade-in duration-150">
                              {/* Telón oscuro desenfocado */}
                              <div
                                className="fixed inset-0 bg-slate-950/80 backdrop-blur-xs transition-opacity cursor-pointer"
                                onClick={() => setEsPantallaCompleta(false)}
                                aria-hidden="true"
                              />

                              {/* Ventana modal centrada de alta ergonomía visual */}
                              <div
                                className="relative w-full max-w-5xl xl:max-w-6xl h-full max-h-[90vh] bg-white rounded-xl shadow-2xl border border-slate-300 flex flex-col overflow-hidden z-10 animate-in zoom-in-95 duration-150"
                                role="dialog"
                                aria-modal="true"
                                aria-label="Comprobante original en pantalla completa"
                              >
                                {/* Encabezado espacioso en una sola fila */}
                                <div className="py-2.5 px-4 bg-slate-50 border-b border-slate-200 flex flex-row items-center justify-between shrink-0 gap-3">
                                  <div className="flex items-center gap-2 min-w-0">
                                    <span className="p-1.5 rounded-lg bg-indigo-100 text-indigo-700 shrink-0">
                                      {previewActiva?.tipo === 'image' ? (
                                        <ImageIcon className="h-4 w-4" />
                                      ) : previewActiva?.tipo === 'pdf' ? (
                                        <FileText className="h-4 w-4" />
                                      ) : (
                                        <Eye className="h-4 w-4" />
                                      )}
                                    </span>
                                    <div className="min-w-0">
                                      <div className="flex items-center gap-2">
                                        <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                                          Visor Original
                                        </h3>
                                        {previewActiva && (
                                          <Badge variant="neutral" size="xs" className="uppercase font-semibold">
                                            {previewActiva.tipo}
                                          </Badge>
                                        )}
                                      </div>
                                      <p
                                        className="text-[11px] text-slate-500 truncate max-w-xs sm:max-w-md"
                                        title={previewActiva?.nombre || capturaDetalle.ruta_archivo}
                                      >
                                        {previewActiva?.nombre || capturaDetalle.ruta_archivo.split('/').pop()}
                                      </p>
                                    </div>
                                  </div>

                                  <div className="flex items-center gap-2 shrink-0">
                                    {previewActiva?.tipo === 'image' && (
                                      <>
                                        <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5 shadow-2xs">
                                          <button
                                            type="button"
                                            onClick={() => setModoAjuste('pagina')}
                                            className={`px-2 py-1 text-xs font-medium rounded-md transition-colors cursor-pointer ${
                                              modoAjuste === 'pagina'
                                                ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-2xs'
                                                : 'text-slate-600 hover:text-slate-900'
                                            }`}
                                            title="Página Completa: muestra 100% del documento sin cortes"
                                          >
                                            Página
                                          </button>
                                          <button
                                            type="button"
                                            onClick={() => setModoAjuste('ancho')}
                                            className={`px-2 py-1 text-xs font-medium rounded-md transition-colors cursor-pointer ${
                                              modoAjuste === 'ancho'
                                                ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-2xs'
                                                : 'text-slate-600 hover:text-slate-900'
                                            }`}
                                            title="Ajustar Ancho: expande la imagen al ancho para leer el texto"
                                          >
                                            Ancho
                                          </button>
                                        </div>

                                        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-1 py-0.5 shadow-2xs">
                                          <Button
                                            type="button"
                                            variant="ghost"
                                            size="xs"
                                            onClick={handleZoomOut}
                                            disabled={zoomPct <= 50}
                                            title="Alejar (-25%)"
                                            className="h-6 w-6 p-0"
                                          >
                                            <ZoomOut className="h-3.5 w-3.5" />
                                          </Button>
                                          <span className="text-xs font-mono font-semibold text-slate-700 w-9 text-center select-none">
                                            {zoomPct}%
                                          </span>
                                          <Button
                                            type="button"
                                            variant="ghost"
                                            size="xs"
                                            onClick={handleZoomIn}
                                            disabled={zoomPct >= 250}
                                            title="Acercar (+25%)"
                                            className="h-6 w-6 p-0"
                                          >
                                            <ZoomIn className="h-3.5 w-3.5" />
                                          </Button>
                                        </div>

                                        <Button
                                          type="button"
                                          variant="outline"
                                          size="xs"
                                          onClick={handleRotate}
                                          title="Rotar 90°"
                                          className="h-7 px-2 text-xs flex items-center gap-1 cursor-pointer"
                                        >
                                          <RotateCw className="h-3.5 w-3.5" />
                                          <span className="hidden sm:inline">Rotar</span>
                                        </Button>

                                        <Button
                                          type="button"
                                          variant="ghost"
                                          size="xs"
                                          onClick={handleResetView}
                                          title="Restablecer vista"
                                          className="h-7 px-2 text-xs text-slate-500 hover:text-slate-800 cursor-pointer"
                                        >
                                          Reset
                                        </Button>
                                      </>
                                    )}

                                    <div className="h-4 w-px bg-slate-200 mx-0.5" />

                                    <Button
                                      type="button"
                                      variant="outline"
                                      size="xs"
                                      onClick={() => setEsPantallaCompleta(false)}
                                      title="Salir de pantalla completa (Esc)"
                                      className="h-7 px-2.5 text-xs font-medium text-slate-700 hover:bg-slate-100 flex items-center gap-1.5 cursor-pointer"
                                    >
                                      <Minimize2 className="h-3.5 w-3.5 text-slate-500" />
                                      <span>Cerrar</span>
                                    </Button>
                                  </div>
                                </div>

                                {/* Contenedor del documento en pantalla completa con fondo de mesa de trabajo de alto contraste */}
                                <div className="flex-1 min-h-0 overflow-auto p-6 bg-slate-200/75 flex flex-col items-center justify-start shadow-inner">
                                  {previewActiva?.tipo === 'image' ? (
                                    <div
                                      className="transition-transform duration-150 inline-block my-auto"
                                      style={{
                                        transform: `rotate(${rotacionDeg}deg)`,
                                        transformOrigin: 'center center',
                                      }}
                                    >
                                      <img
                                        src={previewActiva.url}
                                        alt="Comprobante original pantalla completa"
                                        className="select-none shadow-2xl rounded-sm ring-1 ring-slate-900/20 bg-white block"
                                        style={{
                                          width: modoAjuste === 'ancho' ? '100%' : modoAjuste === 'pagina' ? 'auto' : `${zoomPct}%`,
                                          maxHeight: modoAjuste === 'pagina' ? 'calc(90vh - 140px)' : 'none',
                                          maxWidth: modoAjuste === 'pagina' ? '100%' : modoAjuste === 'ancho' ? '100%' : 'none',
                                          height: 'auto',
                                        }}
                                      />
                                    </div>
                                  ) : previewActiva?.tipo === 'pdf' ? (
                                    <iframe
                                      src={previewActiva.url}
                                      title="Vista previa PDF completa"
                                      className="w-full h-full rounded border border-slate-200 bg-white"
                                    />
                                  ) : null}
                                </div>

                                {/* Pie de pantalla completa con atajos de teclado ergonómicos */}
                                {previewActiva?.tipo === 'image' && (
                                  <div className="py-2 px-4 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-500 shrink-0">
                                    <span className="text-[11px] text-slate-500 font-medium">
                                      Visualizando en alta resolución contra datos homologados
                                    </span>
                                    <div className="flex items-center gap-2.5 text-[10px] text-slate-500 font-medium select-none">
                                      <span className="flex items-center gap-1">
                                        <kbd className="px-1 py-0.5 rounded bg-white border border-slate-300 text-[9px] font-mono shadow-2xs font-semibold text-slate-700">+/-</kbd>
                                        <span>Zoom</span>
                                      </span>
                                      <span className="text-slate-300">·</span>
                                      <span className="flex items-center gap-1">
                                        <kbd className="px-1 py-0.5 rounded bg-white border border-slate-300 text-[9px] font-mono shadow-2xs font-semibold text-slate-700">R</kbd>
                                        <span>Rotar 90°</span>
                                      </span>
                                      <span className="text-slate-300">·</span>
                                      <span className="flex items-center gap-1">
                                        <kbd className="px-1 py-0.5 rounded bg-white border border-slate-300 text-[9px] font-mono shadow-2xs font-semibold text-slate-700">0</kbd>
                                        <span>Reset</span>
                                      </span>
                                      <span className="text-slate-300">·</span>
                                      <span className="flex items-center gap-1">
                                        <kbd className="px-1 py-0.5 rounded bg-white border border-slate-300 text-[9px] font-mono shadow-2xs font-semibold text-slate-700">Esc</kbd>
                                        <span>Cerrar</span>
                                      </span>
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>,
                            document.body
                          )}
                      </div>
                    )}

                    {/* Sub-panel Derecho: Datos Extraídos, Cabecera y Líneas (7 cols o ancho completo) */}
                    <div className={`${mostrarVisor ? 'xl:col-span-7' : 'col-span-1'} space-y-4 min-w-0`}>
                      {/* Alertas de Validación Contable / OCR */}
                      {alertasValidacion.length > 0 && (
                        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3.5 text-xs text-amber-900 space-y-1.5 shadow-xs">
                          <div className="flex items-center gap-2 font-bold text-amber-800">
                            <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
                            <span>Observaciones y Alertas de Validación Contable (OCR):</span>
                          </div>
                          <ul className="list-disc list-inside space-y-0.5 pl-1 text-[11px] text-amber-900">
                            {alertasValidacion.map((alerta) => (
                              <li key={alerta.id}>
                                {alerta.valor_corregido || alerta.valor_extraido}
                              </li>
                            ))}
                          </ul>
                          <p className="text-[11px] text-amber-700 font-medium pt-1 border-t border-amber-200/60">
                            Por favor revise y corrija los valores marcados en rojo antes de convertir este comprobante a borrador.
                          </p>
                        </div>
                      )}

                      {/* Sección 1: Campos de Cabecera */}
                      <Card className="shadow-xs">
                        <CardHeader className="py-2.5 px-3.5 border-b border-slate-100 flex flex-row items-center justify-between">
                          <CardTitle className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                            Datos Extraídos de Cabecera
                          </CardTitle>
                          <span className="text-[11px] text-slate-500 font-medium">
                            {camposCabecera.length} campos identificados
                          </span>
                        </CardHeader>
                        <CardContent className="p-3">
                          <div className={`grid grid-cols-1 sm:grid-cols-2 ${mostrarVisor ? 'lg:grid-cols-2 xl:grid-cols-2' : 'lg:grid-cols-3'} gap-2.5`}>
                            {camposCabecera.map((c) => {
                              const isEditing = editingCampoId === c.id;
                              return (
                                <div key={c.id} className="p-2.5 rounded-lg border border-slate-200 bg-slate-50/70 text-xs">
                                  <div className="flex items-center justify-between mb-1">
                                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                                      {c.nombre_campo.replace('_', ' ')}
                                    </span>
                                    {renderConfianzaBadge(c.confianza)}
                                  </div>

                                  {isEditing ? (
                                    <div className="flex items-center gap-1.5 mt-1">
                                      <Input
                                        type="text"
                                        value={tempValorCorregido}
                                        onChange={(e) => setTempValorCorregido(e.target.value)}
                                        autoFocus
                                        className="h-7 text-xs"
                                      />
                                      <Button
                                        type="button"
                                        size="xs"
                                        variant="success"
                                        onClick={() => handleGuardarCorreccion(c.id)}
                                      >
                                        <Save className="h-3 w-3" />
                                      </Button>
                                      <Button
                                        type="button"
                                        size="xs"
                                        variant="outline"
                                        onClick={() => setEditingCampoId(null)}
                                      >
                                        <X className="h-3 w-3" />
                                      </Button>
                                    </div>
                                  ) : (
                                    <div className="flex items-center justify-between gap-1 mt-1">
                                      <span className="font-semibold text-slate-900 truncate" title={c.valor_corregido || c.valor_extraido || ''}>
                                        {c.valor_corregido ? (
                                          <span className="text-amber-800">
                                            {c.valor_corregido}{' '}
                                            <span className="line-through text-slate-400 font-normal text-[10px]">
                                              ({c.valor_extraido})
                                            </span>
                                          </span>
                                        ) : (
                                          c.valor_extraido || '—'
                                        )}
                                      </span>
                                      {!capturaDetalle.documento_id && (
                                        <button
                                          type="button"
                                          onClick={() => {
                                            setEditingCampoId(c.id);
                                            setTempValorCorregido(c.valor_corregido || c.valor_extraido || '');
                                          }}
                                          className="text-slate-400 hover:text-slate-700 p-1"
                                          title="Corregir valor"
                                        >
                                          <Edit3 className="h-3 w-3" />
                                        </button>
                                      )}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </CardContent>
                      </Card>

                      {/* Sección 2: Líneas de Detalle Extraídas */}
                      <Card className="shadow-xs">
                        <CardHeader className="py-2.5 px-3.5 border-b border-slate-100 flex flex-row items-center justify-between">
                          <CardTitle className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                            Líneas de Detalle del Comprobante ({lineasAgrupadas.length})
                          </CardTitle>
                          {typeof capturaDetalle.homologacion?.pendientes_homologacion === 'number' && (
                            <Badge
                              variant={capturaDetalle.homologacion.pendientes_homologacion > 0 ? 'warning' : 'success'}
                              size="xs"
                              data-testid="pendientes-homologacion"
                            >
                              {capturaDetalle.homologacion.pendientes_homologacion > 0
                                ? `${capturaDetalle.homologacion.pendientes_homologacion} línea(s) pendiente(s)`
                                : 'Todas homologadas'}
                            </Badge>
                          )}
                        </CardHeader>
                        <CardContent className="p-0">
                          <div className="overflow-x-auto">
                            <table className="w-full text-xs text-left border-collapse">
                              <thead>
                                <tr className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-600 border-b border-slate-200">
                                  <th className="py-2 px-3">Línea</th>
                                  <th className="py-2 px-3">Código Ext.</th>
                                  <th className="py-2 px-3">Descripción Ítem</th>
                                  <th className="py-2 px-2">Und.</th>
                                  <th className="py-2 px-3 text-right">Cantidad</th>
                                  <th className="py-2 px-3 text-right">P. Unit.</th>
                                  <th className="py-2 px-3 text-right">Total</th>
                                  <th className="py-2 px-2 text-center">Conf.</th>
                                  <th className="py-2 px-3 text-center">Homologación</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-100 font-mono tabular-nums">
                                {lineasAgrupadas.map(([numLinea, camposMap]) => {
                                  const homLinea = capturaDetalle.homologacion?.lineas.find((l) => l.linea === Number(numLinea));
                                  const codCampo = camposMap['codigo_externo'];
                                  const descCampo = camposMap['descripcion'];
                                  const undCampo = camposMap['unidad_medida'];
                                  const cantCampo = camposMap['cantidad'];
                                  const precCampo = camposMap['precio_unitario'];
                                  const totCampo = camposMap['valor_total'];

                                  const codVal = codCampo?.valor_corregido || codCampo?.valor_extraido || '—';
                                  const descVal = descCampo?.valor_corregido || descCampo?.valor_extraido || '—';
                                  const undVal = undCampo?.valor_corregido || undCampo?.valor_extraido || 'NIU';
                                  const cantVal = cantCampo?.valor_corregido || cantCampo?.valor_extraido || '0.00';
                                  const precVal = precCampo?.valor_corregido || precCampo?.valor_extraido || '0.00';
                                  const totVal = totCampo?.valor_corregido || totCampo?.valor_extraido || '0.00';

                                  // Confianza mínima de la línea entre todos sus campos
                                  const lineConfianzas = Object.values(camposMap)
                                    .map((c) => (c.confianza !== null ? Number(c.confianza) : 100))
                                    .filter((n) => !isNaN(n));
                                  const minLineaConfianza = lineConfianzas.length > 0 ? Math.min(...lineConfianzas) : 100;

                                  return (
                                    <tr key={numLinea} className="hover:bg-slate-50/80 transition-colors">
                                      <td className="py-2 px-3 font-bold text-slate-900">#{numLinea}</td>
                                      <td className="py-2 px-3">
                                        <code className="bg-slate-100 px-1.5 py-0.5 rounded text-[11px] border border-slate-200">
                                          {codVal}
                                        </code>
                                      </td>
                                      <td className="py-2 px-3 font-sans max-w-[200px] truncate" title={descVal}>
                                        {descVal}
                                      </td>
                                      <td className="py-2 px-2 text-slate-600">{undVal}</td>
                                      <td className="py-2 px-3 text-right text-slate-800">
                                        {cantCampo && editingCampoId === cantCampo.id ? (
                                          <div className="flex items-center justify-end gap-1">
                                            <Input
                                              type="text"
                                              value={tempValorCorregido}
                                              onChange={(e) => setTempValorCorregido(e.target.value)}
                                              autoFocus
                                              className="h-6 w-16 text-right text-xs px-1"
                                            />
                                            <Button
                                              type="button"
                                              size="xs"
                                              variant="success"
                                              className="h-6 w-6 p-0"
                                              onClick={() => handleGuardarCorreccion(cantCampo.id)}
                                            >
                                              <Save className="h-3 w-3" />
                                            </Button>
                                            <Button
                                              type="button"
                                              size="xs"
                                              variant="outline"
                                              className="h-6 w-6 p-0"
                                              onClick={() => setEditingCampoId(null)}
                                            >
                                              <X className="h-3 w-3" />
                                            </Button>
                                          </div>
                                        ) : (
                                          <div className="flex items-center justify-end gap-1 group">
                                            <span>{formatearDecimal(cantVal, { min: 2, max: 8, vacio: String(cantVal ?? '') })}</span>
                                            {!capturaDetalle.documento_id && cantCampo && (
                                              <button
                                                type="button"
                                                onClick={() => {
                                                  setEditingCampoId(cantCampo.id);
                                                  setTempValorCorregido(cantCampo.valor_corregido || cantCampo.valor_extraido || '');
                                                }}
                                                className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-400 hover:text-slate-700 p-0.5"
                                                title="Corregir cantidad"
                                              >
                                                <Edit3 className="h-3 w-3" />
                                              </button>
                                            )}
                                          </div>
                                        )}
                                      </td>
                                      <td className="py-2 px-3 text-right text-slate-600">
                                        {precCampo && editingCampoId === precCampo.id ? (
                                          <div className="flex items-center justify-end gap-1">
                                            <Input
                                              type="text"
                                              value={tempValorCorregido}
                                              onChange={(e) => setTempValorCorregido(e.target.value)}
                                              autoFocus
                                              className="h-6 w-20 text-right text-xs px-1"
                                            />
                                            <Button
                                              type="button"
                                              size="xs"
                                              variant="success"
                                              className="h-6 w-6 p-0"
                                              onClick={() => handleGuardarCorreccion(precCampo.id)}
                                            >
                                              <Save className="h-3 w-3" />
                                            </Button>
                                            <Button
                                              type="button"
                                              size="xs"
                                              variant="outline"
                                              className="h-6 w-6 p-0"
                                              onClick={() => setEditingCampoId(null)}
                                            >
                                              <X className="h-3 w-3" />
                                            </Button>
                                          </div>
                                        ) : (
                                          <div className="flex items-center justify-end gap-1 group">
                                            <span>S/ {formatearDecimal(precVal, { min: 4, max: 8, vacio: String(precVal ?? '') })}</span>
                                            {!capturaDetalle.documento_id && precCampo && (
                                              <button
                                                type="button"
                                                onClick={() => {
                                                  setEditingCampoId(precCampo.id);
                                                  setTempValorCorregido(precCampo.valor_corregido || precCampo.valor_extraido || '');
                                                }}
                                                className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-400 hover:text-slate-700 p-0.5"
                                                title="Corregir precio unitario"
                                              >
                                                <Edit3 className="h-3 w-3" />
                                              </button>
                                            )}
                                          </div>
                                        )}
                                      </td>
                                      <td className="py-2 px-3 text-right font-bold text-slate-900">
                                        {totCampo && editingCampoId === totCampo.id ? (
                                          <div className="flex items-center justify-end gap-1">
                                            <Input
                                              type="text"
                                              value={tempValorCorregido}
                                              onChange={(e) => setTempValorCorregido(e.target.value)}
                                              autoFocus
                                              className="h-6 w-20 text-right text-xs px-1"
                                            />
                                            <Button
                                              type="button"
                                              size="xs"
                                              variant="success"
                                              className="h-6 w-6 p-0"
                                              onClick={() => handleGuardarCorreccion(totCampo.id)}
                                            >
                                              <Save className="h-3 w-3" />
                                            </Button>
                                            <Button
                                              type="button"
                                              size="xs"
                                              variant="outline"
                                              className="h-6 w-6 p-0"
                                              onClick={() => setEditingCampoId(null)}
                                            >
                                              <X className="h-3 w-3" />
                                            </Button>
                                          </div>
                                        ) : (
                                          <div className="flex items-center justify-end gap-1 group">
                                            <span>S/ {formatearDecimal(totVal, { vacio: String(totVal ?? '') })}</span>
                                            {!capturaDetalle.documento_id && totCampo && (
                                              <button
                                                type="button"
                                                onClick={() => {
                                                  setEditingCampoId(totCampo.id);
                                                  setTempValorCorregido(totCampo.valor_corregido || totCampo.valor_extraido || '');
                                                }}
                                                className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-400 hover:text-slate-700 p-0.5"
                                                title="Corregir valor total"
                                              >
                                                <Edit3 className="h-3 w-3" />
                                              </button>
                                            )}
                                          </div>
                                        )}
                                      </td>
                                      <td className="py-2 px-2 text-center">
                                        {renderConfianzaBadge(String(minLineaConfianza))}
                                      </td>
                                      <td className="py-2 px-3 text-center">
                                        {homLinea?.estado === 'HOMOLOGADA' ? (
                                          <Badge
                                            variant="success"
                                            size="xs"
                                            dot
                                            data-testid="linea-homologada"
                                            title={homLinea.equivalencia_id ? `Equivalencia #${homLinea.equivalencia_id} (por ${homLinea.criterio === 'codigo' ? 'código' : 'descripción'})` : homLinea.motivo}
                                          >
                                            Homologada → {homLinea.producto_codigo}
                                          </Badge>
                                        ) : (
                                          <>
                                            <Button
                                              type="button"
                                              variant="outline"
                                              size="xs"
                                              onClick={async () => {
                                                const proveedorId = await proveedorDeCaptura();
                                                setActiveTab('homologaciones');
                                                setCapturaEquivId(capturaDetalle.id);
                                                setRucEsperadoEquiv(capturaDetalle.homologacion?.proveedor?.documento || rucEmisorCaptura);
                                                setFormCodigoExt(codVal === '—' ? '' : codVal);
                                                setFormDescExt(descVal === '—' ? '' : descVal);
                                                setFormTerceroId(proveedorId);
                                                if (unidadesMedida.some((u) => u.codigo === undVal)) setFormUnidadExt(undVal);
                                                setShowEquivModal(true);
                                              }}
                                            >
                                              Homologar
                                            </Button>
                                            {homLinea?.motivo?.startsWith('existe') && (
                                              <span className="block mt-1 font-sans text-[10px] text-amber-700">{homLinea.motivo}</span>
                                            )}
                                          </>
                                        )}
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </CardContent>
                      </Card>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </TabsContent>

        {/* ==================================================================== */}
        {/* PESTAÑA 2: CATÁLOGO DE HOMOLOGACIÓN (`ProductoEquivalencia`)        */}
        {/* ==================================================================== */}
        <TabsContent value="homologaciones" className="space-y-5 pt-2">
          {/* Barra de Filtros y Acciones */}
          <Card>
            <CardHeader className="pb-3 border-b border-slate-100">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <CardTitle className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                    <Filter className="h-4 w-4 text-indigo-600" />
                    Catálogo de Equivalencias y Homologación de Proveedores
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Regla de Oro: Solo las equivalencias confirmadas por un usuario humano se aplican automáticamente en los comprobantes.
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setShowSugerirModal(true)}
                  >
                    <Sparkles className="h-3.5 w-3.5 mr-1 text-indigo-600" />
                    Probar Sugerencia
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      setRucEsperadoEquiv('');
                      setCapturaEquivId(null);
                      setShowEquivModal(true);
                    }}
                  >
                    <Plus className="h-3.5 w-3.5 mr-1" />
                    Nueva Equivalencia
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="equiv-proveedor-filter">Filtrar por Proveedor (Tercero)</Label>
                  <Select
                    id="equiv-proveedor-filter"
                    value={filtroTerceroId}
                    onChange={(e) => setFiltroTerceroId(e.target.value)}
                  >
                    <option value="">Todos los Proveedores</option>
                    {terceros.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.numero_documento} - {t.razon_social}
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="equiv-busqueda-input">Buscar Código o Descripción</Label>
                  <Input
                    id="equiv-busqueda-input"
                    type="text"
                    placeholder="Buscar por SKU externo o producto interno..."
                    value={busquedaEquiv}
                    onChange={(e) => setBusquedaEquiv(e.target.value)}
                    leftIcon={<Search className="h-4 w-4" />}
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Tabla de Equivalencias */}
          <Card>
            <CardHeader className="py-3 px-4 border-b border-slate-200 bg-slate-50/50 flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-sm font-semibold text-slate-900">
                  Equivalencias Registradas ({equivalenciasFiltradas.length})
                </CardTitle>
                <CardDescription className="text-xs">
                  Mapeo directo entre SKUs de proveedores y presentaciones del catálogo interno
                </CardDescription>
              </div>
              <Badge variant="neutral" className="text-xs font-mono">
                {equivalenciasFiltradas.length} de {equivalencias.length}
              </Badge>
            </CardHeader>
            <CardContent className="p-0">
              {equivalenciasFiltradas.length === 0 ? (
                <div className="py-12 text-center text-xs text-slate-500">
                  No existen equivalencias registradas para los filtros aplicados.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-600 border-b border-slate-200">
                        <th className="py-2.5 px-3">Proveedor (Tercero)</th>
                        <th className="py-2.5 px-3">Código Externo</th>
                        <th className="py-2.5 px-3">Descripción Externa</th>
                        <th className="py-2.5 px-3">Und. Ext.</th>
                        <th className="py-2.5 px-3">Producto Interno</th>
                        <th className="py-2.5 px-3">Und. Base</th>
                        <th className="py-2.5 px-3 text-right">Factor Conv.</th>
                        <th className="py-2.5 px-3">Confirmado Por</th>
                        <th className="py-2.5 px-3 text-center">Estado</th>
                        <th className="py-2.5 px-3 text-center">Acciones</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {equivalenciasFiltradas.map((eq) => (
                        <tr key={eq.id} className="hover:bg-slate-50/80 transition-colors">
                          <td className="py-2.5 px-3">
                            <span className="font-semibold text-slate-900 block truncate max-w-[180px]">
                              {eq.tercero_info?.razon_social}
                            </span>
                            <span className="font-mono text-[11px] text-slate-500">
                              RUC: {eq.tercero_info?.numero_documento}
                            </span>
                          </td>
                          <td className="py-2.5 px-3">
                            <code className="bg-slate-100 px-1.5 py-0.5 rounded text-[11px] border border-slate-200 font-mono">
                              {eq.codigo_externo || '—'}
                            </code>
                          </td>
                          <td className="py-2.5 px-3 text-slate-700 max-w-[200px] truncate" title={eq.descripcion_externa || ''}>
                            {eq.descripcion_externa || '—'}
                          </td>
                          <td className="py-2.5 px-3 text-slate-600 font-mono">{eq.unidad_externa_codigo || 'NIU'}</td>
                          <td className="py-2.5 px-3">
                            <span className="font-mono font-semibold text-slate-900">
                              {eq.producto_info?.producto_codigo}
                            </span>{' '}
                            <span className="text-slate-600">· {eq.producto_info?.producto_descripcion}</span>
                          </td>
                          <td className="py-2.5 px-3 text-slate-600 font-mono">{eq.producto_info?.unidad_codigo}</td>
                          <td className="py-2.5 px-3 text-right font-mono tabular-nums font-bold text-slate-900">
                            {formatearDecimal(eq.factor_conversion, { min: 4, max: 8 })}
                          </td>
                          <td className="py-2.5 px-3 text-slate-600 text-[11px]">
                            <span>{eq.confirmado_por_username || 'Admin'}</span>
                            {eq.confirmado_en && (
                              <span className="block font-mono text-[10px] text-slate-400">
                                {new Date(eq.confirmado_en).toLocaleDateString('es-PE')}
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 px-3 text-center">
                            <Badge
                              variant={eq.activa ? 'success' : 'destructive'}
                              size="xs"
                              dot
                            >
                              {eq.activa ? 'ACTIVA' : 'INACTIVA'}
                            </Badge>
                          </td>
                          <td className="py-2.5 px-3 text-center">
                            <Button
                              type="button"
                              variant="outline"
                              size="xs"
                              onClick={() => handleToggleEquivalencia(eq)}
                            >
                              {eq.activa ? 'Desactivar' : 'Activar'}
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Modal Nueva Equivalencia */}
          {showEquivModal && (
            <div
              role="presentation"
              className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-150"
            >
              <section
                role="dialog"
                aria-modal="true"
                className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-6 shadow-xl animate-in zoom-in-95 duration-150"
              >
                <div className="flex items-start justify-between pb-4 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <Plus className="h-5 w-5 text-indigo-600" />
                    <h3 className="text-base font-semibold text-slate-900">
                      Nueva Equivalencia de Producto (Homologación)
                    </h3>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowEquivModal(false)}
                    className="text-slate-400 hover:text-slate-600"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>

                <form onSubmit={handleCrearEquivalencia} className="mt-4 space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="form-tercero">Proveedor Emisor (*)</Label>
                    <Select
                      id="form-tercero"
                      value={formTerceroId}
                      onChange={(e) => setFormTerceroId(e.target.value)}
                      required
                    >
                      <option value="">Seleccione un proveedor...</option>
                      {capturaEquivId && !capturaDetalle?.homologacion?.proveedor?.tercero_id && capturaDetalle?.homologacion?.proveedor?.documento && (
                        <option value={PROVEEDOR_DE_CAPTURA}>
                          {capturaDetalle.homologacion.proveedor.documento} - {capturaDetalle.homologacion.proveedor.nombre || 'Proveedor del comprobante'} (nuevo: se registra al guardar)
                        </option>
                      )}
                      {terceros.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.numero_documento} - {t.razon_social}
                        </option>
                      ))}
                    </Select>
                    {rucEsperadoEquiv && (
                      <p className="text-[11px] text-slate-500">
                        RUC emisor del comprobante: <span className="font-mono">{rucEsperadoEquiv}</span>
                      </p>
                    )}
                    {rucEsperadoEquiv && formTerceroId && formTerceroId !== PROVEEDOR_DE_CAPTURA &&
                      terceros.find((t) => String(t.id) === String(formTerceroId))?.numero_documento !== rucEsperadoEquiv && (
                      <p role="alert" data-testid="aviso-proveedor-distinto" className="text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                        El proveedor elegido no es el emisor del comprobante: la equivalencia no se usará con sus XML.
                      </p>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="form-cod-ext">Código SKU del Proveedor</Label>
                      <Input
                        id="form-cod-ext"
                        type="text"
                        value={formCodigoExt}
                        onChange={(e) => setFormCodigoExt(e.target.value)}
                        placeholder="Ej. TAL-500W-PROV"
                        className="font-mono text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="form-und-ext">Unidad Externa</Label>
                      <Select
                        id="form-und-ext"
                        value={formUnidadExt}
                        onChange={(e) => setFormUnidadExt(e.target.value)}
                      >
                        {unidadesMedida.map((u) => (
                          <option key={u.codigo} value={u.codigo}>
                            {u.codigo} - {u.descripcion}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="form-desc-ext">Descripción del Ítem en Factura</Label>
                    <Input
                      id="form-desc-ext"
                      type="text"
                      value={formDescExt}
                      onChange={(e) => setFormDescExt(e.target.value)}
                      placeholder="Ej. TALADRO INDUSTRIAL IMPACTO 500W"
                    />
                  </div>

                  <div className="border-t border-slate-100 pt-3 space-y-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="form-producto-interno">Producto Interno FACT-KARD (*)</Label>
                      <Select
                        id="form-producto-interno"
                        value={formProductoId}
                        onChange={(e) => setFormProductoId(e.target.value)}
                        required
                      >
                        <option value="">Seleccione el producto de nuestro catálogo...</option>
                        {productos.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.codigo_interno} - {p.descripcion}
                          </option>
                        ))}
                      </Select>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="form-und-interna">Presentación / Unidad</Label>
                        <Select
                          id="form-und-interna"
                          value={formProductoUnidadId}
                          onChange={(e) => setFormProductoUnidadId(e.target.value)}
                          required
                          disabled={productoUnidades.length === 0}
                        >
                          {productoUnidades.map((pu) => (
                            <option key={pu.id} value={pu.id}>
                              {pu.unidad_codigo} (Factor: {pu.factor_a_base}) {pu.es_base ? '★ Base' : ''}
                            </option>
                          ))}
                        </Select>
                      </div>

                      <div className="space-y-1.5">
                        <Label htmlFor="form-factor">Factor de Conversión (*)</Label>
                        <Input
                          id="form-factor"
                          type="number"
                          step="0.00000001"
                          min="0.00000001"
                          value={formFactor}
                          onChange={(e) => setFormFactor(e.target.value)}
                          required
                          className="font-mono tabular-nums text-xs"
                        />
                        <span className="text-[10px] text-slate-500 block">
                          1 Und. Ext. = {formFactor} Und. Base
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setShowEquivModal(false)}
                    >
                      Cancelar
                    </Button>
                    <Button
                      type="submit"
                      variant="primary"
                      size="sm"
                      disabled={loading}
                    >
                      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Check className="h-3.5 w-3.5 mr-1.5" />}
                      Confirmar Homologación
                    </Button>
                  </div>
                </form>
              </section>
            </div>
          )}

          {/* Modal Probar Sugerencia */}
          {showSugerirModal && (
            <div
              role="presentation"
              className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-150"
            >
              <section
                role="dialog"
                aria-modal="true"
                className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-6 shadow-xl animate-in zoom-in-95 duration-150"
              >
                <div className="flex items-start justify-between pb-4 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-5 w-5 text-indigo-600" />
                    <h3 className="text-base font-semibold text-slate-900">
                      Probador de Sugerencia Automática
                    </h3>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowSugerirModal(false)}
                    className="text-slate-400 hover:text-slate-600"
                  >
                    <X className="h-5 w-5" />
                  </button>
                </div>

                <form onSubmit={handleProbarSugerencia} className="mt-4 space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="test-tercero">Proveedor (*)</Label>
                    <Select
                      id="test-tercero"
                      value={testTerceroId}
                      onChange={(e) => setTestTerceroId(e.target.value)}
                      required
                    >
                      <option value="">Seleccione proveedor...</option>
                      {terceros.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.numero_documento} - {t.razon_social}
                        </option>
                      ))}
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="test-cod-ext">Código SKU Externo</Label>
                    <Input
                      id="test-cod-ext"
                      type="text"
                      placeholder="Ej. SKU-PROV-A"
                      value={testCodigoExt}
                      onChange={(e) => setTestCodigoExt(e.target.value)}
                      className="font-mono text-xs"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="test-desc-ext">Descripción Externa</Label>
                    <Input
                      id="test-desc-ext"
                      type="text"
                      placeholder="Ej. TALADRO ACERO 500W"
                      value={testDescExt}
                      onChange={(e) => setTestDescExt(e.target.value)}
                    />
                  </div>

                  <Button
                    type="submit"
                    variant="primary"
                    disabled={loading}
                    className="w-full"
                  >
                    {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Search className="h-3.5 w-3.5 mr-1.5" />}
                    Consultar Motor de Sugerencia
                  </Button>
                </form>

                {sugerenciaResultado && (
                  <div className="mt-4 p-4 rounded-lg bg-slate-50 border border-slate-200 text-xs space-y-2">
                    <span className="font-semibold text-slate-800 block">Resultado del Análisis:</span>
                    {sugerenciaResultado.encontrado ? (
                      <div className="text-emerald-800 bg-emerald-50 p-2.5 rounded border border-emerald-200">
                        <div className="flex items-center gap-1.5 font-semibold">
                          <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                          {sugerenciaResultado.mensaje}
                        </div>
                        <div className="mt-1 font-mono text-[11px]">
                          Producto Vinculado:{' '}
                          <strong>
                            {sugerenciaResultado.sugerencia?.producto_info?.producto_codigo} -{' '}
                            {sugerenciaResultado.sugerencia?.producto_info?.producto_descripcion}
                          </strong>{' '}
                          (Factor: {sugerenciaResultado.sugerencia?.factor_conversion})
                        </div>
                      </div>
                    ) : (
                      <div className="text-rose-800 bg-rose-50 p-2.5 rounded border border-rose-200">
                        <div className="flex items-center gap-1.5 font-semibold">
                          <AlertCircle className="h-4 w-4 text-rose-600 shrink-0" />
                          {sugerenciaResultado.mensaje}
                        </div>
                        <div className="mt-1 text-[11px]">
                          Estado retornado: <code className="font-mono bg-white px-1 py-0.5 rounded border border-rose-200">{sugerenciaResultado.estado}</code> (generaría incidencia contable).
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </section>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default CapturaHomologacionPage;
