/**
 * B17A-QA-001 — código del Catálogo 07 de una línea GRATUITA ya guardada, en el detalle del
 * comprobante. Muestra el valor guardado y (ADMIN, comprobante no anulado) permite registrarlo o
 * corregirlo. Solo información tributaria: no cambia importes, costo ni Kardex.
 */
import { useState } from 'react'
import { cambiarCodigoAfectacion, type Documento, type DocumentoDetalle } from '../../api/documentos'
import type { CodigoAfectacionIgv } from '../../api/catalogos'
import { mensajesDeErrorApi } from '../../utils/errores'

interface Props {
  documento: Documento
  detalle: DocumentoDetalle
  opciones: CodigoAfectacionIgv[]
  catalogo: CodigoAfectacionIgv[]
  editable: boolean
  onActualizado: (doc: Documento) => void
}

export function CodigoAfectacionLinea({ documento, detalle, opciones, catalogo, editable, onActualizado }: Props) {
  const guardado = detalle.codigo_afectacion_igv ?? ''
  const [valor, setValor] = useState(guardado)
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const descripcion = catalogo.find((c) => c.codigo === guardado)?.descripcion

  if (!editable) {
    return (
      <span className="block text-[10px] text-slate-500" data-testid="codigo-afectacion-guardado">
        {guardado ? `Cat. 07: ${guardado}${descripcion ? ` — ${descripcion}` : ''}` : 'Cat. 07: sin código'}
      </span>
    )
  }

  const guardar = async (codigo: string) => {
    setValor(codigo)
    if (!codigo || codigo === guardado) return
    setGuardando(true)
    setError(null)
    try {
      onActualizado(await cambiarCodigoAfectacion(documento.id, detalle.id, codigo))
    } catch (e) {
      setError(mensajesDeErrorApi(e, 'No se pudo guardar el código.').join(' '))
      setValor(guardado)
    } finally {
      setGuardando(false)
    }
  }

  return (
    <span className="mt-1 block">
      <select
        aria-label={`Código Catálogo 07 de la línea ${detalle.linea}`}
        data-testid="codigo-afectacion-detalle"
        className={`w-full min-w-[12rem] h-7 rounded border bg-white px-1.5 text-[11px] ${guardado ? 'border-slate-200' : 'border-amber-400'}`}
        value={valor}
        disabled={guardando}
        onChange={(e) => guardar(e.target.value)}
      >
        <option value="">Código Cat. 07…</option>
        {opciones.map((c) => <option key={c.codigo} value={c.codigo}>{c.codigo} — {c.descripcion}</option>)}
      </select>
      {error && <span className="block text-[10px] text-rose-600" role="alert">{error}</span>}
    </span>
  )
}
